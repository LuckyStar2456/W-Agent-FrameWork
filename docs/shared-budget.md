# 跨摘要与主 Agent 的共享调用预算

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./shared-budget.en.md) | 简体中文

状态：`2.0.0a9 Experimental`。针对性验证与限制见 [a9 发布说明](./releases/2.0.0a9.md)；未调用真实付费模型，不构成厂商最终账单或跨平台保证。

## 作用与装配

`SharedBudgetController` 是可替换的预留/结算协议；`InMemorySharedBudget` 为单事件循环内存模板，`SQLiteSharedBudget` 为显式初始化的本地持久化模板。`SharedBudgetModelProvider` 包装任意标准流 Provider，在进入它的每次调用前预留额度。摘要 Loop 与主 Agent 使用同一预算的包装器，就可共享输入/输出/总 Token 和可选金额额度，而不要求替换 Agent 模板。

```python
from w_agent import (
    InMemorySharedBudget, SharedBudgetLimits, SharedBudgetAmount,
    SharedBudgetModelProvider, ModelRegistry, TokenUsage,
)

ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20000))

class HostMeter:
    async def bound(self, request):
        # 宿主函数：须覆盖已路由请求的全部计费输入，不只是正文字符数。
        upper = await application_input_upper_bound(request)
        return SharedBudgetAmount(TokenUsage(upper, request.max_output_tokens))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)  # 不改写 Provider 实报 Token。

models = ModelRegistry()
models.register("provider", SharedBudgetModelProvider(provider, ledger, HostMeter()))
# 用 models 装配摘要和主 Agent 的 ModelExecutor；所有备用路由也必须包装。
# Provider 客户端与 application_input_upper_bound 由宿主实现、授权并管理生命周期。
view = await ledger.snapshot()
```

这不是开箱即用的厂商 Token 计算器。`SharedBudgetMeter.bound(request)` 与 `actual(request, usage)` 都由宿主显式提供；请求必须有严格正整数输出上限，预留的输出不得小于该上限。不要在 Meter 内递归调用付费模型。输入上界必须覆盖系统提示、工具、媒体、协议开销、隐藏推理等对应厂商计费项；近似字符估算不自动构成可靠上界。若某 Provider 无法给出可靠边界，就不能声称实现了绝对费用上限。

费用控制使用 `SharedBudgetLimits(max_cost="1.00", currency="USD", price_table_version="rates-v1")`，可与 Token 限额组合。此时每个 bound/actual 都必须携带同币种、同价格版本的 `ModelCost`；宿主可接入已有 `PricingResolver`。只有 Token 限额时，cost 必须为 `None`，金额不暗示为零。实际费率由宿主保证，跨币种/跨价格版本不自动换算。

## 预留与结算规则

- 入场条件为“已知实耗 + 在途/未知预留 + 本次上界”不超过任一配置限额；等于上限可入场，额度不足直接拒绝，不排队、不缩小请求、不自动重试。
- 内存模板用异步锁在同一临界区检查和插入预留，避免并发调用各自通过独立检查后合计超额。默认保留最多 10000 个票据，允许 1–100000；终态票据也占容量以保证去重，未提供自动淘汰。
- 成功且完整的流，必须有 Usage；Meter 不得修改实报 Token。包装器在 EOF、协议校验、源流关闭与结算完成后才传出 `FinishEvent`；正文仍按流输出，不能撤回已经展示的内容。
- 成功结算以实际消耗替换预留；重复同一结算幂等，冲突结算拒绝。超过任一预留分量时保留实际消耗、锁定超额状态并拒绝正常完成，后续新调用被阻止。不是事后截断或抹掉已经发生的费用。
- 失败、缺少 Usage、取消、提前关闭或计价失败会尝试标记 unknown，保留整笔预留并阻止新调用。即使失败可能没有收费，也不在缺少证据时退款。其他已经入场的调用不会被强行取消，仍须结算。
- 只有确认尚未进入 Provider 的预留才能 `release()`；包装器只在进入 Provider 前取消时走该路径。宿主直接调用 release 是受信操作，不是模型可获得的授权。
- Provider 错误会转换为不含原始正文、不可重试的共享预算错误。内置 ModelExecutor 尊重此标记，不会自动重放未知计费调用；自定义策略/旁路代码仍须由宿主管理。

`snapshot()` 给出不可变 entries、`known_usage`、`held_usage`、可选 `known_cost`/`held_cost`、limits 和 breached。cached input 是输入的子集，不再加进总 Token。`blocked` 表示已有 unknown 或上界破坏，并不表示有足够余额：没有 blocked 也可能因额度/票据容量不足而拒绝新调用。账本只含随机票据、计数、费用及可选对账索引，不保存 Prompt、回复、请求对象或 Provider 密钥；宿主也不得把敏感正文或密钥填入索引。

## SQLite 持久化与重开

以下替换上例的 ledger；须在宿主异步入口执行，父目录必须已存在：

