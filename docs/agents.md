# Agent Runtime 与 ReAct Loop

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./agents.en.md) | 简体中文

a7（2.0.0a7，针对性回归通过）新增 `AgentDefinition.emit_tool_results` 和 `max_tool_result_event_bytes`：默认不记录工具结果正文；显式开启后，`TOOL_COMPLETED` 可携带有界、可替换编码的模型可见结果。待审批票据不记录，编码失败只标记状态而不重试副作用。详见[工具结果记录与独立回放披露](./event-replay.md)。

`2.0.0a6`（针对性回归通过）新增可选工具续执行：`ToolContinuation` 让 ReAct 保存尚未完成的工具引用并等待明确授权；含票据的检查点使用 schema 2，普通检查点保持 schema 1。恢复只走独立恢复处理器，不重新启动工具、不重发审批前模型请求；不确定执行保留 `RESUMING`。`2.0.0a6`另提供 `resumable_workflow_tool()` 专用引用与续执行桥；双层授权协调服务已加入`2.0.0a6`（针对性回归通过），TUI 引导亦已加入`2.0.0a6`（针对性回归通过），详见 [工具续执行](./tools.md)。

状态：公开 `AgentLoop`/Run 协议、有界单 Agent `ReactAgentLoop`、Token/费用预算、追加式本地 RunStore、审批后恢复、本地 Session 生命周期和应用级实时事件回调为 `Implemented`（Phase 3 / 自 `2.0.0a3` 起）。`2.0.0a4`新增持久化 RunEvent 的游标分页、可替换 JSON 脱敏投影、显式工具参数增量和显式图片/音频输出投影；通用新模态仍为 `Planned`，多 Agent 编排为 `Reserved`。

## 分层

```text
AgentDefinition + RunContext
              ↓
AgentLoop（可整体替换）
   ├── ModelExecutor
   ├── ToolRegistry
   └── ToolExecutorProtocol
              ↓
RunEvent* → RunStore → RunResult / RunCheckpoint
```

`ReactAgentLoop` 是普通首方实现，没有微内核特权。开发者可以实现同一 `AgentLoop` 协议替换整个推理链路，也可以替换模型路由、模型执行、工具目录、工具策略或工具执行器。

## 当前闭环

```python
from w_agent import (
    AgentDefinition,
    MessageRole,
    ModelMessage,
    ReactAgentLoop,
    RunContext,
)

loop = ReactAgentLoop(model_executor, tools, tool_executor)
context = RunContext(
    "run-1",
    (ModelMessage.text(MessageRole.USER, "计算 2 + 3"),),
)
result = await loop.run(AgentDefinition("assistant"), context)
```

每一步执行：

1. 从当前 Scope 读取模型可见的工具 Definition。
2. 通过 `ModelExecutor.invoke()` 执行一次已路由模型请求。
3. 没有工具调用时以 `COMPLETED` 返回最终文本。
4. 有工具调用时解析 JSON 参数并交给 `ToolExecutorProtocol`。
5. 成功或失败结果都以 `ToolResultContent` 回送模型，进入下一步。

`max_steps` 和 `max_tool_calls` 是强制预算。`max_output_tokens` 是每次模型请求的生成上限；累计预算使用独立的 `TokenBudget`，避免混淆。当前模板按顺序执行同一模型响应中的工具调用，不自动并行，也不重试工具。

```python
from w_agent import AgentDefinition, CharacterTokenEstimator, TokenBudget

definition = AgentDefinition(
    "assistant",
    max_output_tokens=2_000,
    emit_text_deltas=True,
    token_budget=TokenBudget(
        max_input_tokens=20_000,
        max_output_tokens=6_000,
        max_total_tokens=24_000,
        require_usage=True,
        require_estimate=True,
        soft_limit_ratio="0.8",
    ),
)

# 仅为本地显式选择的启发式模板；生产可注入自己的精确 tokenizer。
estimator = CharacterTokenEstimator(characters_per_token=4)
# loop = ReactAgentLoop(..., token_estimator=estimator)
```

## 事件和结果

`stream()` 返回单次消费的 `ReactAgentExecution`，依次输出 `RUN_STARTED`、模型阶段、工具阶段和 `RUN_COMPLETED` 事件；结束后从 `execution.result` 读取最终结果。`run()` 是收集这些事件的便利方法。事件在向调用者暴露前先写入 `RunStore`。

`InMemoryRunStore` 适用于测试和短期本地运行；`JsonlRunStore` 对每个 Run 使用追加式 `events.jsonl` 和原子替换的 `checkpoint.json`，在新进程/新 Loop 实例中可重新读取。`list_checkpoints()` 返回 `RunCheckpointSummary`，只含恢复定位、参数名和计量，不含 Prompt、参数值、输出或凭据。事件序号必须连续，未知 Schema 版本或损坏日志会失败关闭。`2.0.0a4`的 JSONL 追加也改为逐行核对至目标序号，不再为每次追加构造整份事件列表；仍是线性扫描，后续可另加索引。

