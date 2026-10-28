# Agent runtime and ReAct loop

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./agents.md)

a7 (2.0.0a7, focused regressions passed) adds `AgentDefinition.emit_tool_results` and `max_tool_result_event_bytes`. Recording is off by default; explicit opt-in lets `TOOL_COMPLETED` carry bounded model-visible results through a replaceable encoder. Approval tickets are excluded and encoding failure marks status without retrying effects. See [tool-result recording and independent replay disclosure](./event-replay.en.md).

The a6 release (focused regressions passed) adds optional tool continuation. `ToolContinuation` lets ReAct persist unfinished-tool references and wait for explicit authority. Ticket-bearing checkpoints use schema 2; ordinary checkpoints retain schema 1. Resume uses only the separate continuation handler, never restarting the tool or replaying the preceding model call. Uncertain execution retains `RESUMING`. The a6 release also provides the reference-first `resumable_workflow_tool()` bridge; two-layer approval coordination services are now in the a6 release (focused regressions passed), while UI guidance is also present in the a6 release (focused regressions passed). See [tool continuation](./tools.en.md).

Status: public `AgentLoop`/run contracts, a bounded single-agent `ReactAgentLoop`, token/cost budgets, an append-only local RunStore, post-approval resume, the local session lifecycle, and application-level live-event callbacks are `Implemented` in Phase 3 / since `2.0.0a3`. The `2.0.0a4` release adds cursor-paged reading of persisted RunEvents, replaceable JSON redaction projection, explicit tool-argument deltas, and explicit image/audio output projection; general new modalities remain `Planned`, and multi-agent orchestration is `Reserved`.

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

