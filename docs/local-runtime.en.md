# Locally configured agent runtime

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./local-runtime.md)

Unpublished M4 recommends `async with open_local_runtime(config, ...) as runtime`, passing the `compile_local_runtime()` component plan to `ApplicationHost`. CLI/TUI use this path, with pre-start replacement of Loops, routers, executors and stores. The synchronous `assemble_local_runtime()` retains basic compatibility without silently changing its lifecycle semantics. See [default assembly](./default-assembly.en.md).

The worktree [`knowledge_search_tool`](./knowledge-tools.en.md) returns ordinary bindings selected through `tools.enabled` and host `tool_bindings`, reusing CLI `--tool-entry` / `--confirm-tool-code` and TUI `LOAD TOOLS`. Defaults require `knowledge.read` and external-call approval; JSON neither imports nor grants permissions automatically. Local implementation/wiring regressions pass and outside a9; this is not dedicated retrieval configuration UI.

The framework provides a [knowledge-body context policy](./knowledge-context.en.md). Direct `history_policy=AsyncKnowledgeContextPolicy(query, retriever)` still skips the entire policy with `include_history=False`. Separate [named knowledge assembly](./knowledge-runtime.en.md) selects a host catalog via JSON knowledge.binding, with per-call query confirmation and independent CLI/TUI run code/query consent. This explicit path can retrieve knowledge without history, including empty Sessions; checkpoint resume never requeries. Text-only composition, passing local implementation/tests and outside a9.

The framework provides a [read-only Qdrant history selector](./vector-retrieval.en.md), injected by Python hosts through `AsyncRetrievedSessionHistoryPolicy` and `history_policy`. It is not loaded from configuration or wired to CLI/TUI; hosts still own indexing and embedding/retrieval costs. Included in 2.0.0, with local regressions passing and not part of a9.

Hosts may separately use the new [explicit index preparation/write](./vector-indexing.en.md) source. Runtime never calls these side-effect stages automatically; query consent does not authorize history-body embedding or overwrites. These additions are also included in 2.0.0 with local regressions passing.

a9 shared budgets support named Runtime/Provider assembly bindings: JSON selects a host-supplied controller/meter binding and assembly wraps the configured Provider. Memory and explicitly initialized SQLite controllers are supported. CLI run/run-resume/evaluate/provider-probe and TUI Run/approval-resume/evaluation/probes now support independently confirmed budget factories and pool summaries. Existing Run budgets and Session statistics remain unchanged. 2.0.0a9 Experimental; see a9 release notes for validation; see below and [shared budgets](./shared-budget.en.md).

The a9 SQLite summary observer can be explicitly assembled by Python hosts; it neither creates a Runtime database automatically nor wires into CLI/TUI. Its `snapshot(run.result)` reuses explicit aggregation. 2.0.0a9 Experimental; see a9 release notes for validation; see [durable accounting](./context-accounting.en.md).

a8/a9 additions on this page are Experimental; see [a9 release notes](./releases/2.0.0a9.en.md) for validation scope.

a8 addition (2.0.0a8 Experimental; focused regressions passed): Python `run()` / `run_messages()` now accept `AsyncSessionHistoryPolicy` through `history_policy`. Runtime awaits preparation before the main Agent loop and supports cancellation; async retrieval/summary templates require host-injected trusted callbacks. CLI/TUI built-in selections remain local synchronous policies and do not automatically contact external services. Preparation tokens/costs are outside the main Run budget and need separate host authorization/accounting; see [Session async preparation](./sessions.en.md).

`AgentSessionHistorySummarizer` now provides an independent summary-Run adapter, reusing its assembled Loop's budgets/accounting and reporting started/terminal states and Usage completeness through a required observer; likewise 2.0.0a8 Experimental with focused regressions passing. Assemble a dedicated empty tool catalog and any required PricingResolver, rather than directly reusing a Runtime Loop with business tools. Main Session totals do not automatically include these Session-unbound summary Runs.

