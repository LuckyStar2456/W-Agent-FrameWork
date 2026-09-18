# Agent Runtime 与 ReAct Loop

[English](./agents.en.md) | 简体中文

状态：公开 `AgentLoop`/Run 协议、有界单 Agent `ReactAgentLoop`、Token/费用预算、追加式本地 RunStore、审批后恢复、本地 Session 生命周期和应用级实时事件回调为 `Implemented`（Phase 3 / 当前 `2.0.0a3`）。通用事件回放和多 Agent 编排仍为 `Planned` 或 `Reserved`。

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

`InMemoryRunStore` 适用于测试和短期本地运行；`JsonlRunStore` 对每个 Run 使用追加式 `events.jsonl` 和原子替换的 `checkpoint.json`，在新进程/新 Loop 实例中可重新读取。`list_checkpoints()` 返回 `RunCheckpointSummary`，只含恢复定位、参数名和计量，不含 Prompt、参数值、输出或凭据。事件序号必须连续，未知 Schema 版本或损坏日志会失败关闭。

Run 事件包含重建模型上下文所需的模型文本、工具参数和结果阶段信息，因此调用者必须把它们视为可能含敏感数据的本地运行内容。工具审计是另一条记录，只保存参数名等最小元数据。当前 Store 不负责加密，保存目录的访问控制由本地应用负责。

`MODEL_COMPLETED` 包含本次响应 Token、逐尝试账本和 `attempt_usage_complete`；失败模型阶段也记录不含 Prompt/凭据的尝试摘要。随后产生的 `TOKEN_USAGE` 包含 Run 累计已知值。`RunResult.attempts` 提供强类型完整账本，`RunResult.usage` 提供累计已知用量，`usage_complete` 表明包括重试/故障转移在内的每次模型尝试是否都收到 Provider 用量。真实零用量与未上报不会混淆。

Token 硬预算在每个成功响应后按 Provider 已报告的逐尝试实际值核算，超限时在执行该响应中的工具前以 `TOKEN_BUDGET` 停止。剩余输出/总量也会收紧下一请求的输出上限。应用可向 `ReactAgentLoop` 注入异步 `TokenEstimator`；调用前产生的 `TokenEstimate` 会校验累计输入/总量，并从总量余额中扣除预计输入后再收紧本次输出上限。`require_estimate=True` 在估算器缺失、失败或返回非法结果时以 `TOKEN_ESTIMATE_UNAVAILABLE` 失败关闭；否则用 `TOKEN_ESTIMATE_UNAVAILABLE` 事件公开降级但允许继续。`soft_limit_ratio` 只产生 `TOKEN_BUDGET_WARNING`，不会暗中改变停止策略。`TOKEN_ESTIMATED` 只含数量、估算器标识和精确性，不含 Prompt。

内置 `CharacterTokenEstimator` 统计中立消息中的文本、工具调用/结果、工具与响应 Schema 和停止词；它明确标记 `exact=False`，不处理图片/音频，也不声称覆盖厂商隐藏格式开销。应用可替换为模型专用 tokenizer。估算只保护下一次初始请求，不能预知重试/故障转移或 Provider 最终记账，因此调用后仍始终以实际 Usage 核算。设置 `require_usage=True` 后，只要本轮任一尝试未报告用量（包括随后成功的重试之前的失败尝试），Run 就以 `TOKEN_USAGE_UNAVAILABLE` 停止。

费用计量使用应用提供的 `PriceTable`/`PricingResolver`，按精确 Provider、Model、价格表版本和币种计算，普通输入、缓存输入和输出费用均使用 `Decimal`。`CostBudget` 将一个 Run 绑定到明确的价格表版本；每个尝试都已计价时 `RunResult.cost_complete` 才为真。超限响应在执行工具前以 `COST_BUDGET` 停止；缺少价格、用量、版本或币种不一致时以 `COST_UNAVAILABLE` 失败关闭。费用及表版本进入 `COST_USAGE`、终止事件、结果、Session 和审批 Checkpoint，恢复后继续累计。框架不内置可能过期的厂商价格，也不从 Token 静默推断金额。

`CostBudget(estimate_before_call=True)` 显式启用调用前费用预估。可替换 `CostEstimator` 接收不含 Prompt 的 `CostEstimateRequest`；默认 `PricingCostEstimator` 用已选路由、允许的重试/故障转移次数、Token 输入估算和本次输出上限生成 `CostEstimate`。`COST_ESTIMATED` 同时公开首选单次费用与完整重放包络，`COST_ESTIMATE_UNAVAILABLE` 公开降级，`require_estimate=True` 可在不可估算时以 `COST_ESTIMATE_UNAVAILABLE` 停止，`soft_limit_ratio` 产生 `COST_BUDGET_WARNING`。预估包络超出剩余预算时在模型生成请求前停止；调用后仍始终以 Provider 实报用量再次核算。Session 级累计、逐尝试账本、调用前 Token/费用估算、软阈值事件，以及按 Agent 跨 Session 的只读用量/费用汇总均已实现。

`emit_text_deltas=False` 是兼容默认值，ReAct 使用收集式 `invoke()`。显式设为 `True` 后改用同一个 `ModelExecutor.stream()` 安全透传路径，并在 `MODEL_COMPLETED` 之前持久化/输出 `MODEL_TEXT_DELTA`（`step`、`block_index`、`text`）；最终 `RunResult`、Usage、Attempt 账本与工具循环语义不变。已经公开任何增量后的模型失败不会被普通重试/故障转移静默掩盖，是否启用模型层验证前缀恢复仍由调用者自己的执行器策略决定。TUI 只显示事件类型与安全元数据，不显示增量文本。工具参数增量、图片/音频块和任意 RunEvent 跨进程回放仍为后续能力。

## 首批模板

`customer_support_agent()` 和 `coding_agent()` 构建普通 `AgentDefinition`。对应的 `CUSTOMER_SUPPORT_AGENT_TEMPLATE` / `CODING_AGENT_TEMPLATE` 公开推荐工具名和默认值，所有字段都可在 `build()` 时覆盖，也可完全弃用模板。

模板不绑定 Provider，不注册或隐藏工具，不授予权限、审批或本地执行权。客服模板建议证据检索、客户/工单查询与受审批写入；编码模板建议工作区读写与 `sandbox_command`。应用仍需自行注册工具、配置 Scope 和权限，并为编码执行选择 Docker 沙箱或显式授权的本地开发模式。

## 审批和停止

当工具返回 `NEEDS_APPROVAL` 时，Loop 不执行工具、不把拒绝结果发送给模型，保存 `RunCheckpoint`，并以 `StopReason.NEEDS_APPROVAL` 返回 `pending_tool_call` 和 `checkpoint_id`。批准只能来自本地应用提供的 `ToolExecutionContext.approved_call_ids`；模型输出不能自行授权。

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

Checkpoint 不保存权限或批准凭据。恢复时必须由本地应用重新提供。`SessionManager` 已提供列表、归档、跨 Run 文本对话投影和审批恢复协调；多模态/工具事件通用回放和任意位置恢复仍为 `Planned`。详见[Session 生命周期与跨 Run 上下文](./sessions.md)。

其他停止原因包括 `MAX_STEPS`、`MAX_TOOL_CALLS`、`TOKEN_BUDGET`、`TOKEN_USAGE_UNAVAILABLE`、`COST_BUDGET`、`COST_UNAVAILABLE`、`MODEL_ERROR` 和 `CANCELLED`。模型错误不会泄露 Prompt；工具异常正文不会直接回送模型。
