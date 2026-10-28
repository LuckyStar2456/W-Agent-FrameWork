# 上下文准备与主 Run 用量归集

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./context-accounting.en.md) | 简体中文

状态：`2.0.0a9 Experimental`，针对性回归通过。验证范围见 [a9 发布说明](./releases/2.0.0a9.md)；不代表已完成真实模型或费用验收。

a9 另新增 `SQLiteSessionSummaryObserver`（2.0.0a9 Experimental，验证范围见 a9 发布说明），用法见下节。本次验证范围见 a9 发布说明。

## SQLite 摘要报告持久化（a9 增量）

沿用 `SessionSummaryObserver.record()`，可替换内存观察器，不要求模型、Agent Loop 或摘要策略改变。仅保存摘要 Run 的无正文报告；不保存主 Run 结果、Prompt、摘要文本、异常正文或 Provider 凭据。

```python
from w_agent import SQLiteSessionSummaryObserver, AgentSessionHistorySummarizer

# 父目录须已存在；宿主明确授权本地文件写入，不自动创建目录。
accounting = SQLiteSessionSummaryObserver(
    "summary-usage.sqlite3", "support-refund-20260928", max_runs=128,
)
await accounting.initialize()
summarizer = AgentSessionHistorySummarizer(summary_loop, accounting)
# summary_loop 为宿主装配并授权的专用空工具目录 Loop。
# 将 summarizer 注入 AsyncSummarizedSessionHistoryPolicy 后运行主 Agent。
usage = await accounting.snapshot(run.result)

# 进程重开后使用同一文件、任务标识和容量设置即可读取。
reopened = SQLiteSessionSummaryObserver(
    "summary-usage.sqlite3", "support-refund-20260928", max_runs=128,
)
reports = await reopened.reports()
```

`operation_id` 是宿主给一次本地开发任务选择的关联键，不是租户、权限域、Session 自动关联或模型执行锁。只接受以字母/数字开头、最多 128 字符的 ASCII 字母/数字/`_.:-`。不要放入秘密；Run ID、任务标识和价格版本仍属于本地数据。不同任务可使用同一数据库，但不能据此认为存在访问隔离。

- 构造不访问数据库；`initialize()` 显式创建/打开专用文件并登记任务。父目录必须存在。未知数据库身份/版本拒绝使用，不自动迁移或覆盖已有业务表；初始化失败仍可能留下空文件。
- 配置不可变。每个任务的 `max_runs`（默认 1024，1–10000）与 `max_report_bytes`（默认 16384，512–65536）写入数据库，重开须一致。不同客户端不能通过更改本地上限绕过已有容量。
- `record()` 在同一 SQLite 写事务内检查已有报告、冲突和容量，再写入。相同报告幂等，started 可更新为终态；已有 Run 可在满容量时完成；终态冲突拒绝，未知终态也不自动修正。首次收到终态可存储，但这不能证明模型实际执行过。
- `reports()` 使用只读连接和读事务，按首次登记顺序返回最新报告。不存在的文件或未登记任务报错，不自动创建或当作空账本。限制返回条数与每条载荷，拒绝超限、重复 JSON 键、错误版本、身份/总量/完整性标记不一致；不静默跳过损坏记录。
- 数据库操作在工作线程执行，每次独立连接并关闭；写事务可协调同一本地文件的多个实例/进程，但不是 Agent 执行租约。锁等待默认 1 秒，可配置 `(0, 60]`；锁失败不重试、不回退内存、不触发模型重跑。
- 取消会停止异步等待，但已开始的线程/事务可能继续提交；调用返回异常不证明没有写入。重开读取报告对账，不盲目重跑模型。失败的报告写入与模型执行不是原子事务：崩溃可能只留下 started，费用仍未知。
- `snapshot(main_result)` 复用现有归集规则。主结果不写入数据库，重开后需宿主重新提供对应累计结果；缺少主结果仍返回不完整的已知摘要小计。

只使用宿主管理的可信本地 SQLite 文件；数据库身份与 JSON 校验不是签名，不防范有文件写权限的其他进程。没有自动清理、保留期限、导入陌生账本或跨文件事务。单任务记录限制不限制任务总数、SQLite 内部扫描、日志文件或整个数据库大小；宿主负责备份、目录权限和磁盘容量。a9 定向回归范围见发布说明，不构成跨进程崩溃或真实故障恢复验收。

## 装配与使用

`InMemorySessionSummaryObserver` 实现 `SessionSummaryObserver`，可直接注入 [AgentSessionHistorySummarizer](./sessions.md)。宿主为一次需要关联的开发任务创建一个观察器，再用 `snapshot(main_result)` 合并该任务的摘要报告与一个主 Run 累计结果。整个过程不读取原始 Session、日志或模型正文，也不自动修改 `RunResult`、Session 汇总或既有计费记录。