a8 `InMemorySessionSummaryObserver.snapshot(run.result)` explicitly combines those summary reports with the current Runtime main result without changing the original result or Session statistics. Without a main result it returns known partial consumption with incomplete flags; see [aggregation](./context-accounting.en.md). Automatic CLI/TUI aggregation remains planned; explicit shared pre-call reservations are provided separately in a9.

a7 addition (2.0.0a7, focused regressions passed): `agent.emit_tool_results=true` explicitly records model-visible tool-result bodies. `agent.max_tool_result_event_bytes` defaults to 65536 and limits the complete result object's JSON UTF-8 bytes. Recording is off by default and excludes approval tickets; encoding failures emit fixed status without tool retries. Python assembly accepts `tool_result_event_encoder`; JSON configuration never imports code. Resume retains checkpoint flags/limits, while hosts re-inject the encoder. Reprovide the same custom redaction policy after restart when consistency is required. The base example below remains a6-compatible; the two new fields require a7 or later. See [event recording and disclosure](./event-replay.en.md).

Status: `Experimental`. `2.0.0a3` includes strict local JSON configuration, environment-variable credential references, provider/routing/ReAct assembly, versioned pricing and cost budgets, provider-only assembly and probing, explicit tool selection, persistent runs/sessions, Python API/CLI/TUI approval resume, prompt-free agent-checkpoint listing, application event callbacks, and CLI/TUI text-run entry points. `2.0.0a4` additionally implements explicit pre-call cost estimation/replay envelopes plus privacy-safe workflow-checkpoint discovery and explicit recovery.

## Named shared-budget bindings (2.0.0a9 Experimental)

Configuration gains an optional reference. Without a selection, behavior is unchanged; merely supplying a host catalog does not enable budgets:

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
# The host supplies host_meter.bound/actual with bounds valid for the selected Provider.
bindings = {"development": LocalSharedBudgetBinding(ledger, host_meter)}
config = load_local_runtime_config("runtime.json")  # The configuration above.
async with assemble_local_runtime(config, shared_budget_bindings=bindings) as runtime:
    result = await runtime.run("Start the task")  # Only after host authorization for model access.
    pool = await runtime.shared_budget_snapshot()
    # result.result.usage belongs to this Run; pool.known_usage/held_usage cover the shared pool.
