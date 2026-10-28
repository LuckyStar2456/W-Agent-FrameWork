# 本地配置化 Agent Runtime

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./local-runtime.en.md) | 简体中文

未发布 M4 推荐使用 `async with open_local_runtime(config, ...) as runtime`；该入口将 `compile_local_runtime()` 生成的组件计划交给 `ApplicationHost`。CLI/TUI 已使用此路径，支持启动前替换 Loop、路由、执行器与存储；旧同步 `assemble_local_runtime()` 保留基本兼容，不自动变更其生命周期语义。见[默认装配](./default-assembly.md)。

工作区 [`knowledge_search_tool`](./knowledge-tools.md) 返回普通工具绑定，可经 `tools.enabled` 与宿主 `tool_bindings` 目录选择，并复用既有 CLI `--tool-entry` / `--confirm-tool-code` 与 TUI `LOAD TOOLS`。默认要求 `knowledge.read` 和外部调用审批，不由 JSON 自动导入或授予权限。源码及接线本地回归通过，不属于 a9；这不是专用检索配置页。

现提供[知识正文上下文策略](./knowledge-context.md)。直接传 `history_policy=AsyncKnowledgeContextPolicy(query, retriever)` 时，`include_history=False` 仍跳过整个策略。另有[知识具名装配](./knowledge-runtime.md)：JSON 的 `knowledge.binding` 选择宿主目录，Runtime 每次明确提供 knowledge_query 并确认，CLI/TUI run 独立确认工厂代码和查询。此显式入口支持禁用历史但查询知识；空 Session 同样可检索，检查点恢复不重查。仅文本上下文，本地回归通过，不属于 a9。

工作区已增加[只读 Qdrant 历史选择模板](./vector-retrieval.md)，可由 Python 宿主注入 `AsyncRetrievedSessionHistoryPolicy` 并传入 `history_policy`；不通过配置自动载入、不接入 CLI/TUI、索引与 Embedding/检索费用仍由宿主负责。已随 2.0.0 发布，本地回归通过，不属于 a9。

宿主现可另外使用[显式索引准备/写入](./vector-indexing.md)源码；Runtime 不自动调用这些副作用步骤，查询授权不代替历史正文嵌入或覆盖写入确认，同样已随 2.0.0 发布，本地回归通过。

a9 共享预算已接入 Runtime/Provider 的具名绑定装配：JSON 只选择宿主提供的 controller/meter 绑定，装配器自动包装当前 Provider；支持内存或显式初始化的 SQLite 控制器。CLI run/run-resume/evaluate/provider-probe 与 TUI 运行/审批恢复/评测/探测现可经独立确认加载预算工厂并展示池摘要，既有 Run 预算与 Session 统计不变；2.0.0a9 Experimental，验证范围见 a9 发布说明，详见下文与[共享预算](./shared-budget.md)。

a9 SQLite 摘要观察器可由 Python 宿主显式装配，不自动创建 Runtime 数据库或接入 CLI/TUI。其 `snapshot(run.result)` 重用显式归集接口；2.0.0a9 Experimental，验证范围见 a9 发布说明，见[持久化计量](./context-accounting.md)。

本页 a8/a9 增量为 Experimental；a9 验证范围见 [a9 发布说明](./releases/2.0.0a9.md)。

a8 增量（2.0.0a8 Experimental；针对性回归通过）：Python `run()` / `run_messages()` 的 `history_policy` 已接入 `AsyncSessionHistoryPolicy`。Runtime 在主 Agent Loop 前等待准备，支持取消；内置异步检索/摘要模板要求宿主显式提供受信回调。CLI/TUI 模板选择仍只使用本地同步策略，不自动接入外部服务。准备调用的 Token/费用不纳入主 Run 预算，须宿主独立授权和计量，见 [Session 异步准备](./sessions.md)。

`AgentSessionHistorySummarizer` 现提供独立摘要 Run 的适配器，复用已装配 Loop 的预算/计量，并通过必需观察器报告开始、终态和 Usage 完整性；同属 a8 Experimental 增量，针对性回归通过。为其装配专用空工具目录和所需 PricingResolver，不直接复用包含业务工具的 Runtime Loop；主 Session 汇总不会自动包含这些未绑定 Session 的摘要 Run。

