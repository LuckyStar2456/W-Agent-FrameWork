# Agent runtime and ReAct loop

English | [简体中文](./agents.md)

Status: public `AgentLoop`/run contracts, a bounded single-agent `ReactAgentLoop`, an append-only local RunStore, and post-approval resume are `Implemented` in Phase 3 / `2.0.0a1`. Full session lifecycle, general replay, and multi-agent orchestration remain `Planned` or `Reserved`.

## Layers

```text
AgentDefinition + RunContext
              ↓
AgentLoop (replaceable as a whole)
   ├── ModelExecutor
   ├── ToolRegistry
   └── ToolExecutorProtocol
              ↓
RunEvent* → RunStore → RunResult / RunCheckpoint
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

`stream()` returns a single-use `ReactAgentExecution` that yields `RUN_STARTED`, model-phase, tool-phase, and `RUN_COMPLETED` events. Its final result is available as `execution.result`. `run()` is the convenience method that consumes these events. Each event is appended to `RunStore` before it becomes visible to the caller.

`InMemoryRunStore` serves tests and short-lived local runs. `JsonlRunStore` uses an append-only `events.jsonl` plus atomically replaced `checkpoint.json` per run and can be reopened by a new process or loop instance. Event sequences must be contiguous; unknown schema versions and corrupt logs fail closed.

Run events contain model text, tool arguments, and result-stage information needed to reconstruct model context, so callers must treat them as potentially sensitive local run content. Tool audit is separate and stores only minimal metadata such as argument names. The current store does not encrypt content; filesystem access control belongs to the local application.

The current ReAct template uses the model executor's collecting `invoke()` method, so run events do not yet contain token deltas. The model layer already supports safe pass-through; adapting those events into agent RunEvents is later work.

## Approval and stopping

When a tool returns `NEEDS_APPROVAL`, the loop does not execute it or send a denial to the model. It saves `RunCheckpoint` and returns `StopReason.NEEDS_APPROVAL` with `pending_tool_call` and `checkpoint_id`. Approval can come only from `ToolExecutionContext.approved_call_ids` supplied by the local application; model output cannot authorize itself.

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

Resume executes the original pending call and remaining calls from the same model response, then enters the next model step without repeating the pre-approval model request. A checkpoint is atomically claimed before a side effect runs. If the process exits before its result is durably known, status remains `RESUMING`; a later attempt raises `RunResumeConflictError` for manual reconciliation instead of silently duplicating the effect. Missing approval returns the checkpoint to `PENDING_APPROVAL`.

Checkpoints store neither permissions nor approval credentials; the local application must provide them again. Full session listing/archival, cross-run conversation projections, and arbitrary-position recovery remain `Planned`.

Other stop reasons include `MAX_STEPS`, `MAX_TOOL_CALLS`, `MODEL_ERROR`, and `CANCELLED`. Model failures expose no prompt, and tool exception text is not sent directly back to the model.