```python
from w_agent import SQLiteSharedBudget, SharedBudgetLimits

limits = SharedBudgetLimits(max_total_tokens=20000)
ledger = SQLiteSharedBudget("./shared-budget.db", "development-v1", limits)
await ledger.initialize()
# 把 ledger 传给同一组 SharedBudgetModelProvider。
# 另一个宿主进程可使用同一文件与 budget_id、相同限额/容量进行装配。
reopened = SQLiteSharedBudget("./shared-budget.db", "development-v1", limits)
view = await reopened.snapshot()
```

- 构造不读写数据库。`initialize()` 显式创建专用数据库并绑定预算配置；其余方法不创建缺失文件或预算。不同 `budget_id` 是独立本地账本，不是租户、身份鉴别或权限隔离；新建 ID 也不会继承旧 ID 的消费。
- 入场、结算、释放均在工作线程的 `BEGIN IMMEDIATE` 事务内读取、检查并写入；同一文件的实例/进程通过 SQLite 文件锁协调。事务不覆盖模型执行，不是任务租约或跨 Store 原子事务。不支持绕过账本的调用限额，也未完成真实跨进程环境验收。
- 重开必须使用相同限额、币种、价格版本和票据容量；金额配置的十进制字符串表示也需一致。锁等待 `timeout` 默认 1 秒，允许大于 0 且不超过 60 秒，不影响预算身份。预算配置和票据版本被校验，不隐式迁移、不降低限额、不内存降级。不要复用 SQLite 摘要报告观察器的数据库文件。
- pending/unknown 预留、settled 实耗、released 去重票据都会保留。读取时从票据重算合计与超额状态；未知或超额不会因重启清除。unknown 不能通过普通 settle/release 修正，须使用下面的显式对账接口；不提供“清空后重试”。
- 每个票据 JSON 最多 16 KiB，每个预算票据 JSON 合计最多 32 MiB；默认最多 10000 个票据，可设 1–100000，终态也计入。每次操作读取整个有界预算，适用于本地开发模板，不是高吞吐账单系统。边界只约束载入/保存的票据与配置，不限制整个数据库磁盘体积、数据库数量或查询扫描开销；不提供清理/轮换。
- 数据类型、未知字段、重复 JSON 键、价格身份、票据 ID、文件标识和版本异常均拒绝，不把损坏/缺失数据当作零。仅面向受信本地文件及正常工作的 SQLite 文件锁；不是防篡改账本，不保证网络文件系统或恶意数据库安全。
- 取消只停止等待线程，已开始的事务仍可能提交；reserve 的调用方甚至可能没有拿到已提交的票据 ID。须重新读取 snapshot 检查 pending，不自动退款、过期或重跑模型。存储失败时不报告结算成功，旧预留可能仍存在；固定、无正文、不可重试的错误不能证明事务没有提交。

持久化存储与内存模板共用入场/结算状态转换。a9 定向回归覆盖重开、并发实例、价格/配置绑定、未知状态、损坏数据、取消与 Provider 装配；不构成跨进程崩溃或跨平台行为验收。

## 显式对账：开发者确认，不自动修复

`SharedBudgetReconciler` 是独立可选协议，普通 `SharedBudgetController` 不增加必需方法，Provider 包装器也不会调用对账接口。内存与 SQLite 模板均提供：

```python
from w_agent import SharedBudgetReconciliation, SharedBudgetAmount, TokenUsage

# 宿主先停止并等待目标调用及所有写入者结束，再按独立证据确认票据归属和实耗。
# confirmed_ticket_id 来自宿主核对，不以“第一条未知票据”猜测归属。
entry = next(item for item in (await ledger.snapshot()).entries
             if item.reservation.reservation_id == confirmed_ticket_id)
decision = SharedBudgetReconciliation(
    reconciliation_id="fix-001", reservation=entry.reservation,
    expected_status=entry.status, outcome="settled",
    evidence_ref="billing-record-001", actor_ref="local-developer",
    actual=SharedBudgetAmount(TokenUsage(120, 30)),  # 示例；必须替换为证据确认的实耗。
)
updated = await ledger.reconcile(decision, confirm_inactive=True)
assert updated.reconciliation == decision
```

