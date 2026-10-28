# 知识索引清单与持久写入回执

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-index-journal.en.md) | 简体中文

完整向量可另存[精确计划暂存库](./knowledge-index-plans.md)，审批后使用同一计划执行而不重嵌入。该库与本页回执日志分离，暂存不是写入完成或许可。

相关入口包括[索引日志管理 API/CLI/TUI](./knowledge-index-management.md) 的查看/显式对账，以及[计划准备保存/授权执行入口](./knowledge-plan-actions.md)；远端核验仍待实现。

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。本地 SQLite/替身传输及无头界面回归已通过；未调用真实远端、安装依赖或发布。

## 记录什么，不证明什么

`knowledge_index_manifest(index, writer)` 从[快照向量身份](./knowledge-vectors.md)与已有 Writer 纯构造 `KnowledgeIndexManifest`：包含快照摘要、宿主 Embedding 标签/维度、精确 endpoint/vector_name 和全部预期点 ID。清单摘要绑定这些字段及格式版本，不包含正文、向量值或 API key。

清单不是写入许可、数字签名、执行租约或索引质量证明。endpoint、标签和 ID 仍可敏感，应由宿主管理存储权限；不要把秘密放进这些字段。凭据不参与摘要，轮换凭据/账号后仍需宿主重新审查目标权限。直接构造清单时由宿主保证预期集合完整；工厂使用整个非空 `KnowledgeVectorIndex`。

`KnowledgeIndexAttempt` 记录尝试 ID、精确计划摘要、点 ID 子集、结果状态及可选远端 operation ID。日志不存向量值，无法从日志重建写入计划，也不会自动执行它。

## 分开的提交边界

```python
from w_agent import (
    SQLiteKnowledgeIndexJournal, knowledge_index_manifest, journaled_knowledge_upsert,
)
from my_application import review_exact_upsert

# index、writer、points 由宿主按快照向量文档准备；不在这里自动生成。
manifest = knowledge_index_manifest(index, writer)
journal = SQLiteKnowledgeIndexJournal("knowledge-index-journal.sqlite")
await journal.initialize(confirm_create=True)  # 父目录必须已存在；使用独立数据库。
plan = writer.plan(points)
reviewed_digest = await review_exact_upsert(plan)
receipt = await journaled_knowledge_upsert(
    writer, plan, manifest, journal,
    attempt_id="build-v1-batch-001", confirm_digest=reviewed_digest, confirm_record=True,
)
state = await journal.inspect(manifest.digest)
print(state.all_points_confirmed, state.unresolved_attempt_ids)
```

示例未执行。宿主仍分别授权正文 Embedding、远端覆盖写入、本地日志创建/写入。`journaled_knowledge_upsert()` 先校验目标、点集、维度及精确计划确认，再持久化 `pending`，然后最多发送一次，最后持久化回执。写入前不能确认 pending 记录时不发送；同一 manifest 下相同尝试 ID 再次 begin 会拒绝，即便计划完全相同，也不会自动重发。

本地 pending 提交、远端 upsert、本地最终回执提交是三个独立动作，不是跨存储事务。崩溃可能发生在任何两个动作之间，因而 pending 既可能代表“尚未发送”，也可能代表“远端已成功但未记录”。日志不是可自动执行的恢复队列。

## 状态与覆盖率

- `pending`：本地已登记，但还没有最终观察。必须视为未确定，不能假设没写入。
- `completed`：保存了与计划摘要、点数量相符的 `QdrantWriteResult(status="completed")`。表示收到对应完成回执，不证明当前远端内容仍存在。
- `acknowledged`：仅保存已接收回执，仍未确定，不计入完成。
- `unknown`：已进入写入或无法确定其结果，仍未确定，不自动重试。
- `not-sent`：Writer 明确报告尚未进入传输。不会产生新的完成覆盖，也不会撤销此前完成回执。