```

Boundaries and lifecycle:

- `LocalSharedBudgetConfig(binding=...)` accepts only a 1–128-character opaque name. JSON cannot supply paths, limits, code imports, keys or reconciliation authority. `LocalSharedBudgetBinding(controller, meter)` is a host Python object; its components follow the public protocols and need not be built-in memory/SQLite implementations.
- Both `assemble_local_runtime()` and `assemble_local_provider()` accept `shared_budget_bindings`. Missing or mistyped selected bindings fail before Provider construction, without falling back to unmetered Providers. Unselected catalog objects are not accessed. A shared-budget selection requires an explicit strictly positive integer `agent.max_output_tokens`; character estimates are not promoted to reliable upper bounds.
- Hosts own the controller/meter. Assembly never calls initialize, snapshot, metering or close methods on them. Explicitly `await ledger.initialize()` for SQLite; Runtime does not initialize it or substitute memory after storage errors. Multiple SQLite objects must use the same file, budget_id and configuration; distinct IDs do not share allowance.
- Assembly retains ownership of the original Provider. Closing Runtime or ProviderAssembly closes its original client even though the budget wrapper has no `aclose()`. Repeated closure is idempotent; borrowed controllers/meters are not closed. Runtime still closes closable registered Providers, deduplicating by object identity. Closing does not drain active calls: hosts must cancel/wait for active tasks first. Internals of additional custom wrappers remain the host's responsibility.
- `runtime.shared_budget` / `provider_assembly.shared_budget` expose the selected binding. `runtime.shared_budget_snapshot()` explicitly reads the pool, returns `None` when unselected, and fails with a fixed error if a custom controller lacks snapshot support. Reads neither persist nor invoke models, and do not attribute a pool to one Run/Session. Do not add pool totals to the usage of Runs already included in that pool.
- Summary and main Runtimes may select the same binding; different Providers can use different meters backed by one controller. Give summaries a dedicated empty tool catalog, supply that Loop/Definition to `AgentSessionHistorySummarizer`, and connect it through `AsyncSummarizedSessionHistoryPolicy`. The budget covers summary preparation and subsequent main calls, while summary reports, main Run and Session statistics remain distinct. Custom preparation callbacks using separate unwrapped Providers are not automatically counted.
- Admission failures follow the existing Provider-error `MODEL_ERROR` stop path, not a successful invocation or a Run-local budget stop reason. Unknown charges are not automatically retried. Native cursor forwarding is unsupported: selecting shared budgets with `NativeCursorRecovery` fails before assembly. Later host changes to the public registry, Loop or binding can change or bypass coverage; hosts must keep every generation route wrapped.
- CLI run/run-resume/evaluate/provider-probe and TUI Run/approval-resume/evaluation/probes can explicitly load a budget factory as described below. Evaluation and configured Provider probes use the same explicit factory options; missing bindings are rejected instead of ignoring budgets. Separately opt into the [cross-service durable ledger](./service-usage-runtime.en.md) and [Run/Session links](./service-usage-links.en.md). Links do not turn host-operation totals into exact per-Run usage, and these entry points never reconcile automatically.

Regression source covers opt-out compatibility, shared multi-Run budgets, the summary/main Runtime chain, SQLite missing initialization/reopening, no retries for unknown charges, optional snapshots and client closure. See a9 release notes for focused verification; no live model requests were run.

### CLI/TUI budget factories and pool display (2.0.0a9 Experimental)

Keep `"shared_budget": {"binding": "development"}` in configuration. CLI separately selects the factory and confirms code execution:

```text
wagent run "Start the task" --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
wagent run-resume SESSION RUN --approve-tool-call CALL --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
```

Factories are **trusted, unsandboxed host Python**, not Agent tools or plugin authority. `--confirm-budget-code` is independent of model access, tool-code loading, tool permissions and exact Call ID approval. No confirmation means no loading. The framework neither edits sys.path, installs dependencies nor imports code from JSON. Put modules on the normal Python import path; only `module:factory` references are accepted, not file paths.

```python
# my_budget.py: the host must implement reliable bounds/pricing, not character estimates.
from contextlib import asynccontextmanager
from w_agent import SQLiteSharedBudget, SharedBudgetLimits, LocalSharedBudgetBinding
from application_pricing import meter

@asynccontextmanager
async def open_budgets():
    ledger = SQLiteSharedBudget("./shared-budget.db", "development-v1",
                                SharedBudgetLimits(max_total_tokens=50000))
    await ledger.initialize()  # Explicit host initialization, not hidden assembler writes.
    try:
        yield {"development": LocalSharedBudgetBinding(ledger, meter)}
    finally:
        pass  # Close external resources created here; SQLite has no persistent connection.