a8 的 `InMemorySessionSummaryObserver.snapshot(run.result)` 可显式归集这些摘要报告和当前 Runtime 主结果，不修改原结果或 Session 统计；缺少主结果时返回部分已知消耗并标注不完整，详见[归集专题](./context-accounting.md)。尚未自动接线到 CLI/TUI，也不是统一调用前预算预留。

a7 新增（2.0.0a7，针对性回归通过）：`agent.emit_tool_results=true` 显式记录模型可见的工具结果正文，`agent.max_tool_result_event_bytes` 默认 65536，限制完整结果对象的 JSON UTF-8 字节数。默认关闭，审批票据不记录；编码失败只发出固定状态，不重试工具。Python 装配可传入 `tool_result_event_encoder`，JSON 配置不导入代码。恢复沿用检查点中的开关/上限，编码器由宿主重新注入；要保持自定义脱敏策略，重启后必须重新提供相同策略。下面的基本配置示例兼容 a6，两个新字段需要 a7 或更高版本，详见[事件记录与披露](./event-replay.md)。

状态：`Experimental`。`2.0.0a3` 已包含严格本地 JSON 配置、环境变量凭据引用、Provider/路由/ReAct 装配、版本化价格与费用预算、Provider 单独装配与探测、显式工具选择、持久化 Run/Session、Python API/CLI/TUI 审批恢复、Agent Checkpoint 脱敏列表、应用事件回调，以及 CLI/TUI 文本运行入口。`2.0.0a4` 另外实现显式调用前费用估算/重放包络，以及 Workflow Checkpoint 脱敏汇总和显式恢复。

## 共享预算具名绑定（2.0.0a9 Experimental）

配置中新增可选引用；不选择时保持原行为，不因宿主提供目录就自动启用：

```json
{
  "schema_version": 1,
  "provider": {"template": "ollama", "model": "your-local-model"},
  "agent": {"max_steps": 4, "max_tool_calls": 0, "max_output_tokens": 1024},
  "shared_budget": {"binding": "development"}
}
```

```python
from w_agent import (
    InMemorySharedBudget, SharedBudgetLimits, LocalSharedBudgetBinding,
    load_local_runtime_config, assemble_local_runtime,
)

ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=50000))
# host_meter 由宿主提供，实现 bound/actual；上界须适用于所选 Provider。
bindings = {"development": LocalSharedBudgetBinding(ledger, host_meter)}
config = load_local_runtime_config("runtime.json")  # 使用上面的配置。
async with assemble_local_runtime(config, shared_budget_bindings=bindings) as runtime:
    result = await runtime.run("开始任务")  # 仅在宿主明确授权模型访问之后调用。
    pool = await runtime.shared_budget_snapshot()
    # result.result.usage 是当前 Run；pool.known_usage/held_usage 是整个共享池。
```

边界与生命周期：