`2.0.0a6`新增 `RunEventReplay`、`RunEventCursor` 和 `RunEventPage`：应用可用新进程打开相同的 `JsonlRunStore`，按绑定 Run ID 的序号游标分页取回已持久化事件。读端接受最小 `RunEventSource.events()` 协议，也接受可选 `PagedRunEventSource.events_page()`；内置内存/JSONL Store 已实现后者，JSONL 按行扫描至当前页及一条前瞻记录，内存占用随页大小而非整份日志增长。旧自定义 Store 无需改动，仍可使用 `events()` 回退路径。JSONL 没有随机访问索引，后续页仍需扫描前缀；本页之后的损坏记录会在游标继续读取时才暴露。`has_more` 只描述本次读取时的日志快照；运行中可持有 `next_cursor` 再次读取。这只是读取已记录的事件，不会重新执行模型、工具或审批，也不恢复任意运行栈。API 已通过针对性回归；原始分页不会自行决定内容披露策略。

同一工作区新增 `RunEventProjector`、`SafeRunEventProjector` 和 `ProjectedRunEventPage`。`RunEventReplay.projected_page()` 默认使用内容无关的安全投影，也允许应用在已经获得原始 Store 读取权后显式传入自己的投影器。投影结果必须是有限深度、数值有限且键为字符串的 JSON 兼容对象；投影器异常、返回非对象或包含任意 Python 对象都会失败关闭。CLI `wagent run-events` 与 TUI Checkpoints 页直接请求安全投影页，只保留受类型或枚举约束的计数、状态和费用摘要；模型正文、工具参数/结果、原始异常和任意 Metadata 不进入界面。原始 `page()` API 继续保留兼容性，其 `RunEventPage.events` 仍可能包含敏感内容，本地应用必须自行控制读取权限。自定义投影器不是安全沙箱，框架不会替应用决定哪些业务字段可以公开。

`FieldPolicyRunEventProjector` 是无需编写投影代码的默认拒绝模板。`RunEventFieldPolicy(include=(...), mask=(...), mask_value="***")` 只选择 `RunEvent.data` 的顶层字段；精确事件类型规则优先，`"*"` 只在没有精确规则时回退。未列出的字段被删除，允许与掩码重叠、重复字段、未知事件类型和无效掩码会在构造时拒绝。

`NestedFieldRunEventProjector` 为嵌套 JSON 数据提供同样的默认拒绝策略。每条 `RunEventPathRule` 用字符串键/非负数组索引组成源路径，以纯字符串目标路径构造输出对象，并选择 `COPY` 或固定 `MASK`；目标路径不同即可完成重命名。缺失源路径被忽略，目标重复或父子冲突在构造时拒绝。复制一个对象/数组节点会复制其整个子树，因此规则仍应由已有读取授权的应用明确配置；任意计算、条件逻辑与业务授权判断应使用自定义投影器。

图片/音频输出使用独立的显式链路。`AgentDefinition.emit_output_blocks=True` 才会调用可替换的 `ModelOutputEventEncoder`；默认 `StandardMultimodalEventEncoder` 只处理 Provider 无关的 `ImageContent`/`AudioContent`，不访问 URL，对内联数据设置 8 MiB 上限，并保存 Base64、字节数和 SHA-256。文本和工具块不会被该编码器顺带公开。每个已编码块在 `MODEL_COMPLETED` 前作为 `MODEL_OUTPUT_BLOCK` 持久化；该开关及其内容会随审批 Checkpoint 保留。标准编码失败会产生不含异常正文的 `MODEL_OUTPUT_BLOCK_FAILED`，以 `OUTPUT_EVENT_ERROR` 在工具执行前终止，同时保留已知用量。应用可替换编码器，把内容转存到自己的 Blob Store 或支持新模态。

`MultimodalRunEventProjector` 默认使用 `metadata`：只显示模态、来源类型、媒体类型，以及内联数据的大小/摘要，不显示 URL 或内容。`references` 允许 URL 但仍隐藏内联正文，`content` 才返回实际 URL 或 Base64。三档都会校验标准内联数据的大小和摘要；其他事件交给可替换 fallback，默认仍使用 `SafeRunEventProjector`。这是披露模板，不替代应用权限判断。

```python
from w_agent import JsonlRunStore, RunEventReplay

reader = RunEventReplay(JsonlRunStore(".wagent/state"))
page = await reader.page("run-1", limit=50)
next_page = await reader.page("run-1", cursor=page.next_cursor, limit=50)
safe_page = await reader.projected_page("run-1", limit=50)
```

