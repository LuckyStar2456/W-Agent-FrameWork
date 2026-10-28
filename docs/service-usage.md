# 跨服务用量观测

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

简体中文 | [English](./service-usage.en.md)

状态：当前2.0.0 `Experimental`。这是可选计量视图，**不是第二个预算控制器，也不保证等于最终账单**。准入、预留、结算、未知占款与对账仍由现有 `SharedBudgetController` 负责；现有会话摘要账本和共享预算格式不变。

## 边界与数据

`ServiceUsageRecord` 绑定宿主定义的 `operation_id`、唯一 `record_id`、服务类型（`model`、`embedding`、`retrieval`、`rerank`）、不透明 `source_ref` 和 `meter_version`。宿主只提供标签，不得填入查询、端点 URL、凭据、文档正文或结果内容。账本只保留标签、状态、计数、Token、成本和可选对账引用；标签不是权限或来源证明。

- 潜在计费调用进入前先写入 `started`，崩溃后仍标为未决。
- `completed` 只表示调用/报告完成，不保证用量或价格完整。缺失值保持 `None`，已知部分累计保留不完整标记。
- `unknown` 不等于零；`not-incurred` 表示没有计入的消耗，通常来自已有预算的 released 预留。
- 默认 `token_scope="expected"`；宿主可对非 Token 服务明确选择 `"not-applicable"`，仅排除 Token 维度，不会把未知费用变成零。不会自动把本地 BM25 标价为免费。
- 非 Token 单位由 `ServiceUsageUnit(name, count)` 和明确计量版本表达，按服务/来源/计量版本/单位隔离汇总。费用按币种和价格表版本隔离，不自动换汇。
- 成本复用 `ModelCost`；按请求收费的检索可由宿主明确规定成本分量的使用方式。没有内置实时价格或自动猜价。成本分量限制为 28 位精度、指数 ±28，汇总使用有界高精度 Decimal 上下文。

相同报告幂等，身份变化与冲突终态拒绝。`started` 可推进到终态；将 `unknown` 改为已知必须提供明确 `reconciliation_ref`，来源应是宿主审核证据，而不是猜测重试结果。当前状态账本不等于不可变审计历史。

## 复用已有预算

```python
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger
from w_agent.service_usage_adapters import ObservedSharedBudgetController
from w_agent.shared_budget_provider import SharedBudgetModelProvider
from w_agent.embedding_budget import SharedBudgetTextEmbedder

ledger = SQLiteServiceUsageLedger(".wagent/service-usage.sqlite")
await ledger.initialize(confirm_create=True)  # 父目录必须已存在
model_observer = ObservedSharedBudgetController(
    shared_budget, ledger, operation_id="run-chain-42", service="model",
    source_ref="model-route-a", meter_version="pricing-2026-10",
)
embedding_observer = ObservedSharedBudgetController(
    shared_budget, ledger, operation_id="run-chain-42", service="embedding",
    source_ref="embedding-a", meter_version="pricing-2026-10",
)
model = SharedBudgetModelProvider(model_provider, model_observer, model_meter)
embedder = SharedBudgetTextEmbedder(embedding_provider, embedding_observer, embedding_meter)
```

上例的 `shared_budget`、Provider、可信计量器均由宿主提供，沿用现有组件。两个观测器共享**同一个底层预算**，以预留 ID 作为观测身份；预留值绝不计为实际消耗。观测器不拥有也不关闭 Provider 客户端。

初始观测写入失败时不进入 Provider，并尝试释放预留。底层预算结算成功而观测失败时，装饰器会在写账本**之前**保留已结算真值；清理流程之后的 `settle(None)` 只能重新写入原始真值，不能降级为 unknown，也不能再次结算底层预算。观测失败是不可自动重试的计量错误。取消/崩溃后必须检查两个存储，它们不是跨库原子事务；待确认观测绝不授权重做付费调用。

恢复时可读取底层预算的权威快照，通过 `service_usage_from_budget_entry(...)` 显式投影对应条目，保持原操作/服务/来源/计量版本绑定。预算已有对账决定时，其对账 ID 会进入观测。这只记录证据，不调用服务，也不替代预算对账。

## 检索与重排

`ObservedKnowledgeRetriever` 和 `ObservedKnowledgeReranker` 实现现有 retrieve/rerank 方法。提供底层组件、账本、操作/来源/版本标签、可选 `measurement(result) -> ServiceUsageMeasurement` 和明确的 Token 适用性。回调可提供真实供应商报告、单位计数或宿主已知价格；它是可信代码，不应暗中发起付费调用。没有回调时，用量和成本保持未知。查询与返回文档不会进入报告。

`observe_service_call()` 为其他显式集成提供相同的“先开始记录、后调用、再终态观测”路径。它不做预算预留、不编造价格、不重试调用、不保存输入输出正文。适用时可将已有预算组件放在被观测服务内部，但不能在另一个边界重复记录同一笔消耗。

## 汇总与避免重复计数

```python
from w_agent.service_usage import aggregate_service_usage

summary = aggregate_service_usage(await ledger.records("run-chain-42"))
```

汇总包含已知 Token、成本分组、隔离单位累计、不完整条目 ID 与未决 ID。空账本不会宣称完整；完整性仅针对**提供的报告集**，不包含未接入调用，也不等于整个应用已完整计量。

同一操作应选择模型 attempt 观测**或** `service_usage_from_run(..., confirm_final=True)`，不能两者同时记；同一服务混用 run/attempt 会被拒绝。Run 导入拒绝 `NEEDS_APPROVAL`，且要求宿主明确确认结果不会再恢复执行；它是最终累计值，不是增量，相同重送幂等，变化的终态累计拒绝。活跃/可恢复 Run 请采用 attempt 级观测。不要同时记录复合服务账单与其付费子服务账单，系统无法自动识别任意宿主边界的重叠。

`ServiceUsageLedger` 可替换；`InMemoryServiceUsageLedger` 仅在进程内；`SQLiteServiceUsageLedger` 需显式初始化，拒绝外来数据库和容量不匹配，在事务中串行更新/检查容量，拒绝并发冲突终态。SQLite 保存明文观测，不是加密/认证账单。取消会等待已开始的 SQLite 工作结束，可能已提交；不会自动迁移、清理或创建父目录。

只读 CLI：

```text
wagent service-usage --database .wagent/service-usage.sqlite --operation run-chain-42 --confirm-read
```

若初始化容量不是默认 10000，请使用匹配的 `--max-records`。命令不初始化数据库、不执行插件代码、不调用远端服务。

## 证据与剩余

本轮新增 21 项 service-usage 测试及相邻共享预算、Embedding 预算、会话计量测试合计在隔离 Python 3.11 中 **85 passed**。根代理另有四服务共用真实 SQLite 预算/观测、重开汇总的集成测试，合并计数以当前验收报告为准。这是相关验收证据，不等于供应商账单验收或全量通过。

后续已接 [Runtime/CLI/TUI 观察](./service-usage-runtime.md)与[可选持久关联和只读查询](./service-usage-links.md)。`service-usage --run R --links-database ...` 解析关联后仍汇总整个 operation，不冒称每个 Run 独占用量。剩余：每笔服务/准备观察的 Run 归属、完整自动覆盖、供应商检索/Rerank 账单映射、不可变审计历史、更正流程与远端发票核对。没有自动全局服务预算、在线价格抓取或多租户平台。