`confirmed_point_ids` 只包含有效结果为 completed 且不被任何未对账的 pending/acknowledged/unknown 尝试覆盖的点。有效结果来自原始完成回执，或下述宿主确认的对账决定。`all_points_confirmed` 仅在全部预期点符合该条件时为 True。一个新未确定尝试会使它与旧成功重叠的点暂不计入完成；其他已确认点仍保留。即使后续重试又成功，旧未知尝试仍阻止完成判定，直到宿主有充分证据完成显式对账。

`unresolved_attempt_ids` 列出未确定尝试。上述属性只基于本地日志，不探测远端存在性、正确模型、检索相关性、数据保留或索引服务的后续修改；不得直接展示为“已验收可用”。空索引不创建该非空清单，无需伪造一条空写入。

## 可替换协议与持久化

`KnowledgeIndexJournal` 定义异步 `begin()` / `record()` / `inspect()`，可由宿主替换。`SQLiteKnowledgeIndexJournal` 是本地实现；`KnowledgeIndexJournalSnapshot` 是不可变读取结果。构造不执行 I/O；`initialize(confirm_create=True)` 才创建/核对独立数据库，不修改现有知识正文快照库、不创建父目录、不自动迁移其他数据库。

宿主可手动 `begin(manifest, attempt_id, plan, confirm_write=True)`，执行自己的流程后 `record(..., outcome=..., receipt=..., confirm_write=True)`；受信宿主必须据真实对应调用记录，不能把旧回执或别的进程的调用结果挪作当前尝试的证据。协议不验证远端回执的真实性，也不提供活跃调用租约。

- begin 在事务内拒绝重复尝试 ID；目标、vector_name、点子集和维度必须匹配清单，跨批重复点可以存在，但覆盖率按点去重。
- record 只能将 pending 转为一个最终观察。completed/acknowledged 必须携带匹配状态、计划摘要与点数量的类型化回执；unknown/not-sent 不接受远端回执。
- 相同最终观察可重复保存，用于本地调用结果不确定时核对；不同观察不能覆盖已保存结果。对账另存决定，不升级或抹除原始 acknowledged/unknown；已对账的 pending 也不再接受迟到的 record 改写。
- `BEGIN IMMEDIATE` 串行化同库写入检查。两个独立连接不能同时登记同一个尝试 ID；这不是不同 manifest/数据库之间的去重，也不阻止宿主另取新 ID 明确发起另一调用。
- 每清单最多 1024 次尝试，每次 1–128 个点，清单最多 1024 个预期点。数据库最多 1024 个清单，单条规范日志最多 8 MiB，总 payload 最多 128 MiB；不是物理磁盘、SQLite 日志或进程内存配额。数据量更大时替换协议实现。
- 读取使用只读连接，限制 payload 字节并校验规范 JSON、重复键、格式、摘要、清单身份、点集及尝试唯一性；损坏失败，不返回部分状态。日志存储的是最终观察不可覆盖的逻辑记录，不是每次调用都新增一行的事件日志。
- `timeout=5` 默认控制 SQLite 锁等待，不是整体截止时间。线程操作在取消时排空并关闭连接后才传播取消，可能已经提交，不能假定回滚。所有连接按操作关闭，无常驻连接。
- 数据库及父目录必须可信；内容摘要不是认证，无法抵抗同时篡改内容和摘要的攻击者。保存的 endpoint/Embedding 标签/ID/操作号并非公开信息或匿名数据。

## 宿主依据独立证据对账

可选 `KnowledgeIndexReconciler` 协议定义 `reconcile()`，不强制已有 `KnowledgeIndexJournal` 插件实现新能力。SQLite 模板实现两者。`KnowledgeIndexReconciliation` 绑定对账 ID、清单摘要、尝试 ID、精确计划摘要、预期原始状态、决定结果、证据引用及操作者引用。

先由宿主停止并排空相关工作，确认该次本地/远端调用不会再产生迟到效果，再审查与该次尝试和目标相符的独立证据。仅取消本地协程、搜索不到点或看到相同点 ID 都不够。若不能排除迟到效果或只有部分点的证据，保留未确定状态，不提交整次尝试的决定。