- `LocalSharedBudgetConfig(binding=...)` 只接受 1–128 字符不透明名称，JSON 不能写入路径、限额、代码导入、密钥或对账授权。`LocalSharedBudgetBinding(controller, meter)` 是宿主 Python 对象；两个对象的方法必须符合公开协议，不限定内存/SQLite 实现。
- `assemble_local_runtime()` 和 `assemble_local_provider()` 均接受 `shared_budget_bindings`。所选绑定缺失或类型不符会在构造 Provider 前失败，不回退到未计量 Provider；未选择时不访问目录内对象。选择共享预算必须显式配置严格正整数 `agent.max_output_tokens`，不借用字符估算器推断可靠上界。
- 绑定中的 controller/meter 完全由宿主管理。装配不调用它们的 initialize、snapshot、计量或关闭方法；SQLite 必须预先 `await ledger.initialize()`，运行时也不自动初始化或在存储异常时换成内存。多个 SQLite 对象要使用同一文件、budget_id 和相同配置；不同 ID 不共享额度。
- 装配器保存原 Provider 的所有权；Runtime 或 ProviderAssembly 关闭时会关闭自己创建的原客户端，不因预算包装器没有 `aclose()` 而遗漏。重复关闭幂等；不关闭借用的 controller/meter。Runtime 仍关闭注册表中可关闭的 Provider，并按对象身份去重。关闭不是等待正在执行的调用结束，宿主须先取消/等待活动任务；自定义额外包装器的内部资源仍由宿主管理。
- `runtime.shared_budget` / `provider_assembly.shared_budget` 暴露所选绑定，`runtime.shared_budget_snapshot()` 显式读取共享池；未启用返回 `None`，自定义 controller 不支持 snapshot 则报固定错误。读取不持久化、不触发模型，也不宣称该池属于某个 Run/Session；不能把池累计再与它包含的 Run 用量相加。
- 摘要 Runtime 和主 Runtime 可选同一绑定；不同 Provider 可以使用不同 meter、同一个 controller。为摘要创建独立空工具目录，随后把其 Loop/Definition 交给 `AgentSessionHistorySummarizer`，通过 `AsyncSummarizedSessionHistoryPolicy` 接入主 Runtime。预算覆盖准备摘要与后续主调用，但摘要观察器、主 Run 和 Session 的历史统计依然独立。任意自定义准备回调若另行调用未包装 Provider，不会自动计入。
- 预算拒绝沿 Provider 错误进入现有 `MODEL_ERROR` 停止路径，不伪装成已成功模型调用或 Run 内预算原因；未知费用不自动重试。当前包装器没有原生游标适配，选择共享预算并传入 `NativeCursorRecovery` 会在装配前拒绝。宿主后续修改公开注册表、Loop 或 binding 可改变甚至绕过覆盖范围，须自行保持所有生成路由均包装。
- CLI run/run-resume/evaluate/provider-probe 与 TUI 运行/审批恢复/评测/配置化探测可按下文显式加载预算工厂，缺失绑定时拒绝装配而不忽略预算。可另行显式接入[跨服务持久账本](./service-usage-runtime.md)与[Run/Session 关联](./service-usage-links.md)；关联不会把宿主 operation 汇总变成逐 Run 精确用量，这些入口也不会自动执行对账。

Runtime 回归覆盖：不启用时兼容、多个 Run 共享池、摘要/主 Runtime 链路、SQLite 未初始化/重开、未知费用禁止重试、可选快照与客户端关闭。a9 定向验证范围见发布说明；未运行实际模型请求。

### CLI/TUI 预算工厂与池展示（2.0.0a9 Experimental）

配置保留 `"shared_budget": {"binding": "development"}`。CLI 另显式给出工厂与代码执行确认：

```text
wagent run "开始任务" --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
wagent run-resume SESSION RUN --approve-tool-call CALL --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
```

工厂是**受信、非沙箱的宿主 Python 代码**，不是 Agent 工具或插件权限。`--confirm-budget-code` 独立于模型调用、工具代码、工具权限和精确 Call ID 审批；不确认则不加载。框架不改 sys.path、不安装依赖、不从 JSON 导入代码。宿主把模块放到正常 Python 导入路径；入口仅接受 `module:factory`，不接受文件路径。

```python
# my_budget.py：meter 必须由宿主实现真实的上界/计价，不使用示例字符估算。
from contextlib import asynccontextmanager
from w_agent import SQLiteSharedBudget, SharedBudgetLimits, LocalSharedBudgetBinding
from application_pricing import meter

@asynccontextmanager
async def open_budgets():
    ledger = SQLiteSharedBudget("./shared-budget.db", "development-v1",
                                SharedBudgetLimits(max_total_tokens=50000))
    await ledger.initialize()  # 宿主显式选择初始化；不是装配器暗中写入。
    try:
        yield {"development": LocalSharedBudgetBinding(ledger, meter)}
    finally:
        pass  # 宿主在这里关闭自己创建的外部资源；SQLite 控制器无常驻连接。
```