```

The zero-argument factory returns an async context manager yielding 1–64 named `LocalSharedBudgetBinding` objects, including the configured selection. Plain dicts, coroutine-returning async factories, missing selections and invalid types fail closed. Setup/cleanup and Runtime use share one event loop; cleanup follows model-client closure. A context's exit return value cannot suppress Runtime errors. Completed setup writes are not automatically rolled back if later assembly fails. Hosts must clean partially acquired resources when setup fails/is cancelled before yielding. Synchronous imports/factory creation may block UI: keep them small and put async preparation inside the context.

CLI adds `shared_budget` to the existing result; TUI uses a separate panel. Fields show input/output/cached/total tokens for `known_usage` and `held_usage`, known/held costs, limits, four ticket-status counts and blocked/breached. This is a read-time snapshot of the entire pool, not this Run or Session usage that can be added again. blocked=false does not guarantee sufficient allowance. Ticket IDs, price versions, evidence and actor references are omitted. Without a selected budget, CLI omits the field and TUI displays disabled.

A post-Run snapshot failure displays `status=unavailable`, without fabricated zero usage, changed Run results or model replay. Host cleanup can fail after a model already ran; inspect the ledger instead of retrying generation. Cancellation does not imply refunds, and repeated cancellation can interrupt host cleanup. Cross-process CLI invocations/resumes need a shared durable pool: a newly created memory controller on each invocation is not cumulative accounting. Memory covers only the lifetime of that factory object.

TUI Run and Checkpoints add a budget factory field and per-attempt `LOAD BUDGET`. `RUN`/`RESUME` and other confirmations remain independent. Run captures/locks the entry at startup and consumes budget confirmation with other confirmations; approval resume also consumes budget confirmation. No automatic reconciliation, periodic refresh or evidence-read button is added.

Evaluation and configured Provider probes accept the same factory options:

```text
wagent evaluate builtin:customer-support --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --confirm-model-call --json
wagent provider-probe --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --mode safe --json
wagent provider-probe --config runtime.json --budget-entry my_budget:open_budgets --confirm-budget-code --mode active --confirm-active-probe --json
```

An entire evaluation batch opens one factory and shares its pool across cases, without resetting allowance per case. CLI JSON adds a separate `shared_budget`; text and TUI display the pool separately. Saved `--report` files retain the original evaluation-report format, and pool snapshots are not exclusive batch usage. Snapshot failures do not change evaluation/probe results or replay generation. TUI Evaluation and configured Models probes require separate `LOAD BUDGET`, alongside existing `EVALUATE` / `ACTIVE` consent.

Safe mode only lists models, without generation reservations, but the factory remains authorized trusted host code with potential side effects. Active/capability mode uses the probe's minimal request cap of 8 output tokens, not the agent output cap. The wrapper reserves a reliable bound for that request and denies insufficient allowance before generation. Ordinary URL endpoint probes are outside model budgets. Hidden calls inside factories, scorers or tools are not automatically metered and must be wrapped by the host.

Unified cross-ledger totals and real-environment acceptance remain planned; see a9 release notes for validation scope.

## Structured media run entry (2.0.0a7; focused regressions passed)

### a8: local context templates (2.0.0a8 Experimental; focused regressions passed)

Alongside existing `text` / `recorded` / `none`, `--history` adds `retrieved` / `summarized`. Both use historical text only and require separate `--confirm-history-transform`, accepting possible loss of facts. This replaces neither model-call consent, input-recording consent, tool-code consent nor media-history consent, and invokes no additional models automatically.

```text
wagent run "continue the refund" --session existing-session --history retrieved --history-query "refund invoice" --history-recent-turns 2 --history-retrieved-turns 4 --confirm-history-transform --confirm-model-call
wagent run "continue discussion" --session existing-session --history summarized --history-summary-chars 4096 --history-max-bytes 65536 --confirm-history-transform --confirm-model-call
```

Retrieval requires an explicit nonempty `--history-query`, never automatically extracted from Prompt or a media file. `--history-recent-turns` defaults to 2 and accepts zero. Retrieved older segments default to 4, summary characters to 4096 and template-output UTF-8 bytes to 65536; the latter three must be positive integers. The byte limit is not a token budget. Shared `BuiltinSessionHistoryOptions` validation rejects irrelevant mode-specific settings rather than silently ignoring them, before input-file reads, tool imports or Runtime assembly.

TUI Run offers the same fields (blank means default) and `TRANSFORM HISTORY` consent. Python hosts can still inject any `history_policy` without this built-in options object. See [Session templates](./sessions.en.md) for default input limits, text-role restrictions and lossy behavior. Focused regressions for this wiring passed.

`LocalAgentRuntime.run_messages(messages, ...)` accepts a nonempty sequence of `ModelMessage` objects. Existing `run(prompt, ...)` preserves text usage and default titles. Both accept per-call `record_inputs`, `include_history` and `history_policy`, defaulting to no additional input recording and text history. Typed-message runs default to title `Agent run`, overridable by `session_title`. Permissions, exact approved call IDs, cancellation and event callbacks still use the same Session/Agent path. Resume does not reinject history.

```python
from w_agent import load_input_manifest, RecordedSessionHistoryPolicy