```python
from w_agent import KnowledgeIndexReconciliation

# 假定 host_review 是宿主已完成独立审查的结果，不是框架自动生成。
# journal、manifest 指向既有日志；本例不重新发送计划。
decision = KnowledgeIndexReconciliation(
    reconciliation_id=host_review.id,
    manifest_digest=manifest.digest,
    attempt_id=host_review.attempt_id,
    plan_digest=host_review.plan_digest,
    expected_outcome=host_review.original_outcome,
    outcome=host_review.outcome,
    evidence_ref=host_review.evidence_ref,
    actor_ref=host_review.actor_ref,
)
state = await journal.reconcile(
    decision, confirm_inactive=True, confirm_write=True,
)
print(state.effective_outcome(decision.attempt_id))
```

示例未执行；两个确认参数必须为字面布尔 True。`confirm_inactive` 是宿主声明，不是租约或框架核实的远端事实。库不抓取证据、不验证操作者身份、不询问远端，也不执行/重放写入。

- 仅对原始 pending/acknowledged/unknown 对账。`completed` 表示宿主确认该次精确计划全部完成；`not-applied` 表示该尝试没有效果且不会有迟到效果，不表示当前远端不存在那些点。
- `attempts` 保留原始状态和 operation ID，`reconciliations` 保存独立决定；`effective_outcome(attempt_id)` 返回派生结果。not-applied 解除该尝试的不确定性，但不创造完成覆盖；此前其他已完成尝试的覆盖可以恢复。
- 同清单内对账 ID 唯一，每次尝试最多一条决定；完全相同的决定可重复提交，改变结果、证据、操作者或 ID 都不能覆盖。事务内匹配预期原始状态与计划，冲突时不落盘；这不是证据真实性认证。错误决定的修订流程尚未提供。
- 引用是非空、无 ASCII 控制字符、最多 128 UTF-8 字节的宿主标签。默认 repr 隐藏证据/操作者引用，但序列化 JSON 和数据库会明文保存；不要存凭据或证据正文。引用可指向宿主保管的证据，不保证可解析、持久或可信。
- 无对账记录的日志保持规范 v1 JSON；首次显式对账写入含决定的 v2 JSON，SQLite 表结构、application ID、user_version 均不变。只读 inspect 不改写旧日志；旧版仅支持 v1 的读取器不能读取 v2，不能盲目降级。每清单最多 1024 条决定，仍受原 payload 限额约束。
- 取消或本地返回失败不证明决定未提交：先 inspect，必要时重交完全相同的决定，不重发远端写入。即使所有点已确认，也仍需另做真实检索验收。

## 写入失败与下一步

远端失败/取消时，组合函数尽力记录 unknown；Writer 明确尚未发送时记录 not-sent。若这次本地记录也失败，原 pending 仍是保守状态，函数保留原远端异常，不谎称记录成功。远端返回回执后若本地保存失败，会报固定 `knowledge-index-receipt-persistence-failed`，不能据此重发远端；先 inspect 并结合宿主保留的独立证据核对。第二次取消也可能发生在本地保存期间，仍应重新读取。

日志没有保存 Embedding 用量或向量数值，不代替准备费用账本、索引版本文件或原文快照。宿主仍负责预算、资源生命周期、保存所需证据，以及发布可查询版本前的真实检索验收。

## 本轮进度与剩余

本地日志/对账回归已通过，未调用真实远端。`list_journals()` 与 `knowledge-index-list --database <日志库> --confirm-read` 提供校验后的独立回执目录，TUI 增加 List journal manifests。可选 `CoordinatedKnowledgeIndexJournal.begin_exclusive()` 在同库事务内拒绝同目标跨清单的未确定重叠点；[构建执行及显式重试](./knowledge-builds.md)使用该能力，原 `begin()` 保持低层兼容语义，不提供此协调。不同库、URL 别名和绕过此接口的 writer 仍由宿主协调。远端证据采集、错误决定修订、历史清理、索引差异同步、统一费用账本及真实服务验收仍待实现/核验。见[准备恢复](./knowledge-build-recovery.md)与[路线图](./roadmap.md)。
