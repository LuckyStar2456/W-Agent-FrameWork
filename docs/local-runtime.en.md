# Locally configured agent runtime

English | [简体中文](./local-runtime.md)

Status: `Experimental`. `2.0.0a3` includes strict local JSON configuration, environment-variable credential references, provider/routing/ReAct assembly, versioned pricing and cost budgets, provider-only assembly and probing, explicit tool selection, persistent runs/sessions, Python API/CLI/TUI approval resume, prompt-free agent-checkpoint listing, application event callbacks, and CLI/TUI text-run entry points. Current main additionally implements explicit pre-call cost estimation/replay envelopes plus privacy-safe workflow-checkpoint discovery and explicit recovery.

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
- `emit_text_deltas=true` explicitly enables `model-text-delta` RunEvents. JSONL persists delta bodies, while the TUI renders safe metadata only and never the body.
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

`load_local_runtime_config()`, `assemble_local_provider()`, and `assemble_local_runtime()` are convenience layers, not a second closed runtime. Provider-only assembly returns `LocalProviderAssembly`; it resolves credential references and constructs the object without registration or network access, after which the application chooses any probe or registration policy. The full runtime exposes its definition, loop, ModelRegistry, ToolRegistry, and SessionManager; `run()`/`resume()` can project live events in persisted order through `event_callback`. Both assemblies support `async with` and idempotent `aclose()`; the full runtime rejects use after close. CLI/TUI paths use and close them in the same event loop automatically. Applications can replace the template registry, provider transport, routing, tools, and stores.

Applications pass `{name: ToolBinding}` as `tool_bindings`; configuration selects only a subset. `LocalAgentRuntime.run()` accepts authority and optional approved IDs for that run, while `resume()` accepts session/run IDs, authority, and a non-empty exact approval set. Configuration, sessions, checkpoints, and composition codes cannot create permission, approval, or local-execution authority.