messages = load_input_manifest("input.json")  # Read/parse only; no model call.
async with runtime:
    run = await runtime.run_messages(
        messages,
        session_id="existing-session",
        record_inputs=True,
        history_policy=RecordedSessionHistoryPolicy(),
    )
```

Python hosts obtain consent for model sending, Session recording and media-history reuse; the API does not display confirmation prompts. Replace or reassemble the recorder through public `runtime.sessions`. `include_history=False` disables history, not current messages. See [Session policies](./sessions.en.md).

CLI accepts exactly one Prompt or `--input-file`, such as this `input.json` (replace the example URL):

```json
{
  "schema_version": 1,
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "Describe this image"},
      {"type": "image", "url": "https://example.test/image.png"}
    ]
  }]
}
```

```text
wagent run --input-file input.json --confirm-model-call
wagent run --input-file input.json --record-inputs --confirm-input-recording --confirm-model-call
wagent run "Continue the analysis" --session existing-session --history recorded --confirm-history-media --confirm-model-call
wagent run "Independent question" --history none --confirm-model-call
```

Published a7 accepts `text` (default), `recorded` or `none` for `--history`; additional a8 modes are described above. Media-history and current-input-recording confirmations are independent, never stored as future authority in config or Sessions. Tool-code loading and tool permissions retain their separate gates. Required confirmations and mutually exclusive input checks happen before reading input, importing tools, loading configuration or assembling the Runtime. Malformed inputs do not trigger tool imports. Actual Runtime assembly and Session creation may still create local directories or an empty Session; later failure does not establish that no local writes occurred.

Files accept schema 1, user messages and text/image/audio only, rejecting unknown keys, duplicate JSON keys, non-finite numbers, tool calls/results, permissions and execution settings. Name/metadata are also rejected by default; see the explicit a8 options below. Image/audio sources are either HTTP(S) `url` without userinfo (`media_type` optional), or strict `data_base64` with required `media_type`. No attachment paths, downloads or code imports are supported. URLs are forwarded to the Provider; hosts govern subsequent fetching and network permissions. Other roles/types remain available through Python `run_messages()` or host parsers: this file template does not limit core protocols.

### a8 message-field run options (2.0.0a8 Experimental; focused regressions passed)

Input-file user messages may include `name` / `metadata` only with explicit `--input-message-fields`; Python parsers use `allow_message_fields=True`. Names are nonempty strings up to 256 characters; metadata is a finite JSON object with string keys. Fields default to at most 64 KiB per message and count toward the manifest's total content budget. Values are detached copies, never role, tool-permission or execution grants.

- Current input: `--input-message-fields` permits forwarding fields to the configured Provider, even without recording. `--confirm-model-call` is still required.
- Additional recording: independently select `--record-input-name` / `--record-input-metadata`, requiring the input-field option and `--record-inputs --confirm-input-recording`.
- History reuse: independently select `--history-name` / `--history-metadata`, requiring `--history recorded --confirm-history-media`. Without field selection, this mode can still decode wrapped content without reusing its fields.
- Read-only display: Replay disclosure remains separate; neither displaying nor recording enables historical sending.

TUI Run has equivalent checkboxes and retains per-attempt `RUN`, `RECORD INPUTS` and `SEND HISTORY` confirmations, without new confirmation tokens. Selections are captured before execution and locked while running. Python `LocalAgentRuntime.run()` / `run_messages()` and `SessionManager.run_agent()` accept a per-call `input_recorder=MessageFieldsSessionInputRecorder(...)`, requiring `record_inputs=True` and never changing the shared Manager default. Omitting it retains the Manager's default recorder.

Hosts must confirm Provider field support; no live requests were executed for this change. The a7 manifest parser rejects these fields. Recording options do not disable existing checkpoints, events or Provider logs. Focused regressions passed.

Python `InputManifestLimits` defaults: 16 MiB file, 256 messages, 256 blocks per message, 1,000,000 characters per text block, 8 MiB decoded bytes per media item, 16,384 URL characters and 32 MiB total content. Files require UTF-8, with optional BOM. `input_manifest_from_mapping()` validates content/schema; `load_input_manifest()` additionally enforces the file-byte limit. There is no automatic compression, token estimate or silent truncation. Existing Provider capabilities, pricing, budgets and failures still apply; this does not establish media support for every model.

`record_inputs=False` only disables additional rich Session records, not existing RunEvents, checkpoints, model recordings or Provider logs. Existing checkpoints may retain full messages; review each persistence policy separately. The TUI Run form also supports media files and independent confirmations; see [TUI documentation](./tui.en.md). See [a7 release notes](./releases/2.0.0a7.en.md) for validation boundaries.

## Configuration

Example `.wagent/config.json`:

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

`template` accepts built-in `anthropic`, `gemini`, `ollama`, `qwen-native`, `deepseek`, `glm`, `qwen`, or `turbo`. `turbo` requires an explicit `base_url`. The loader rejects unknown fields, inline `api_key`, and credential-shaped extension fields. Credentials are resolved from `api_key_env` only during assembly and are not written to runs, sessions, or composition codes.

`tools.enabled` only selects names from the `tool_bindings` catalog explicitly supplied by the host. JSON imports no code, registers no unknown tool, and grants no permission or approval. `agent.max_tool_calls` must be positive when tools are enabled. Catalog tools that are not selected never enter this run's `ToolRegistry` or model context.

`pricing` is optional and entirely application supplied; the framework does not bundle vendor prices that may become stale. The version, currency, maximum run cost, and per-million-token rate for each exact provider/model must be explicit. JSON strings are recommended for amounts to avoid binary floating-point ambiguity. The example rates demonstrate structure only and are not current vendor prices. Cached input falls back conservatively to the normal input rate when omitted. With a cost budget enabled, a missing matching rate or missing attempt usage fails closed with `cost-unavailable`. Pre-call cost estimation is opt-in through `estimate_before_call=true` and requires an agent token estimator plus a per-call output or cumulative-total cap. `require_estimate` controls whether an unavailable projection fails closed before the model-generation request.

## CLI

To inspect the configured provider first, use:

```powershell
wagent provider-probe --config .wagent/config.json --mode safe --json
wagent provider-probe --config .wagent/config.json --mode active `
  --confirm-active-probe --json
```