# An explicit local heuristic template; production may inject an exact tokenizer.
estimator = CharacterTokenEstimator(characters_per_token=4)
# loop = ReactAgentLoop(..., token_estimator=estimator)
```

## Events and results

`stream()` returns a single-use `ReactAgentExecution` that yields `RUN_STARTED`, model-phase, tool-phase, and `RUN_COMPLETED` events. Its final result is available as `execution.result`. `run()` is the convenience method that consumes these events. Each event is appended to `RunStore` before it becomes visible to the caller.

`InMemoryRunStore` serves tests and short-lived local runs. `JsonlRunStore` uses an append-only `events.jsonl` plus atomically replaced `checkpoint.json` per run and can be reopened by a new process or loop instance. `list_checkpoints()` returns `RunCheckpointSummary` values containing recovery identity, argument names, and metering but no prompts, argument values, outputs, or credentials. Event sequences must be contiguous; unknown schema versions and corrupt logs fail closed. In the `2.0.0a4` release, JSONL append also checks lines through the target sequence instead of materializing the full log for every write; it remains a linear scan, and an index may be added later.

The a6 release adds `RunEventReplay`, `RunEventCursor`, and `RunEventPage`. An application can reopen the same `JsonlRunStore` in a new process and page through persisted events using a sequence cursor bound to one run ID. The reader accepts either the minimal `RunEventSource.events()` contract or the optional `PagedRunEventSource.events_page()` capability. Built-in memory and JSONL stores implement bounded paging: JSONL scans lines through the requested page and one lookahead record, so memory grows with page size rather than the entire log. Existing custom stores need no changes and continue through the `events()` fallback. JSONL has no random-access index, so later pages still scan the prefix; corruption beyond a returned page is discovered when the cursor reaches it. `has_more` describes only the log snapshot at read time; a running client may read again from `next_cursor`. This read-only retrieval does not re-execute a model, tool, or approval and does not restore an arbitrary runtime stack. The API has passed focused regressions; raw paging does not decide content disclosure by itself.

The same worktree adds `RunEventProjector`, `SafeRunEventProjector`, and `ProjectedRunEventPage`. `RunEventReplay.projected_page()` defaults to a content-free safe projector and lets an application explicitly supply its own projector after it has already been granted read access to the raw store. Projected output must be a bounded-depth, finite-number JSON-compatible object with string keys; projector exceptions, non-object results, and arbitrary Python objects fail closed. CLI `wagent run-events` and the TUI Checkpoints screen request safe projected pages directly, retaining only type- or enum-constrained counts, status, and cost summaries. Model text, tool arguments/results, raw exceptions, and arbitrary metadata never enter those interfaces. The raw `page()` API remains for compatibility, and its `RunEventPage.events` may contain sensitive content, so local applications must control read authority themselves. A custom projector is not a security sandbox; the framework cannot decide which business fields an application may disclose.

`FieldPolicyRunEventProjector` is a default-deny template that needs no projector code. `RunEventFieldPolicy(include=(...), mask=(...), mask_value="***")` selects only top-level `RunEvent.data` fields. An exact event-type rule wins, and `"*"` is only a fallback when no exact rule exists. Unlisted fields are removed. Include/mask overlap, duplicate fields, unknown event types, and invalid masks are rejected at construction.

`NestedFieldRunEventProjector` applies the same default-deny approach to nested JSON data. Each `RunEventPathRule` uses string keys/non-negative array indexes for its source, a string-only target path that constructs an output object, and either `COPY` or fixed `MASK`; a different target path performs renaming. Missing sources are skipped, while duplicate or parent/child target collisions are rejected at construction. Copying an object/array node copies its complete subtree, so an already-authorized application must still configure rules explicitly. Arbitrary computation, conditional logic, and business authorization belong in a custom projector.

Image/audio output uses a separate explicit path. Only `AgentDefinition.emit_output_blocks=True` invokes the replaceable `ModelOutputEventEncoder`. The default `StandardMultimodalEventEncoder` handles provider-neutral `ImageContent`/`AudioContent` only, performs no URL I/O, caps inline data at 8 MiB, and records Base64, byte count, and SHA-256. It does not disclose text or tool blocks as a side effect. Each encoded block is persisted as `MODEL_OUTPUT_BLOCK` before `MODEL_COMPLETED`; the flag and content survive approval checkpoints. A standard encoding failure emits `MODEL_OUTPUT_BLOCK_FAILED` without an exception body and stops as `OUTPUT_EVENT_ERROR` before tool execution while preserving known usage. Applications may replace the encoder to externalize content into their own blob store or support new modalities.

`MultimodalRunEventProjector` defaults to `metadata`: it exposes modality, source kind, media type, and inline size/digest, but no URL or body. `references` may expose URLs while still hiding inline bodies, and only `content` returns the recorded URL or Base64. All modes verify standard inline size and digest. Other events go to a replaceable fallback, which defaults to `SafeRunEventProjector`. This is a disclosure template, not application authorization.

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

Run events contain model text, tool arguments, and result-stage information needed to reconstruct model context, so callers must treat them as potentially sensitive local run content. Tool audit is separate and stores only minimal metadata such as argument names. The current store does not encrypt content; filesystem access control belongs to the local application.

`MODEL_COMPLETED` exposes response tokens, a per-attempt ledger, and `attempt_usage_complete`; failed model stages also record prompt-free, credential-free attempt summaries. The following `TOKEN_USAGE` event exposes known run totals. `RunResult.attempts` carries the typed complete ledger, `RunResult.usage` carries cumulative known usage, and `usage_complete` reports whether every attempt, including retry and failover, supplied provider usage. A real zero-token report is not confused with missing metadata.

Hard token budgets reconcile every provider-reported attempt after a successful response and stop with `TOKEN_BUDGET` before executing tool calls from a response that exceeded a limit. Remaining output/total allowance also tightens the next request's output cap. Applications may inject an asynchronous `TokenEstimator` into `ReactAgentLoop`; its pre-call `TokenEstimate` checks cumulative input/total limits and subtracts estimated input from the total allowance before tightening the output cap. `require_estimate=True` fails closed as `TOKEN_ESTIMATE_UNAVAILABLE` when the estimator is missing, fails, or returns an invalid result. Otherwise a `TOKEN_ESTIMATE_UNAVAILABLE` event makes the degradation visible while execution continues. `soft_limit_ratio` emits `TOKEN_BUDGET_WARNING` only and never silently changes the stop policy. `TOKEN_ESTIMATED` contains counts, estimator identity, and exactness but no prompt.

The built-in `CharacterTokenEstimator` counts neutral-message text, tool calls/results, tool and response schemas, and stop strings. It explicitly reports `exact=False`, rejects image/audio input, and does not claim to include hidden vendor framing. Applications can replace it with a model-specific tokenizer. An estimate protects only the next initial request; it cannot predict retries/failover or final provider accounting, so actual usage is always reconciled afterward. With `require_usage=True`, any unreported attempt—including a failed attempt before a successful retry—stops the run with `TOKEN_USAGE_UNAVAILABLE`.

Cost metering uses an application-supplied `PriceTable`/`PricingResolver` and exact provider, model, table version, and currency identities. Normal input, cached input, and output costs use `Decimal`. `CostBudget` binds a run to one explicit table version, and `RunResult.cost_complete` becomes true only when every attempt was priced. An over-limit response stops with `COST_BUDGET` before its tools execute. Missing rates or usage and version/currency mismatches fail closed as `COST_UNAVAILABLE`. Cost and table identity flow through `COST_USAGE`, terminal events, results, sessions, and approval checkpoints so resumed runs continue the same ledger. The framework bundles no potentially stale vendor prices and never silently infers money from token counts.

`CostBudget(estimate_before_call=True)` explicitly enables pre-call cost estimation. A replaceable `CostEstimator` receives a prompt-free `CostEstimateRequest`; the default `PricingCostEstimator` builds a `CostEstimate` from the selected routes, allowed retry/failover counts, the input-token estimate, and that request's output cap. `COST_ESTIMATED` exposes both the preferred single-attempt cost and full replay envelope, `COST_ESTIMATE_UNAVAILABLE` exposes degradation, `require_estimate=True` can stop as `COST_ESTIMATE_UNAVAILABLE` when projection is unavailable, and `soft_limit_ratio` emits `COST_BUDGET_WARNING`. An envelope beyond remaining budget stops before the model-generation request, while provider-reported usage is always reconciled again afterward. Session totals, per-attempt ledgers, pre-call token/cost estimation, soft-threshold events, and read-only per-agent cross-session usage/cost summaries are implemented.

`emit_text_deltas=False` is the compatibility default. The `2.0.0a4` release adds a separate `emit_tool_call_deltas=False` flag. Enabling either uses `ModelExecutor.stream()` and persists/yields `MODEL_TEXT_DELTA` (text) or `MODEL_TOOL_CALL_DELTA` (`step`, `block_index`, `call_id`, `name`, `arguments_delta`) before `MODEL_COMPLETED`. Enabling text streaming does not implicitly expose tool arguments. With both flags disabled, ReAct keeps collecting `invoke()`. Final `RunResult`, usage, attempt ledger, and tool-loop semantics stay unchanged; a failure after visible output is not silently hidden by ordinary retry/failover. Applications may explicitly assemble `ReactAgentLoop(..., stream_recovery=NativeCursorRecovery(max_resumes=2))` or inject a verified-text-prefix strategy; recovery applies only in streaming mode. Pre-call cost estimation includes the allowed extra resume/replay connections for each route; failed attempts without provider-reported usage remain unknown and estimates do not replace settlement. Raw tool deltas and explicitly recorded media blocks may contain sensitive content and are persisted by the JSONL store. The default CLI/TUI projection shows only safe counts and status, never call IDs, tool names, arguments, media URLs, or inline bodies. Bundled vendor-native continuation adapters remain later work.

## Initial templates

`customer_support_agent()` and `coding_agent()` build ordinary `AgentDefinition` values. Their `CUSTOMER_SUPPORT_AGENT_TEMPLATE` / `CODING_AGENT_TEMPLATE` objects expose recommended tool names and defaults. Every definition field can be replaced through `build()`, and callers may ignore the templates entirely.

Templates bind no provider, register or hide no tool, and grant no permission, approval, or local-execution authority. The support template recommends evidence search, customer/ticket reads, and approval-gated writes. The coding template recommends workspace operations and `sandbox_command`. Applications still register tools, configure scope and authority, and choose Docker isolation or the explicitly authorized local development mode for code execution.

## Approval and stopping

When policy requires approval, the loop saves `RunCheckpoint` before invoking the handler. In the a6 release, a handler may also return a typed `ToolContinuation` after preparing unfinished work; this produces `NEEDS_APPROVAL` with a persisted continuation ticket. Neither path sends a denial or a successful tool result to the model. The loop returns `StopReason.NEEDS_APPROVAL` with `pending_tool_call` and `checkpoint_id`. Approval can come only from `ToolExecutionContext.approved_call_ids` supplied by the local application; model output cannot authorize itself.

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

Checkpoints store neither permissions nor approval credentials; the local application must provide them again. `SessionManager` now provides listing, archival, cross-run text conversation projection, and approval-resume coordination. The a6 release adds [accumulated event snapshots](./event-replay.en.md) (focused regressions passed). Optional tool-result recording is available in a7 (2.0.0a7, focused regressions passed); read-only Replay UI is available in a7; dedicated media rendering remains Planned; arbitrary-position execution recovery is outside this replay capability. See [Session lifecycle and cross-run context](./sessions.en.md).

Other stop reasons include `MAX_STEPS`, `MAX_TOOL_CALLS`, `TOKEN_BUDGET`, `TOKEN_USAGE_UNAVAILABLE`, `COST_BUDGET`, `COST_UNAVAILABLE`, `MODEL_ERROR`, and `CANCELLED`. Model failures expose no prompt, and tool exception text is not sent directly back to the model.
