# Agent Runtime 与 ReAct Loop

[English](./agents.en.md) | 简体中文

状态：公开 `AgentLoop`/Run 协议、有界单 Agent `ReactAgentLoop`、追加式本地 RunStore 和审批后恢复为 `Implemented`（Phase 3 / `2.0.0a1`）。完整 Session 生命周期、通用回放和多 Agent 编排仍为 `Planned` 或 `Reserved`。

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

`max_steps` 和 `max_tool_calls` 是强制预算。当前模板按顺序执行同一模型响应中的工具调用，不自动并行，也不重试工具。

## 事件和结果

`stream()` 返回单次消费的 `ReactAgentExecution`，依次输出 `RUN_STARTED`、模型阶段、工具阶段和 `RUN_COMPLETED` 事件；结束后从 `execution.result` 读取最终结果。`run()` 是收集这些事件的便利方法。事件在向调用者暴露前先写入 `RunStore`。

`InMemoryRunStore` 适用于测试和短期本地运行；`JsonlRunStore` 对每个 Run 使用追加式 `events.jsonl` 和原子替换的 `checkpoint.json`，在新进程/新 Loop 实例中可重新读取。事件序号必须连续，未知 Schema 版本或损坏日志会失败关闭。

Run 事件包含重建模型上下文所需的模型文本、工具参数和结果阶段信息，因此调用者必须把它们视为可能含敏感数据的本地运行内容。工具审计是另一条记录，只保存参数名等最小元数据。当前 Store 不负责加密，保存目录的访问控制由本地应用负责。

当前 ReAct 使用模型执行器的收集式 `invoke()`，所以 Run 事件尚不包含逐 Token 增量。模型层本身已经支持安全透传，接入 Agent RunEvent 是后续工作。

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

Checkpoint 不保存权限或批准凭据。恢复时必须由本地应用重新提供。完整 Session 列表、归档、跨 Run 对话投影和任意位置恢复仍为 `Planned`。

其他停止原因包括 `MAX_STEPS`、`MAX_TOOL_CALLS`、`MODEL_ERROR` 和 `CANCELLED`。模型错误不会泄露 Prompt；工具异常正文不会直接回送模型。