`safe` generates no content, but a provider catalog may be either a remote request or a static declaration. Only `active` validates actual generation and stream termination with at most 8 output tokens, so it requires separate explicit authorization.

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

Every command requires explicit `--confirm-model-call` authorization. A successful result contains session ID, run ID, stop reason, final text, step/tool counts, the per-attempt ledger, and cumulative token/cost values plus completeness flags. Use `--session <id>` to continue an existing text session.

Developer-owned tools may use an explicit `module:attribute` entry that returns one `ToolBinding` or an iterable of bindings. Importing Python tool code is a separate risk: the CLI executes it only when both `--tool-entry` and `--confirm-tool-code` are present. Configuration alone cannot trigger imports. Runtime permissions must also be granted per command through `--grant-permission`:

```powershell
wagent run "Save this note" `
  --config .wagent/config.json `
  --tool-entry my_agent_tools:build_tools `
  --confirm-tool-code `
  --grant-permission notes.write `
  --confirm-model-call `
  --json
```

When policy requires per-call approval, the run stops as `needs-approval` and returns a `checkpoint_id` plus `pending_tool` containing only call ID, tool name, and argument names; values are not printed. Resume with the same configuration, entry, and permission after approving the exact call ID:

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

Every resume re-requests model-call authority, tool-code authority, and exact call IDs. Tool entries can change between processes; production hosts should pin package versions and verify their source.

If the run or call ID is unknown, run `wagent checkpoint list --json`; `--session` filters the result. The prompt-free list includes agent, status, tool name, call ID, argument names, and token/cost usage, but never prompts, argument values, outputs, or credentials.

## TUI