工厂无参数，返回异步上下文管理器，yield 1–64 个具名 `LocalSharedBudgetBinding`；必须包含配置选中的名称。普通 dict、返回 coroutine 的 async 工厂、缺失绑定和错误类型均拒绝。setup/cleanup 与 Runtime 使用在同一事件循环内，清理在模型客户端关闭后进行；Runtime 异常不能被工厂的退出返回值吞掉。工厂初始化一旦已发生，即使后续装配失败也不会自动回滚；setup 内失败/取消前的部分资源由宿主上下文自行清理。同步导入/工厂创建可能阻塞 UI，宿主应保持轻量，将异步准备放到上下文中。

CLI 在原结果中增加 `shared_budget`，TUI 独立面板显示 `known_usage` / `held_usage` 的输入、输出、缓存和总 Token，已知/预留费用、额度、四类票据数量、blocked/breached。它是整个池的读取时快照，不是本次 Run 或可直接相加的 Session 统计；blocked=false 也不等于额度充足。不会显示票据 ID、价格版本、证据或操作人索引。未启用时 CLI 不添加该字段，TUI 显示未启用。

运行完成后的快照读取失败仅显示 `status=unavailable`，不编造零用量、不修改 Run 结果、不重跑模型。工厂清理失败可能发生在模型已执行之后，此时命令/表单报告宿主错误，应检查账本而不是重试生成。取消不等于退款；重复取消也可能中断宿主清理。跨 CLI 进程或恢复要共用持久池，不能把每次新建的内存池误认为累计预算；内存模板只覆盖工厂对象存活期间。

TUI Run 与 Checkpoints 表单新增预算工厂输入，逐次输入 `LOAD BUDGET`；仍需 `RUN` / `RESUME` 与其他独立确认。Run 表单启动时捕获入口并锁定，预算确认与其余确认一起消费；恢复表单也消费预算确认。不增加自动对账、定时刷新或证据读取按钮。

评测和配置化 Provider 探测也支持相同工厂参数：

```text
wagent evaluate builtin:customer-support --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
wagent provider-probe --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --mode safe --json
wagent provider-probe --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --mode active --confirm-active-probe --json
```

整批评测只打开一次工厂，所有用例共用池；不为每个用例重置预算。CLI JSON 添加独立 `shared_budget`，文本和 TUI 使用独立池展示；`--report` 保存的原评测报告格式不变，不能把池快照当成本批独占用量。快照读取失败不改变评测/探测结果，不重试生成。TUI Evaluation 与 Models 配置化探测都需要独立 `LOAD BUDGET`，另保留 `EVALUATE` / `ACTIVE` 确认。

safe 模式只读取模型目录，不预留生成额度；但工厂仍是有副作用的受信宿主代码，必须授权。active/capability 模式使用探测器的 8 输出 Token 最小请求上限，而非 agent 的输出上限；预算包装器按该请求可靠上界预留，不足时不进入生成。普通 URL 端点探测不属于模型预算。工厂、评分器或工具内部的隐藏调用不自动计入，需宿主自行包装。

统一跨账本统计与真实环境验收仍待后续完成；本次验证范围见 a9 发布说明。

## 结构化媒体运行入口（2.0.0a7；针对性回归通过）

### a8：本地上下文模板（2.0.0a8 Experimental；针对性回归通过）

除既有 `text` / `recorded` / `none` 外，`--history` 新增 `retrieved` / `summarized`。二者仅处理历史文本，需要独立 `--confirm-history-transform`，接受筛选或摘要可能丢失事实；不替代 `--confirm-model-call`、记录输入授权、工具加载授权或媒体历史授权，不自动调用额外模型。

```text
wagent run "继续处理退款" --session existing-session --history retrieved --history-query "退款 发票" --history-recent-turns 2 --history-retrieved-turns 4 --confirm-history-transform --confirm-model-call
wagent run "继续讨论" --session existing-session --history summarized --history-summary-chars 4096 --history-max-bytes 65536 --confirm-history-transform --confirm-model-call
```

