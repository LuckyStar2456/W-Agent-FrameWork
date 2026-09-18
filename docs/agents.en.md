# Agent runtime and ReAct loop

English | [简体中文](./agents.md)

Status: public `AgentLoop`/run contracts, a bounded single-agent `ReactAgentLoop`, token/cost budgets, an append-only local RunStore, post-approval resume, the local session lifecycle, and application-level live-event callbacks are `Implemented` in Phase 3 / current `2.0.0a3`. General event replay and multi-agent orchestration remain `Planned` or `Reserved`.

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

`max_steps` and `max_tool_calls` are enforced budgets. `max_output_tokens` caps one model request; cumulative limits use a separate `TokenBudget` to keep those meanings distinct. The current template executes tool calls from one model response sequentially. It neither parallelizes nor retries tools automatically.

```python
from w_agent import AgentDefinition, CharacterTokenEstimator, TokenBudget

definition = AgentDefinition(
    "assistant",
    max_output_tokens=2_000,
    token_budget=TokenBudget(
        max_input_tokens=20_000,
        max_output_tokens=6_000,
        max_total_tokens=24_000,
        require_usage=True,
        require_estimate=True,
        soft_limit_ratio="0.8",
    ),
)

# An explicit local heuristic template; production may inject an exact tokenizer.
estimator = CharacterTokenEstimator(characters_per_token=4)
# loop = ReactAgentLoop(..., token_estimator=estimator)
```

## Events and results

`stream()` returns a single-use `ReactAgentExecution` that yields `RUN_STARTED`, model-phase, tool-phase, and `RUN_COMPLETED` events. Its final result is available as `execution.result`. `run()` is the convenience method that consumes these events. Each event is appended to `RunStore` before it becomes visible to the caller.

`InMemoryRunStore` serves tests and short-lived local runs. `JsonlRunStore` uses an append-only `events.jsonl` plus atomically replaced `checkpoint.json` per run and can be reopened by a new process or loop instance. `list_checkpoints()` returns `RunCheckpointSummary` values containing recovery identity, argument names, and metering but no prompts, argument values, outputs, or credentials. Event sequences must be contiguous; unknown schema versions and corrupt logs fail closed.

Run events contain model text, tool arguments, and result-stage information needed to reconstruct model context, so callers must treat them as potentially sensitive local run content. Tool audit is separate and stores only minimal metadata such as argument names. The current store does not encrypt content; filesystem access control belongs to the local application.

`MODEL_COMPLETED` exposes response tokens, a per-attempt ledger, and `attempt_usage_complete`; failed model stages also record prompt-free, credential-free attempt summaries. The following `TOKEN_USAGE` event exposes known run totals. `RunResult.attempts` carries the typed complete ledger, `RunResult.usage` carries cumulative known usage, and `usage_complete` reports whether every attempt, including retry and failover, supplied provider usage. A real zero-token report is not confused with missing metadata.

Hard token budgets reconcile every provider-reported attempt after a successful response and stop with `TOKEN_BUDGET` before executing tool calls from a response that exceeded a limit. Remaining output/total allowance also tightens the next request's output cap. Applications may inject an asynchronous `TokenEstimator` into `ReactAgentLoop`; its pre-call `TokenEstimate` checks cumulative input/total limits and subtracts estimated input from the total allowance before tightening the output cap. `require_estimate=True` fails closed as `TOKEN_ESTIMATE_UNAVAILABLE` when the estimator is missing, fails, or returns an invalid result. Otherwise a `TOKEN_ESTIMATE_UNAVAILABLE` event makes the degradation visible while execution continues. `soft_limit_ratio` emits `TOKEN_BUDGET_WARNING` only and never silently changes the stop policy. `TOKEN_ESTIMATED` contains counts, estimator identity, and exactness but no prompt.

The built-in `CharacterTokenEstimator` counts neutral-message text, tool calls/results, tool and response schemas, and stop strings. It explicitly reports `exact=False`, rejects image/audio input, and does not claim to include hidden vendor framing. Applications can replace it with a model-specific tokenizer. An estimate protects only the next initial request; it cannot predict retries/failover or final provider accounting, so actual usage is always reconciled afterward. With `require_usage=True`, any unreported attempt—including a failed attempt before a successful retry—stops the run with `TOKEN_USAGE_UNAVAILABLE`.

Cost metering uses an application-supplied `PriceTable`/`PricingResolver` and exact provider, model, table version, and currency identities. Normal input, cached input, and output costs use `Decimal`. `CostBudget` binds a run to one explicit table version, and `RunResult.cost_complete` becomes true only when every attempt was priced. An over-limit response stops with `COST_BUDGET` before its tools execute. Missing rates or usage and version/currency mismatches fail closed as `COST_UNAVAILABLE`. Cost and table identity flow through `COST_USAGE`, terminal events, results, sessions, and approval checkpoints so resumed runs continue the same ledger. The framework bundles no potentially stale vendor prices and never silently infers money from token counts. Session totals, per-attempt ledgers, pre-call token estimation, and soft-threshold events are implemented; cross-session agent aggregation and pre-call monetary estimation remain planned.

The current ReAct template uses the model executor's collecting `invoke()` method, so run events do not yet contain per-token text deltas. The model layer already supports safe pass-through; adapting text deltas into agent RunEvents is later work.

## Initial templates

`customer_support_agent()` and `coding_agent()` build ordinary `AgentDefinition` values. Their `CUSTOMER_SUPPORT_AGENT_TEMPLATE` / `CODING_AGENT_TEMPLATE` objects expose recommended tool names and defaults. Every definition field can be replaced through `build()`, and callers may ignore the templates entirely.

Templates bind no provider, register or hide no tool, and grant no permission, approval, or local-execution authority. The support template recommends evidence search, customer/ticket reads, and approval-gated writes. The coding template recommends workspace operations and `sandbox_command`. Applications still register tools, configure scope and authority, and choose Docker isolation or the explicitly authorized local development mode for code execution.

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

Checkpoints store neither permissions nor approval credentials; the local application must provide them again. `SessionManager` now provides listing, archival, cross-run text conversation projection, and approval-resume coordination. General multimodal/tool event replay and arbitrary-position recovery remain `Planned`. See [Session lifecycle and cross-run context](./sessions.en.md).

Other stop reasons include `MAX_STEPS`, `MAX_TOOL_CALLS`, `TOKEN_BUDGET`, `TOKEN_USAGE_UNAVAILABLE`, `COST_BUDGET`, `COST_UNAVAILABLE`, `MODEL_ERROR`, and `CANCELLED`. Model failures expose no prompt, and tool exception text is not sent directly back to the model.