The Run screen reads the same configuration. The user must type `RUN` before a model call starts. After success it shows output, token usage, and cost, and keeps the session ID for the next turn. The UI never stores that confirmation as durable authority. The Checkpoints screen refreshes prompt-free agent summaries and workflow summaries from a selected state root. Developer tool code is imported only after `LOAD TOOLS`; workflow definitions are imported only after `LOAD WORKFLOW`. Agent and workflow recovery independently require one-shot `RESUME` and `RESUME WORKFLOW` confirmations.

## Budget semantics

- `max_output_tokens` bounds one model request's output.
- `emit_text_deltas=true` explicitly enables `model-text-delta` RunEvents. The independent `emit_tool_call_deltas=true` flag enables `model-tool-call-delta` events containing raw argument fragments. Both flags off keep collecting mode. `emit_output_blocks=true` separately records standard image/audio output blocks without changing collecting/streaming mode; those events may contain a URL or Base64. JSONL persists explicitly enabled raw content, while the default TUI/CLI projection shows only safe metadata, never text bodies, tool names, arguments, or media content.
- `max_input_tokens`, `max_cumulative_output_tokens`, and `max_total_tokens` are cumulative within one run.
- With `require_usage=true`, any attempt without usage, including a failed attempt before a successful retry, stops the run as `token-usage-unavailable`.
- `token_estimator="character"` is an explicitly selected local heuristic template; `require_estimate=true` fails closed before the call when estimation is unavailable. The Python API may inject any `TokenEstimator` and is not limited to this template.
- Pre-call estimation exposes `token-estimated`, tightens the output allowance against the total limit, and blocks the network request when estimated input leaves no generation space. `soft_limit_ratio` emits `token-budget-warning` without stopping the run.
- The character estimator is marked inexact and rejects image/audio input. It does not include hidden vendor overhead, retry, or failover usage; provider-reported usage remains authoritative after the call.
- `pricing.max_cost` is the cumulative run limit computed with the named price-table version. Decimal arithmetic is exact, and an over-limit response stops as `cost-budget` before its tool calls execute.
- Explicit cost preflight uses a replaceable `CostEstimator`. The default `PricingCostEstimator` builds a `cost-estimated` envelope from the selected routes, configured retry/failover counts, estimated input, and output cap, choosing the higher cached/uncached input quote. A projected cumulative overrun stops before the model-generation request; `pricing.soft_limit_ratio` emits `cost-budget-warning`. Whether route-catalog resolution itself uses network I/O remains provider-defined.
- A heuristic token estimate makes the monetary envelope non-conservative; only an exact token estimate marks the default envelope conservative. In every case, the cost budget reconciles provider-reported actual usage again after the call, and missing usage or price data never continues as zero cost.
- Setting `max_attempts_per_route` or `max_routes` above one authorizes additional, potentially billable retry or failover calls.

## Open assembly boundary

`load_local_runtime_config()`, `assemble_local_provider()`, and `assemble_local_runtime()` are convenience layers, not a second closed runtime. Provider-only assembly returns `LocalProviderAssembly`; it resolves credential references and constructs the object without registration or network access, after which the application chooses any probe or registration policy. The full runtime exposes its definition, loop, ModelRegistry, ToolRegistry, and SessionManager; `run()`/`resume()` can project live events in persisted order through `event_callback`. Both assemblies support `async with` and idempotent `aclose()`; the full runtime rejects use after close. CLI/TUI paths use and close them in the same event loop automatically. Applications can replace the template registry, provider transport, routing, tools, and stores. The `2.0.0a4` release also accepts `assemble_local_runtime(..., stream_recovery=NativeCursorRecovery(max_resumes=2))`; this takes effect only when the agent configuration explicitly enables text or tool-argument deltas and the provider implements the matching protocol. JSON configuration does not load strategy code or persist cursors by itself.

Applications pass `{name: ToolBinding}` as `tool_bindings`; configuration selects only a subset. `LocalAgentRuntime.run()` accepts authority and optional approved IDs for that run, while `resume()` accepts session/run IDs, authority, and a non-empty exact approval set. Configuration, sessions, checkpoints, and composition codes cannot create permission, approval, or local-execution authority.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