```python
from w_agent import (
    FieldPolicyRunEventProjector,
    RunEventFieldPolicy,
    RunEventType,
)

projector = FieldPolicyRunEventProjector({
    RunEventType.MODEL_TOOL_CALL_DELTA: RunEventFieldPolicy(
        include=("step", "name"),
        mask=("arguments_delta",),
    ),
})
page = await reader.projected_page("run-1", projector=projector)
```

```python
from w_agent import (
    NestedFieldRunEventProjector,
    RunEventPathAction,
    RunEventPathRule,
)

nested = NestedFieldRunEventProjector({
    "model-completed": (
        RunEventPathRule(
            ("response", "items", 0, "label"),
            ("result", "name"),
        ),
        RunEventPathRule(
            ("response", "credential"),
            ("result", "credential"),
            RunEventPathAction.MASK,
        ),
    ),
})
```

```python
from w_agent import MediaProjectionMode, MultimodalRunEventProjector

definition = AgentDefinition("vision", emit_output_blocks=True)
media_view = MultimodalRunEventProjector(MediaProjectionMode.METADATA)
page = await reader.projected_page("run-1", projector=media_view)
```

Run 事件包含重建模型上下文所需的模型文本、工具参数和结果阶段信息，因此调用者必须把它们视为可能含敏感数据的本地运行内容。工具审计是另一条记录，只保存参数名等最小元数据。当前 Store 不负责加密，保存目录的访问控制由本地应用负责。

`MODEL_COMPLETED` 包含本次响应 Token、逐尝试账本和 `attempt_usage_complete`；失败模型阶段也记录不含 Prompt/凭据的尝试摘要。随后产生的 `TOKEN_USAGE` 包含 Run 累计已知值。`RunResult.attempts` 提供强类型完整账本，`RunResult.usage` 提供累计已知用量，`usage_complete` 表明包括重试/故障转移在内的每次模型尝试是否都收到 Provider 用量。真实零用量与未上报不会混淆。

Token 硬预算在每个成功响应后按 Provider 已报告的逐尝试实际值核算，超限时在执行该响应中的工具前以 `TOKEN_BUDGET` 停止。剩余输出/总量也会收紧下一请求的输出上限。应用可向 `ReactAgentLoop` 注入异步 `TokenEstimator`；调用前产生的 `TokenEstimate` 会校验累计输入/总量，并从总量余额中扣除预计输入后再收紧本次输出上限。`require_estimate=True` 在估算器缺失、失败或返回非法结果时以 `TOKEN_ESTIMATE_UNAVAILABLE` 失败关闭；否则用 `TOKEN_ESTIMATE_UNAVAILABLE` 事件公开降级但允许继续。`soft_limit_ratio` 只产生 `TOKEN_BUDGET_WARNING`，不会暗中改变停止策略。`TOKEN_ESTIMATED` 只含数量、估算器标识和精确性，不含 Prompt。

内置 `CharacterTokenEstimator` 统计中立消息中的文本、工具调用/结果、工具与响应 Schema 和停止词；它明确标记 `exact=False`，不处理图片/音频，也不声称覆盖厂商隐藏格式开销。应用可替换为模型专用 tokenizer。估算只保护下一次初始请求，不能预知重试/故障转移或 Provider 最终记账，因此调用后仍始终以实际 Usage 核算。设置 `require_usage=True` 后，只要本轮任一尝试未报告用量（包括随后成功的重试之前的失败尝试），Run 就以 `TOKEN_USAGE_UNAVAILABLE` 停止。

费用计量使用应用提供的 `PriceTable`/`PricingResolver`，按精确 Provider、Model、价格表版本和币种计算，普通输入、缓存输入和输出费用均使用 `Decimal`。`CostBudget` 将一个 Run 绑定到明确的价格表版本；每个尝试都已计价时 `RunResult.cost_complete` 才为真。超限响应在执行工具前以 `COST_BUDGET` 停止；缺少价格、用量、版本或币种不一致时以 `COST_UNAVAILABLE` 失败关闭。费用及表版本进入 `COST_USAGE`、终止事件、结果、Session 和审批 Checkpoint，恢复后继续累计。框架不内置可能过期的厂商价格，也不从 Token 静默推断金额。

`CostBudget(estimate_before_call=True)` 显式启用调用前费用预估。可替换 `CostEstimator` 接收不含 Prompt 的 `CostEstimateRequest`；默认 `PricingCostEstimator` 用已选路由、允许的重试/故障转移次数、Token 输入估算和本次输出上限生成 `CostEstimate`。`COST_ESTIMATED` 同时公开首选单次费用与完整重放包络，`COST_ESTIMATE_UNAVAILABLE` 公开降级，`require_estimate=True` 可在不可估算时以 `COST_ESTIMATE_UNAVAILABLE` 停止，`soft_limit_ratio` 产生 `COST_BUDGET_WARNING`。预估包络超出剩余预算时在模型生成请求前停止；调用后仍始终以 Provider 实报用量再次核算。Session 级累计、逐尝试账本、调用前 Token/费用估算、软阈值事件，以及按 Agent 跨 Session 的只读用量/费用汇总均已实现。