检索必须显式提供非空 `--history-query`，即使已有 Prompt 或媒体文件也不自动提取查询。`--history-recent-turns` 默认 2，允许 0；检索旧段数默认 4、摘要字符数默认 4096、模板输出 UTF-8 字节数默认 65536，后三者必须为正整数。后者不是 Token 预算。全部参数通过 `BuiltinSessionHistoryOptions` 统一校验，不使用的模式专属选项会被拒绝，不静默忽略；校验先于输入文件读取、工具导入和 Runtime 装配。

TUI Run 提供同样字段（空白表示默认）和 `TRANSFORM HISTORY` 确认；Python 应用仍可直接注入任意 `history_policy`，无需使用此内置选项对象。模板默认输入限制、文本角色约束与损失性边界见 [Session 模板](./sessions.md)。这些接线的针对性回归通过。

`LocalAgentRuntime.run_messages(messages, ...)` 接受非空 `ModelMessage` 序列。原 `run(prompt, ...)` 保留文本用法和默认标题；两者均可逐次传入 `record_inputs`、`include_history`、`history_policy`，默认不额外记录输入、保留文本历史。新消息运行默认标题为 `Agent run`，可显式设置 `session_title`。权限、精确批准 ID、取消与事件回调继续交给同一 Session/Agent 链路；恢复入口不重新注入历史。

```python
from w_agent import load_input_manifest, RecordedSessionHistoryPolicy

messages = load_input_manifest("input.json")  # 只读取并解析；不调用模型。
async with runtime:
    run = await runtime.run_messages(
        messages,
        session_id="existing-session",
        record_inputs=True,
        history_policy=RecordedSessionHistoryPolicy(),
    )
```

Python 宿主自行取得模型发送、Session 输入记录、媒体历史复用的同意；API 不弹出确认。记录器仍可通过公开的 `runtime.sessions` 替换或重新装配。`include_history=False` 可禁用历史；当前消息不受此开关影响。详见 [Session 策略](./sessions.md)。

CLI 的 Prompt 与 `--input-file` 二选一，例如以下 `input.json`（替换示例地址）：

```json
{
  "schema_version": 1,
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "描述这张图片"},
      {"type": "image", "url": "https://example.test/image.png"}
    ]
  }]
}
```

```text
wagent run --input-file input.json --confirm-model-call
wagent run --input-file input.json --record-inputs --confirm-input-recording --confirm-model-call
wagent run "继续分析" --session existing-session --history recorded --confirm-history-media --confirm-model-call
wagent run "独立问题" --history none --confirm-model-call
```

a7 已发布版本的 `--history` 接受 `text`（默认）/ `recorded` / `none`；a8 新增模式见上文。媒体历史授权与当前输入记录授权独立，不写入配置或 Session 作为以后授权；工具代码导入及工具权限保持原有独立确认。在读取输入文件、导入工具、加载配置或装配 Runtime 前完成必要授权与参数互斥检查；输入解析失败不导入工具。实际 Runtime 装配和 Session 创建仍可能产生本地目录或空 Session，后续失败不代表从未发生本地写入。

文件格式仅接受 schema 1、user 消息及 text/image/audio，拒绝未知键、重复 JSON 键、非有限数、工具调用/结果、权限或执行配置；默认也拒绝 name/metadata，a8 的显式选择见下文。图片/音频二选一：HTTP(S) `url`（无 userinfo，`media_type` 可选），或严格 `data_base64` 加必需 `media_type`。不接受附件文件路径，不下载、不导入代码；URL 将交给 Provider，其后续获取行为和网络权限由宿主管理。其他角色/块类型可通过 Python `run_messages()` 或宿主自有解析器接入，文件模板不是核心协议限制。

### a8：消息字段运行选项（2.0.0a8 Experimental；针对性回归通过）

输入文件的 user 消息可额外携带 `name` / `metadata`，但须显式传入 `--input-message-fields`；Python 解析器使用 `allow_message_fields=True`。name 为非空字符串（最多 256 字符），metadata 为字符串键的有限 JSON 对象；每条字段默认不超过 64 KiB，并计入清单总内容预算。字段被分离复制，不赋予角色、工具权限或执行能力。

