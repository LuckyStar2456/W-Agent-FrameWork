# 显式历史向量准备与 Qdrant 写入

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./vector-indexing.en.md) | 简体中文

2.0.0 Experimental：本地回归通过，已随 2.0.0 发布，不属于 2.0.0a9；真实服务、费用、质量及人工生产界面仍待验收。

## 两个独立的副作用阶段

[历史检索](./vector-retrieval.md)仍只读，不会触发索引。本模块提供可独立替换的准备函数、不可变数据和写入服务；不要求替换 Agent Loop，不授予模型工具权限，不自动发现或导入宿主代码。

1. `prepare_qdrant_history_points(namespace, turns, embedder, confirm_embedding=True)`：先校验整批历史、重复 ID、文本大小，再顺序调用宿主 Embedder。这个确认允许把选定历史正文交给 Embedder，独立于检索时发送查询词的授权。
2. `QdrantVectorWriter.plan(points)`：纯本地准备，生成不可变 `QdrantUpsertPlan`，不调用模型或访问网络。宿主审核具体目的地、point ID、向量内容和覆盖风险后，以 `upsert(plan, confirm_digest=reviewed_digest)` 单次发送。

根据 [Qdrant Upsert API](https://api.qdrant.tech/api-reference/points/upsert-points)，该请求会覆盖同 ID 的已有点。模板采用 `PUT /collections/{collection}/points?wait=true`，发送 ID、默认或具名向量及空 payload。它不是仅新增操作，也不保证保留旧 payload 或其他向量。请使用宿主管理的专用 collection，并在确认前审查冲突；不自动读取远端判断是否存在。

## 装配示例

```python
from w_agent import (
    MessageRole, ModelMessage, SessionHistoryTurn,
    QdrantVectorSearch, QdrantVectorWriter, prepare_qdrant_history_points,
)
from my_application import authorized_embedder, review_index_overwrite

# 宿主选择与历史策略一致的连续 Run 文本段，不把整个 Session 交给未知代码。
turns = (SessionHistoryTurn("run-1", (
    ModelMessage.text(MessageRole.USER, "退款规则是什么？"),
    ModelMessage.text(MessageRole.ASSISTANT, "已确认的规则摘要……"),
)),)
points = await prepare_qdrant_history_points(
    "support-session-v1", turns, authorized_embedder, confirm_embedding=True,
)
backend = QdrantVectorSearch(
    "http://127.0.0.1:6333", "support_history", vector_name="dense",
)
writer = QdrantVectorWriter(backend)
plan = writer.plan(points)
# 此回调由宿主实现并获得真实批准，不能直接接受陌生计划自带的摘要。
reviewed_digest = await review_index_overwrite(plan)
receipt = await writer.upsert(plan, confirm_digest=reviewed_digest)
if not receipt.applied:
    # 远端仅 acknowledged；检查状态，不把它显示成已完成或自动重试。
    pass
```

collection 必须由宿主预先创建，维度/距离度量/具名向量须匹配所选 Embedding 模型。上例只展示接口，不会在导入或文档加载时执行。`backend` 可同时供 `QdrantSessionHistoryRetriever` 使用；索引与检索的 namespace/文本/Run ID 规则必须一致。

也可以自行生成 `DenseVectorPoint(point_id, vector)` 并交给其他存储或写入实现，或直接把 points 交给本模板规划。通用点 ID 支持有界字符串/uint64；Qdrant 计划额外要求 UUID/uint64。准备函数不依赖 Writer，Writer 不调用 Embedder。

## 文本、计划和结果契约

- `qdrant_history_embedding_text(turn)` 纯本地返回版本化 JSON 文本，包含有序角色/文本块，不包含 Run ID、name、metadata 或 Session 标题。输出本身含历史正文，必须按敏感数据处理；不是提示注入防护，也不会自行脱敏。
- ID 沿用 `qdrant_history_point_id(namespace, turn)`。名称/元数据不参与。修改文本或 namespace 会产生新 ID，旧点不会被删除；未变化的 ID 再次写入仍是一次显式覆盖，不提供“跳过已存在”或增量同步。
- 准备批次最多 128 段；全批实际发送给 Embedder 的 JSON/角色/文本 UTF-8 字节受 `SessionHistoryLimits.max_input_bytes` 限制。每次嵌入返回有限数值 tuple，所有点维度必须一致。空批次不调用 Embedder，但不能创建空 upsert 计划。
- 向量和计划均不可变，repr 隐藏向量/目标/点集；调用者直接读取字段、打印发送请求或记录 Embedder 参数仍会暴露敏感信息。向量不是匿名化数据，ID/摘要也不是秘密。
- 计划 digest 是绑定版本、PUT、精确端点、wait 参数、point ID/顺序、向量和空 payload 的 SHA-256。向量或目标改变须重新审核。API key 不纳入，因此轮换凭据不改变计划；使用哪个账户/权限仍由宿主审核。
- digest 不是签名、一次性令牌或隔离边界。`confirm_digest` 必须来自受信宿主真实审批，不能自动回填用户/模型/分享包提交的摘要。相同计划可再次显式执行，但不自动去重或重试；自定义 Python/transport 能绕过此类库级检查。
- Writer 复用 backend 的凭据、默认/具名向量、传输、超时和字节上限；拒绝其他目的地/向量名的计划，发送前再次校验正文大小。请求过大可能在 Embedding 已付费后被拒绝，应由宿主提前选择合理批次和维度。
- `QdrantWriteResult` 包含 `plan_digest`、`point_count`、`status`、可选 `operation_id`。只有 `completed` 的 `applied` 为 True；`acknowledged` 只表示已接收，不自动轮询或推断稍后成功。完成回执也不证明检索质量、账单真实性或永远不会被其他写入覆盖。
- `VectorIndexWriteError.may_have_written=False` 表示本模板未进入传输；True 表示已进入，结果不确定。HTTP 失败、错误/超限正文、无效回执、传输异常与超时不证明零写入，可能部分或全部已发生；检查远端后再决定。这里没有事务回滚、跨调用原子性或持久回执账本。
- Task 取消继续传播 `CancelledError`。若已开始 Embedding 或写入，无法撤销远端费用/写入；宿主须自行保留计划及执行阶段。准备中途失败不会返回部分批次，但此前 Embedding 可能已计费。只要调用者未另外运行 Writer，准备函数不会写入。
- 默认 timeout 为 30 秒：准备覆盖整批顺序 Embedding，写入覆盖单次请求。默认 HTTPX 按请求关闭资源，自定义传输和 Embedder 是借用对象、由宿主关闭；同步阻塞或忽略取消的扩展无法被强制终止。

## 计量与剩余模块

Embedding/检索/写入费用不自动合并到 Agent Run、Session 或共享预算池；付费回调需宿主显式计量，不能把未知费用记为零。接口也不验证第三方向量模型与检索配置一致。

授权隔离、限额、隐私、精确摘要、映射、未知状态、取消及准备→写入→检索 ID 的本地模拟传输回归通过。[正文上下文](./knowledge-context.md)、[快照向量](./knowledge-vectors.md)、带日志计划和构建 CLI/TUI 已显式组合此 Writer；[PDF/Office 与增量解析](./knowledge-import-extensions.md)也已独立实现。collection 创建、远端证据/查询、差异同步、更多 Embedding 模板、真实 Qdrant 验收及统一费用归集仍未完成。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