`emit_text_deltas=False` 是兼容默认值。`2.0.0a4`另有独立的 `emit_tool_call_deltas=False`；两者任一显式开启时，ReAct 使用 `ModelExecutor.stream()`，分别在 `MODEL_COMPLETED` 前持久化/输出 `MODEL_TEXT_DELTA`（文本）或 `MODEL_TOOL_CALL_DELTA`（`step`、`block_index`、`call_id`、`name`、`arguments_delta`）。开启文本流不会顺带暴露工具参数。两个开关都关闭时沿用收集式 `invoke()`。最终 `RunResult`、Usage、Attempt 账本与工具循环语义不变；已经公开任何增量后的模型失败不会被普通重试/故障转移静默掩盖。可在 `ReactAgentLoop(..., stream_recovery=NativeCursorRecovery(max_resumes=2))` 显式装配原生游标续流，或注入文本前缀恢复策略；仅在流模式生效。若启用调用前费用估算，估算包络会把允许的额外续流/重放连接计入每条路由的最大尝试数；Provider 未上报的失败尝试用量仍为未知，不能以预估代替结算。原始工具参数增量和显式保存的媒体块都可能包含敏感内容，JSONL Store 会持久化它们；默认 CLI/TUI 安全投影只显示计数和状态，不显示 `call_id`、工具名、参数、媒体 URL 或内联正文。内置厂商原生续流适配仍为后续能力。

## 首批模板

`customer_support_agent()` 和 `coding_agent()` 构建普通 `AgentDefinition`。对应的 `CUSTOMER_SUPPORT_AGENT_TEMPLATE` / `CODING_AGENT_TEMPLATE` 公开推荐工具名和默认值，所有字段都可在 `build()` 时覆盖，也可完全弃用模板。

模板不绑定 Provider，不注册或隐藏工具，不授予权限、审批或本地执行权。客服模板建议证据检索、客户/工单查询与受审批写入；编码模板建议工作区读写与 `sandbox_command`。应用仍需自行注册工具、配置 Scope 和权限，并为编码执行选择 Docker 沙箱或显式授权的本地开发模式。

## 审批和停止

当策略层返回 `NEEDS_APPROVAL` 时，工具处理器尚未执行；Loop 不把拒绝结果发送给模型，保存 `RunCheckpoint`，并以 `StopReason.NEEDS_APPROVAL` 返回 `pending_tool_call` 和 `checkpoint_id`。`2.0.0a6`的类型化续执行也使用此停止原因，但表示准备处理器已经返回票据、尚未完成工具。批准只能来自本地应用提供的 `ToolExecutionContext.approved_call_ids`；模型输出不能自行授权。

```python
store = JsonlRunStore(".wagent/state")
loop = ReactAgentLoop(model_executor, tools, tool_executor, store=store)

first = await loop.run(definition, context)
resumed = await loop.resume(
    first.checkpoint_id,
    tool_context=ToolExecutionContext(
        permissions=frozenset({"notes.write"}),
        approved_call_ids=frozenset({"call-1"}),
    ),
)
```

恢复会继续执行原待审批调用、同一模型响应中的剩余调用，再进入下一模型步骤，不会重新发起审批前的模型请求。Checkpoint 在执行副作用前被原子 claim；若进程在结果确定落盘前退出，状态停在 `RESUMING`，下一次恢复抛出 `RunResumeConflictError`，要求开发者人工核实，而不会静默重复副作用。未提供批准时，Checkpoint 恢复为 `PENDING_APPROVAL`。

Checkpoint 不保存权限或批准凭据。恢复时必须由本地应用重新提供。`SessionManager` 已提供列表、归档、跨 Run 文本对话投影和审批恢复协调；`2.0.0a6`新增[事件累积快照](./event-replay.md)（针对性回归通过）；工具结果正文可选记录已加入a7（2.0.0a7，针对性回归通过），只读 Replay 已在 a7 提供，专用媒体渲染仍为 Planned，任意位置执行恢复不属于此回放能力。详见[Session 生命周期与跨 Run 上下文](./sessions.md)。

其他停止原因包括 `MAX_STEPS`、`MAX_TOOL_CALLS`、`TOKEN_BUDGET`、`TOKEN_USAGE_UNAVAILABLE`、`COST_BUDGET`、`COST_UNAVAILABLE`、`MODEL_ERROR` 和 `CANCELLED`。模型错误不会泄露 Prompt；工具异常正文不会直接回送模型。