- `confirm_inactive=True` 必须显式传入，整数 1、字符串等不能替代。它是宿主对目标票据没有活跃执行/后续写入者的断言，不是框架检查出的租约，也不保证远端调用已结束。存在其他活跃进程时须由宿主协调停止，不能凭超时或“暂时没有新输出”确认。
- 决定仅接受 `expected_status="pending"` 或 `"unknown"`，且提交时状态、票据 ID 和预留金额须与当前账本匹配。若普通结算先完成，对账拒绝；若对账先完成，迟到的普通结算拒绝，不覆盖对账记录。
- `outcome="settled"` 要求明确实耗；金额预算还要求币种/价格版本一致。`outcome="not-incurred"` 配合 `actual=None` 表示证据确认既没有应计 Token、也没有费用，并将票据置为 released。**免费调用但有 Token 消耗**仍应 settled，费用可为零；不能用“未收费”抹掉 Token。
- `reconciliation_id` 在同一预算内唯一；`evidence_ref`、`actor_ref` 与 ID 均为 1–128 字符的 `[A-Za-z0-9][A-Za-z0-9_.:-]*` 不透明索引。它们不是正文、URL、文件路径、身份认证或权限授予。框架不会联网查询证据，也不验证证据真实性；证据内容、操作人身份和票据关联由宿主管理。
- 一张票据最多接受一个最终决定，保留原预留、前置状态、结果、实耗与证据/操作人索引。完全相同的决定重复提交幂等；相同 ID 的不同内容、跨票据重复 ID、不同决定覆盖已有决定均拒绝。已确认的普通 settled/released 也不支持改写。这里是每票据的不可覆盖回执，不是全量时间序列审计日志或防篡改凭证。
- 对账在内存锁/SQLite 单一写事务中同时保存回执和结果；失败不会仅退款而丢掉回执。SQLite 在同一事务中检查重复 ID，重开时也检查；对账回执计入原票据 16 KiB/账本 32 MiB 上限及票据数量上限，无自动淘汰。
- 实耗超过预留仍完整记录并锁定 breached；本接口不清除既有超额状态、不提高预算。处理一笔 unknown 也不会解锁其他 unknown；即便所有 unknown 已处理，额度不足仍可拒绝入场。
- SQLite 数据库表/配置保持版本 1；无回执票据继续读写版本 1，对账票据写为严格版本 2，读者同时支持两种形状。初始化不批量迁移或改写旧票据；旧实现不能读取版本 2，不能混跑旧版写入者。a9 为这些格式的首个发布版本，a8 不提供此模块。
- 取消或存储错误可能发生在事务提交之后：重开查看 `entry.reconciliation`，或在再次确认无活跃写入者后重复提交同一决定，不能重新生成一个 ID 来试图覆盖。对账不重跑模型，不修改原 Run/Session 的历史 Usage 或摘要报告。

a9 对账定向回归覆盖两个后端、竞争/幂等、重开、取消、损坏回执与容量回滚；CLI/TUI 不提供对账按钮，也不会把该能力作为模型工具暴露。

## 扩展与未完成部分

工作区已新增[跨服务观测账本](./service-usage.md)：显式装饰当前 controller，记录模型/Embedding 实耗，另有检索/重排观测器及只读 CLI。它不改变预算格式、不自动合并 Run/Session 统计、不额外准入，也不表示完整自动接线已完成。

另有已随 2.0.0 发布，本地回归通过的 [Embedding 预算包装器](./embeddings.md)：`SharedBudgetTextEmbedder` 通过独立 `EmbeddingBudgetMeter` 让单文本嵌入显式使用同一 controller，保留预留/已知/未知语义。该增量不属于 a9；不自动初始化数据库、装配 Embedding 配置或归入主 Run/Session 统计。

用户可替换 controller、meter、Provider 和 Agent Loop。包装器不自动关闭宿主 Provider 客户端；只关闭本次源流。Provider 内部自行重试必须被其上界和实耗完整覆盖，否则共享账本也无法看到隐藏调用。list/resolve 不计量，因此不得把付费生成隐藏在这些方法中。

本模板不转发 `stream_with_cursor` / `resume_stream`，内置原生游标恢复会拒绝不支持的包装器，不绕过计量；游标请求需后续独立计量适配。所有摘要/主模型/备用路由必须经过包装器，未包装调用、外部检索、嵌入和工具费用不会自动纳入。

取消是协作式的，不能撤销网络侧调用；重复取消可能打断清理并留下 pending，仍占预留。controller 的 reserve/settle 异常可能发生在状态已提交后，宿主必须按账本对账，不能据此盲目重跑模型。内存账本退出即丢失、不具备跨进程协调或崩溃恢复；SQLite 模板可持久化。两者都不具备任务自动关联或计费真实性证明，也不与 SQLite 摘要报告观察器自动同步；显式对账不是跨账本自动校正。

a9 提供 [Runtime 具名绑定](./local-runtime.md)：配置的 `shared_budget.binding` 选择宿主提供的 `LocalSharedBudgetBinding(controller, meter)`，Runtime/Provider 装配器自动包装所选 Provider 并保留原客户端关闭职责；共享 SQLite 不自动初始化。Runtime 通过 `shared_budget_snapshot()` 显式读取池总量，未选择时返回 None；历史 Run/Session 统计不变。此增量同属 a9 Experimental，验证范围见 a9 发布说明。

CLI run/run-resume/evaluate/provider-probe 与 TUI 运行/审批恢复/评测/探测现支持独立授权的宿主预算工厂及池级摘要，见 [Runtime 工厂接入](./local-runtime.md)。框架不自行发现/导入预算代码，不提供对账按钮；该增量属 a9 Experimental，验证范围见 a9 发布说明。

后续仍需准备阶段/主 Run 统一账本、原生游标计量、持久化/跨进程验收、真实上界和厂商行为验收。参见[用量归集](./context-accounting.md)及[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
