# 导入追溯持久化与显式增量索引同步

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-sync.en.md) | 简体中文

后续已补[共享 CLI 管理入口](./knowledge-sync-entries.md)及[完整 TUI 主路径](./knowledge-sync-tui.md)。其独立 282 项合并定向证据见[同步与计量验收](./acceptance-2026-10-01-sync-usage.md)，下文保留底层初次验收范围。

2.0.0 Experimental，已随 2.0.0 发布。本轮获准后在现有项目净环境执行知识合并定向回归：**115 passed / 2 skipped，117 项收集，4.78 秒**，包括本模块 31 项、真实格式解析 15 项、文件/Writer/跨链路与导出检查。两个跳过仍为 Windows symlink/FIFO 平台限制，不是解析依赖缺失。不挪用上一轮 1811 项作为新增同步能力的证据，也不与含重叠包检查的其他组直接相加。未连接真实 Qdrant/Embedding、未验证真实费用/检索质量，也没有发布。默认构造与规划无外部副作用。

## 持久 trace 与跨版本向量缓存

`KnowledgeImportStore` 是可替换的 `save(trace, confirm_write=...)` / `load(namespace, version)` 协议。`SQLiteKnowledgeImportStore` 显式初始化专用 SQLite，保存已读取的解析原文、原始/解析指纹、快照与块偏移。相同版本/内容重复保存幂等，冲突不覆盖；读取核对规范 JSON、摘要、来源映射和重新生成的分块。它不会读取或写回源文件，不归档原始二进制。

```python
from w_agent import (
    SQLiteKnowledgeImportStore, LocalTextKnowledgeImporter,
    prepare_traced_knowledge_import, prepare_knowledge_sync_index,
    KnowledgeSyncPlan, SQLiteKnowledgeSyncJournal,
    QdrantKnowledgeSyncWriter, QdrantVectorWriter, QdrantVectorSearch,
    execute_knowledge_sync,
)

traces = SQLiteKnowledgeImportStore("imports.sqlite")
await traces.initialize(confirm_create=True)  # 父目录须已存在
# 首次导入时 previous_trace/previous_index 为 None。
# 后续应显式 load 上次 trace，并从已完成同步的 load_plan(digest).current 取向量缓存。
loaded = await LocalTextKnowledgeImporter(root).load(
    ("manual.md",), confirm_read=True,
    previous=previous_trace.imported if previous_trace is not None else None,
)
current_trace = prepare_traced_knowledge_import("manual", "v2", loaded)
await traces.save(current_trace, confirm_write=True)
current_index = await prepare_knowledge_sync_index(
    current_trace, "host-pinned-model-v1", 768, embedder,
    previous=previous_index, confirm_embedding=True,
    confirm_reuse_digest=previous_index.digest if previous_index is not None else None,
)
```

以上是宿主接线示例，未执行真实服务。宿主先审查旧缓存，再给出其精确摘要；不能由模型自行把对象摘要当作批准。实际模型与预处理版本由宿主固定，标签和摘要不认证模型身份。缺少复用批准且存在可复用点时，在调用 Embedding 前拒绝。

新增 `wagent-knowledge-sync-point-v1` 与已有 snapshot-bound point-v1 是两套明确隔离的身份格式。稳定 ID 绑定 namespace、parser_key、完整文件记录（路径/raw/text 摘要/长度/来源文档 ID）、chunk 配置、字符/字节区间、块正文、来源、标题、embedding_key 和维度，**不绑定 snapshot version**。同内容仅改版本时复用全部精确向量、零 Embedding 调用；新增文件和变化文件的块才重新嵌入。文件中任意内容、BOM、解析版本、分块配置、模型标签变化都可能使该文件全部块失效；这是文件级增量，不是语义分块去重。旧格式不自动迁移。

`KnowledgeSyncIndex` 为完整有界向量缓存，最多 1024 点、合计 1048576 个向量值。准备前校验完整输入；Embedding 失败可能已经产生费用，无自动重试/退款承诺。缓存值与相同稳定 ID 冲突时，计划拒绝替换。`KnowledgeSyncPlan` 严格序列化并绑定前后完整缓存，`stage()` 持久保存 trace 与精确向量；重开后 `load_plan(digest)` 可继续，无需重新 Embedding。

## 明确批准差异 upsert 与删除

```python
writer = QdrantKnowledgeSyncWriter(QdrantVectorWriter(
    QdrantVectorSearch("http://localhost:6333", "dedicated_knowledge")
))
journal = SQLiteKnowledgeSyncJournal("sync.sqlite")
await journal.initialize(confirm_create=True)
plan = KnowledgeSyncPlan(writer.endpoint, writer.vector_name, current_index, previous_index)
preview = plan.summary()  # 无正文/向量；独立展示 upsert/delete 摘要及数量
# 用户/宿主审查目标、数量、内容变更及删除范围后，提供独立批准的摘要。
result = await execute_knowledge_sync(
    plan, writer, journal,
    confirm_plan_digest=approved_plan_digest,
    confirm_upsert_digest=approved_upsert_digest,
    confirm_delete_digest=approved_delete_digest,
    confirm_record=True,
)
```

