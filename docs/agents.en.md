# Agent runtime and ReAct loop

English | [简体中文](./agents.md)

Status: the public `AgentLoop`/run contracts, a single-use run-event stream, and a bounded single-agent `ReactAgentLoop` are `Implemented` in Phase 3 / `2.0.0a1`. Durable sessions, event storage, post-approval resume, and multi-agent orchestration remain `Planned` or `Reserved`.

## Layers

```text
AgentDefinition + RunContext
              ↓
AgentLoop (replaceable as a whole)
   ├── ModelExecutor
   ├── ToolRegistry
   └── ToolExecutorProtocol
              ↓
RunEvent* → RunResult
```

`ReactAgentLoop` is an ordinary first-party implementation with no microkernel privileges. Developers can replace the complete reasoning path through the same `AgentLoop` protocol, or independently replace model routing, model execution, the tool catalog, tool policy, or tool executor.

## Current loop

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
    (ModelMessage.text(MessageRole.USER, "calculate 2 + 3"),),
)
result = await loop.run(AgentDefinition("assistant"), context)
```

Each step:

1. Reads model-visible tool definitions from the current scope.
2. Executes one routed model request through `ModelExecutor.invoke()`.
3. Returns final text with `COMPLETED` when no tool call exists.
4. Parses tool-call JSON and delegates it to `ToolExecutorProtocol`.
5. Sends both successful and failed results back as `ToolResultContent`, then starts the next step.

`max_steps` and `max_tool_calls` are enforced budgets. The current template executes tool calls from one model response sequentially. It neither parallelizes nor retries tools automatically.

## Events and results

`stream()` returns a single-use `ReactAgentExecution` that yields `RUN_STARTED`, model-phase, tool-phase, and `RUN_COMPLETED` events. Its final result is available as `execution.result`. `run()` is the convenience method that consumes these events.

Run events contain model text, tool arguments, and result-stage information needed to reconstruct this in-process model context, so callers must treat them as potentially sensitive run content. Tool audit is separate and stores only minimal metadata such as argument names.

The current ReAct template uses the model executor's collecting `invoke()` method, so run events do not yet contain token deltas. The model layer already supports safe pass-through; adapting those events into agent RunEvents is later work.

## Approval and stopping

When a tool returns `NEEDS_APPROVAL`, the loop does not execute it or send a denial to the model. It returns `StopReason.NEEDS_APPROVAL` with `pending_tool_call`. Approval can come only from `ToolExecutionContext.approved_call_ids` supplied by the local application; model output cannot authorize itself.

There is no durable resume handle yet. A caller can grant approval in a new run, but true continuation from the same event position remains `Planned`; rerunning must not be described as resume.

Other stop reasons include `MAX_STEPS`, `MAX_TOOL_CALLS`, `MODEL_ERROR`, and `CANCELLED`. Model failures expose no prompt, and tool exception text is not sent directly back to the model.
