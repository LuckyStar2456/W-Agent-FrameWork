# Agent Runtime 与 ReAct Loop

[English](./agents.en.md) | 简体中文

状态：公开 `AgentLoop`/Run 协议、单次消费的 Run 事件流，以及有界单 Agent `ReactAgentLoop` 为 `Implemented`（Phase 3 / `2.0.0a1`）。持久化 Session、事件存储、审批后恢复和多 Agent 编排仍为 `Planned` 或 `Reserved`。

## 分层

```text
AgentDefinition + RunContext
              ↓
AgentLoop（可整体替换）
   ├── ModelExecutor
   ├── ToolRegistry
   └── ToolExecutorProtocol
              ↓
RunEvent* → RunResult
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

`max_steps` 和 `max_tool_calls` 是强制预算。当前模板按顺序执行同一模型响应中的工具调用，不自动并行，也不重试工具。

## 事件和结果

`stream()` 返回单次消费的 `ReactAgentExecution`，依次输出 `RUN_STARTED`、模型阶段、工具阶段和 `RUN_COMPLETED` 事件；结束后从 `execution.result` 读取最终结果。`run()` 是收集这些事件的便利方法。

Run 事件包含重建本次进程内模型上下文所需的模型文本、工具参数和结果阶段信息，因此调用者必须把它们视为可能含敏感数据的运行内容。工具审计是另一条记录，只保存参数名等最小元数据。

当前 ReAct 使用模型执行器的收集式 `invoke()`，所以 Run 事件尚不包含逐 Token 增量。模型层本身已经支持安全透传，接入 Agent RunEvent 是后续工作。

## 审批和停止

当工具返回 `NEEDS_APPROVAL` 时，Loop 不执行工具、不把拒绝结果发送给模型，并以 `StopReason.NEEDS_APPROVAL` 返回 `pending_tool_call`。批准只能来自本地应用提供的 `ToolExecutionContext.approved_call_ids`；模型输出不能自行授权。

当前没有持久化恢复句柄。调用者可以在新 Run 中预先提供批准；真正从同一事件位置继续的 Session/Checkpoint 恢复仍为 `Planned`，不得把重新运行描述为恢复。

其他停止原因包括 `MAX_STEPS`、`MAX_TOOL_CALLS`、`MODEL_ERROR` 和 `CANCELLED`。模型错误不会泄露 Prompt；工具异常正文不会直接回送模型。