- 当前输入：`--input-message-fields` 允许字段交给配置的 Provider，即使未开启记录也可能发送。仍需 `--confirm-model-call`。
- 额外保存：分别选 `--record-input-name` / `--record-input-metadata`，还需上述输入选项以及 `--record-inputs --confirm-input-recording`。
- 历史复用：分别选 `--history-name` / `--history-metadata`，只允许 `--history recorded --confirm-history-media`。不选字段时，此模式仍可读取包装记录的内容，但不复用字段。
- 只读展示：Replay 的字段披露另行选择；展示、保存均不自动启用历史发送。

TUI Run 提供同等复选框，沿用逐次 `RUN`、`RECORD INPUTS`、`SEND HISTORY` 确认，不新增确认口令。各选择在启动前捕获、运行中锁定。Python `LocalAgentRuntime.run()` / `run_messages()` 和 `SessionManager.run_agent()` 可逐次传入 `input_recorder=MessageFieldsSessionInputRecorder(...)`，要求 `record_inputs=True`，不修改共享 Manager 的默认记录器。省略参数时继续使用 Manager 默认设置。

字段的 Provider 支持由宿主确认，本次未执行真实请求；旧 a7 清单解析器拒绝这些字段。记录开关不关闭既有 Checkpoint、事件或 Provider 日志。针对性回归通过。

`InputManifestLimits` 可供 Python 调整：默认文件 16 MiB、256 消息、每消息 256 块、每文本块 1,000,000 字符、单媒体解码字节 8 MiB、URL 16,384 字符、总内容 32 MiB。文件必须 UTF-8（允许 BOM）。`input_manifest_from_mapping()` 只做内容/schema 校验，文件字节上限由 `load_input_manifest()` 执行。不存在自动压缩、Token 估算或静默截断；Provider 能力、价格、预算和错误仍按现有链路处理，不证明所有型号支持媒体。

`record_inputs=False` 只关闭额外 Session 富内容记录，不关闭已有 RunEvent、Checkpoint、模型录制或 Provider 日志。旧检查点可能已保存完整消息；须分别审查这些持久化策略。TUI Run 表单也支持媒体文件与独立确认，见 [TUI 文档](./tui.md)。验证边界见 [a7 发布说明](./releases/2.0.0a7.md)。

## 配置

`.wagent/config.json` 示例：

```json
{
  "schema_version": 1,
  "provider": {
    "template": "deepseek",
    "name": "primary",
    "model": "deepseek-chat",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout": 60
  },
  "agent": {
    "name": "local-assistant",
    "system_prompt": "Answer clearly and cite uncertainty.",
    "max_steps": 4,
    "max_tool_calls": 4,
    "max_output_tokens": 1024,
    "emit_text_deltas": true,
    "emit_tool_call_deltas": false,
    "emit_output_blocks": false,
    "max_input_tokens": 12000,
    "max_cumulative_output_tokens": 3000,
    "max_total_tokens": 15000,
    "require_usage": true,
    "token_estimator": "character",
    "estimator_characters_per_token": 4,
    "require_estimate": true,
    "soft_limit_ratio": "0.8"
  },
  "invocation": {
    "max_attempts_per_route": 1,
    "max_routes": 1,
    "timeout": 60
  },
  "tools": {
    "enabled": ["repository_search", "save_note"]
  },
  "pricing": {
    "version": "my-prices-2026-09-18",
    "currency": "USD",
    "max_cost": "0.25",
    "estimate_before_call": true,
    "require_estimate": true,
    "soft_limit_ratio": "0.8",
    "prices": [
      {
        "provider": "primary",
        "model": "deepseek-chat",
        "input_per_million": "1.00",
        "output_per_million": "2.00",
        "cached_input_per_million": "0.50"
      }
    ]
  }
}
```

`template` 可使用内置 `anthropic`、`gemini`、`ollama`、`qwen-native`、`deepseek`、`glm`、`qwen` 或 `turbo`。`turbo` 必须显式提供 `base_url`。配置拒绝未知字段、明文 `api_key` 与扩展中的凭据字段；凭据只在装配时从 `api_key_env` 读取，不写入 Run、Session 或工程装配编码。