`upsert_points` 仅为 current 中不在 previous 的点；`delete_ids` 严格为 previous 自有 ID 减 current ID。摘要绑定完整计划和具体批次，不接受只批准新增来执行删除。每批最多 128 点，先完成所有 upsert，再发送删除；无变更和空初始版本仍需要 plan/record 确认，显式推进本地 head，但不发网络请求。

`KnowledgeSyncWriter` 协议可替换。Qdrant 模板复用原 `QdrantVectorWriter`，删除按[官方 ID 删除接口](https://api.qdrant.tech/api-reference/points/delete-points)发送 `POST /collections/{collection}/points/delete?wait=true`，正文只有精确 IDs，不使用 filter、不删除集合。删除会移除整点（包括所有 named vectors/payload）；必须使用宿主独占的专用集合。旧版本被移除点的远端检索不再保证可用，已归档解析原文仍保留；需要所有旧版本远端可检索时，继续使用旧的版本固定索引/不同集合。

`SyncVectorKnowledgeRetriever` 将同步点 ID 映射回当前 trace 的快照文档 ID，限定当前候选并从本地解析正文；不相信远端 payload。索引同步成功不代表检索质量或远端长期存在性。

## 日志、重启与安全重试

`KnowledgeSyncJournal` 可替换；SQLite 模板在同库事务中维护每个 collection endpoint 的 head 与 active plan。新计划必须接续已完成 head，未决计划阻止分叉/新 genesis；改变 named vector 不可复用同一 head。每批 `ready → pending` 持久提交后才进入 transport。`completed` 批次重启后跳过，`ready` 批次可继续；`pending/unknown/acknowledged` 不自动重放、不进入下一批、不推进 head。发包后回执落库失败保留 pending；取消可能已发送/提交。

确定发包前拒绝的 `not-sent` 支持独立批准重试：

```python
from w_agent import knowledge_sync_retry_digest

# inspect_observations 查看原始状态、generation、operation_id 与证据引用。
# 主机审查确认 not-sent 后，批准该精确 plan/batch/generation 的重试摘要。
await journal.retry_not_sent(
    plan.digest, batch=0, generation=0, retry_id="manual-retry-1",
    confirm_retry_digest=approved_retry_digest, confirm_write=True,
)
# 重新 execute 仍需原计划及动作批准，不会重新 Embedding。
```

`knowledge_sync_retry_digest(plan.digest, batch, generation)` 用于展示待批准摘要。事务先将旧 not-sent 代次插入不可覆盖的 `sync_retries`，再给下一代设置 ready；旧 generation、重复 retry_id 和未决结果拒绝。最多保留 64 次显式重试/计划。`inspect_retries()` 提供原代次记录，`inspect_observations()` 保留当前原始 receipt/evidence；完成对账不会抹掉原 acknowledged/unknown 观察。

`reconcile_completed()` 仅在宿主独立核验已应用、排空迟到效果并明确授权写入后，将 pending/unknown/acknowledged 解释为已完成；要提供有界 evidence_ref。它不联网核验，不是证据真实性认证。未知结果的 not-applied 重试/撤销流程尚未提供，仍拒绝重放；绝不能虚报已完成以解锁。

端点必须 canonical：小写 hostname，无显式默认端口、末尾/重复斜杠、dot/编码歧义 path、凭据/query/fragment。不同拼法在计划和适配器构造时拒绝；不同 DNS 名称、代理转发到同集合、其他数据库或绕过同步入口的 writer 仍由宿主协调，这不是远端/跨库租约。

## 存储与验证边界

trace store 与 sync journal 分别是独立 application_id、`user_version=1` 的专用库；sync 初始 schema 含 targets/plans/batches/retries 四表，不采用先前试验 schema、不修改其他知识库、不自动迁移。构造不 I/O、读取不创建缺失库、创建不建父目录。所有正文/向量/引用明文保存；默认最多 1024 记录/计划、payload 合计 512 MiB，单 trace 96 MiB、单 sync plan 256 MiB，不等于物理磁盘/内存配额。目录/SQLite 文件须可信。取消等待已启动 worker，不能承诺回滚。

本轮专属 `tests/test_knowledge_sync.py` 的 31 项回归通过，覆盖真实临时 SQLite 重开、增量复用/模型和源绑定、精确删除、独立批准、未知状态/取消/ack 屏障、并发 claim、两批恢复、空计划、canonical endpoint、损坏和显式 not-sent 代次恢复。四个新模块 compileall 通过。外部调用使用注入传输，未验收真实 Qdrant。主代理本轮知识合并定向结果为 115 passed / 2 skipped；此前 1811 项不作为这些新增行为的证明。