```python
from w_agent import (
    AgentSessionHistorySummarizer, AsyncSummarizedSessionHistoryPolicy,
    InMemorySessionSummaryObserver,
)

# summary_loop 须由宿主授权、装配预算/模型并使用空工具目录，见 Session 文档。
accounting = InMemorySessionSummaryObserver(max_runs=128)
summarizer = AgentSessionHistorySummarizer(summary_loop, accounting)
policy = AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=2)

# 实际模型调用须先得到应用层授权。
run = await runtime.run(prompt, session_id=session_id, history_policy=policy)
usage = await accounting.snapshot(run.result)
report = usage.to_dict()
print(report["known_usage"], report["usage_complete"], report["cost_totals"])
```

如果主调用失败、取消或没有返回 `RunResult`，可读取 `await accounting.snapshot()`，得到已知摘要消耗，但 `main_result_supplied=False`，整体 `usage_complete` / `cost_complete` 均为 False。这不意味着主调用免费或未发生，只表示主调用消耗未纳入本次报告。

审批恢复后，显式传入最新的累计主结果：`await accounting.snapshot(resumed.result)`。观察器不保存主结果，更不会把恢复前后的累计 Token 相加。每次只传一个主结果；跨多个主 Run 的应用汇总由宿主另行组织。

## 字段与完整性

- `known_usage`：当前报告集合中已知的输入、输出、缓存输入 Token 合计。`total_tokens` 只加输入与输出，不重复累加缓存子集。
- `known_model_calls`、`known_reported_usage_calls`、`known_priced_usage_calls`：已知调用计数；完全未知的调用不虚构为零次，需结合不完整 Run 列表阅读。
- `pending_summary_run_ids`：只有 started、尚无终态的摘要 Run。
- `incomplete_usage_run_ids` / `incomplete_cost_run_ids`：已有记录但用量/价格不完整的摘要或主 Run。缺少整个主结果另由 `main_result_supplied` 表示。
- `cost_totals`：按 `(currency, price_table_version)` 分组的已知金额。不同币种、不同价格版本不换算、不强行相加；可全部计量完整而仍有多个金额分组。
- `main_stop_reason`：主结果终止原因。Usage 完整不代表任务成功或执行结束；例如 NEEDS_APPROVAL 的当前累计用量可以完整，但恢复后仍可能增加。

返回 `SessionPreparationUsage` 为不可变快照，`to_dict()` 返回独立 JSON 兼容数据。未完成、取消、失败或缺少 Usage 的摘要不抹掉其他已知消耗，也不会被解释为零费用。观察器报告本身的 completed/rejected 状态不决定是否计入：拒绝采用的摘要同样可能产生真实费用。

## 去重、容量与替换

观察器默认最多保留 1,024 个摘要 Run，使用进程内异步锁串行更新。相同报告重复投递不重复计量，started 可更新为终态；不同的终态、终态后重新 started 都会报冲突并保留原记录。达到容量后不接收新的 Run，但已有 Run 仍可完成。作为摘要器观察器时，开始报告被拒绝会阻止该次模型调用。这里的容量是内存记录数量限制，不是共享 Token/金额预算。

`reports()` 返回每个 Run 的最新不可变报告。宿主可使用纯函数 `aggregate_session_preparation_usage(reports, main_result)` 装配自有观察器；要求 tuple、唯一 Run ID，主 Run ID 不得与摘要冲突。主结果中只有严格校验后的身份、状态、计数和费用被读取，不保留其输入、输出、事件或尝试正文。

终态已记录为未知后，内置观察器不会静默覆盖修正。宿主应按独立 Run Store/Provider 证据对账，并明确重建新的报告集合或替换观察器；不能盲目重试模型调用来“修复”计量。

## 边界与剩余工作

a9 新增独立的[共享调用预算](./shared-budget.md)协议、内存/SQLite 控制器和 Provider 包装器，可显式装配摘要/主模型的调用前预留，并提供基于宿主证据确认的 pending/unknown 对账；2.0.0a9 Experimental，验证范围见 a9 发布说明。它不由此处的观察器自动启用；SQLite 预算使用独立数据库，对账不会改写本观察器的报告或主 Run 结果。

观察器必须由宿主正确关联。框架无法证明传入的报告属于同一任务、报告集合没有遗漏，或费用等于厂商最终账单。不要把多个并发任务共用的观察器误当作单次请求账本；不自动推断主 Session 关系。a8 的默认观察器只保存在内存，进程退出会丢失；a9 SQLite 摘要报告持久化见上文，验证范围见 a9 发布说明，尚未提供厂商账单对账后端。

此模块只归集，不在模型调用前预留 Token/金额，不阻止其他未接入它的调用，不提供跨进程执行锁或共享硬预算。单个摘要和主 Run 仍使用各自的 `TokenBudget` / `CostBudget`；主 Run/准备阶段统一持久账本、Runtime/CLI/TUI 自动归集与展示仍待后续实现。自定义检索、嵌入或其他准备调用只有经宿主规范化为对应报告并纳入集合后才会计入，不自动监控第三方网络调用。