`tools.enabled` 只从宿主明确提供的 `tool_bindings` Catalog 中选择名称。JSON 不导入代码、不注册未知工具，也不授予权限或审批；启用工具时 `agent.max_tool_calls` 必须大于零。未选择的 Catalog 工具不会进入本次 `ToolRegistry` 或模型上下文。

`pricing` 可选且完全由本地开发者提供；框架不内置可能过期的厂商价格。`version`、币种、最大 Run 费用和每个精确 Provider/Model 的百万 Token 单价必须显式给出，金额建议使用 JSON 字符串避免浮点歧义。示例价格仅演示结构，不代表厂商实际价格。缓存输入未单独给价时按普通输入价保守计算；缺少匹配价格或任一尝试用量时，启用费用预算的 Run 会以 `cost-unavailable` 失败关闭。调用前费用预估必须通过 `estimate_before_call=true` 显式启用，并要求 Agent 配置 Token 估算器以及单次输出或累计总量上限；`require_estimate` 控制估算不可用时是否在模型生成请求前失败关闭。

## CLI

先检查配置化 Provider 时可使用：

```powershell
wagent provider-probe --config .wagent/config.json --mode safe --json
wagent provider-probe --config .wagent/config.json --mode active `
  --confirm-active-probe --json
```

`safe` 不生成内容，但具体 Provider 的目录实现可能是远程请求或静态声明；`active` 才以最多 8 输出 Token 验证实际生成和流终止协议，因此需要独立明确授权。

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

`--confirm-model-call` 是每次命令必需的显式授权。成功结果包含 Session ID、Run ID、停止原因、最终文本、步骤/工具计数、逐尝试账本，以及 Token/费用累计值与完整性标记。使用 `--session <id>` 可继续已有文本 Session。

开发者自有工具可由明确的 `module:attribute` 入口返回一个 `ToolBinding` 或其可迭代集合。导入 Python 工具代码是独立风险，CLI 只有同时传入 `--tool-entry` 与 `--confirm-tool-code` 才会执行；配置文件本身不能触发导入。权限也必须逐次通过 `--grant-permission` 授予：

```powershell
wagent run "Save this note" `
  --config .wagent/config.json `
  --tool-entry my_agent_tools:build_tools `
  --confirm-tool-code `
  --grant-permission notes.write `
  --confirm-model-call `
  --json
```

若策略要求逐调用审批，Run 以 `needs-approval` 停止，并返回 `checkpoint_id` 及仅含 `call_id`、工具名和参数名的 `pending_tool`；参数值不会打印。检查后以同一配置、工具入口和权限恢复，并批准精确 Call ID：

```powershell
wagent run-resume <session-id> <run-id> `
  --config .wagent/config.json `
  --tool-entry my_agent_tools:build_tools `
  --confirm-tool-code `
  --grant-permission notes.write `
  --approve-tool-call <call-id> `
  --confirm-model-call `
  --json
```

每次恢复都会重新要求模型调用授权、工具代码授权与精确 Call ID。工具入口可能在两次进程间发生变化，生产用法应由应用固定包版本并验证来源。

不知道 Run/Call ID 时可先执行 `wagent checkpoint list --json`，也可用 `--session` 过滤。列表只含脱敏的 Agent、状态、工具名、Call ID、参数名与 Token/费用计量，不读取 Prompt、参数值、输出或凭据。

## TUI

Run 页面读取同一配置。用户必须输入 `RUN` 才会发起模型调用；成功后显示输出、Token 和费用计量，并把 Session ID 留在输入框中用于下一轮。界面不会把确认保存为长期授权。Checkpoint 页面可刷新 Agent 审批摘要，也可从指定 State Root 刷新 Workflow 摘要。开发者工具代码仅在输入 `LOAD TOOLS` 后导入，Workflow Definition 仅在输入 `LOAD WORKFLOW` 后导入；Agent 与 Workflow 恢复分别要求独立的 `RESUME` / `RESUME WORKFLOW` 一次性确认。

## 预算语义

- `max_output_tokens` 是单次模型请求的输出上限。
- `emit_text_deltas=true` 显式启用 `model-text-delta` RunEvent；独立的 `emit_tool_call_deltas=true` 启用 `model-tool-call-delta`（含原始参数片段）。两个开关都关闭时使用收集模式。`emit_output_blocks=true` 另行保存标准图片/音频输出块，不改变收集/流模式；可能包含 URL 或 Base64。JSONL 会保存明确启用的原始内容，TUI/CLI 默认只显示安全元数据，不展示正文、工具名、参数或媒体内容。
- `max_input_tokens`、`max_cumulative_output_tokens`、`max_total_tokens` 是一个 Run 内的累计上限。
- `require_usage=true` 时，只要某次模型尝试未报告用量（包括成功重试之前的失败尝试），Run 就以 `token-usage-unavailable` 停止。
- `token_estimator="character"` 是必须显式选择的本地启发式模板；`require_estimate=true` 在估算不可用时调用前失败关闭。Python API 可注入任意 `TokenEstimator`，不受该模板限制。
- 调用前估算会公开 `token-estimated`、收紧总量对应的输出额度，并在预计输入已无生成空间时阻止网络请求；`soft_limit_ratio` 只产生 `token-budget-warning`，不停止 Run。
- 字符估算器标记为非精确并拒绝图片/音频。它不覆盖厂商隐藏开销、重试或故障转移；调用后仍以 Provider 实报用量核算。
- `pricing.max_cost` 是使用指定价格表版本计算的累计 Run 费用上限；费用使用十进制精确计算，超限时在执行本次响应中的工具前以 `cost-budget` 停止。
- 显式费用预估使用可替换 `CostEstimator`。默认 `PricingCostEstimator` 根据已选路由、配置允许的重试/故障转移次数、预计输入和输出上限生成 `cost-estimated` 包络；缓存/非缓存输入取较高报价。预计累计费用超限时在模型生成请求前停止，`pricing.soft_limit_ratio` 产生 `cost-budget-warning`。路由目录解析是否访问网络仍由 Provider 实现决定。
- 启发式 Token 估算会使费用包络标记为非保守；只有精确 Token 估算才能把默认包络标记为保守。无论哪种情况，费用预算仍依据调用后 Provider 实际报告值再次核算；缺少用量或价格时不会按零费用继续。
- 将 `max_attempts_per_route` 或 `max_routes` 设为大于 1 会授权额外、可能计费的重试或故障转移。

## 开放装配边界

`load_local_runtime_config()`、`assemble_local_provider()` 与 `assemble_local_runtime()` 是便利层，不是新的封闭 Runtime。Provider 单独装配返回 `LocalProviderAssembly`，只解析凭据引用并构造对象，不注册、不访问网络；应用随后可选择任意探测或注册策略。完整 Runtime 公开 Definition、Loop、ModelRegistry、ToolRegistry 和 SessionManager；`run()`/`resume()` 可通过 `event_callback` 投影按持久化顺序产生的实时事件。两种装配都支持 `async with` 和幂等 `aclose()`；关闭后完整 Runtime 拒绝继续运行。CLI/TUI 自动在同一事件循环内完成使用与关闭。应用可替换模板注册表、Provider 传输、路由、工具与 Store。`2.0.0a4`还可用 `assemble_local_runtime(..., stream_recovery=NativeCursorRecovery(max_resumes=2))` 注入恢复策略；它只在 Agent 配置显式启用文本或工具参数增量且 Provider 实现相应协议时生效，JSON 配置不会自行加载策略代码或持久化游标。

应用将 `{name: ToolBinding}` 作为 `tool_bindings` 传给装配器；配置只能选择其中的子集。`LocalAgentRuntime.run()` 接收本次运行的权限和可选批准 ID，`resume()` 接收 Session/Run ID、权限与非空精确批准集合。配置、Session、Checkpoint 和工程装配编码都不能生成权限、批准或本地执行授权。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
