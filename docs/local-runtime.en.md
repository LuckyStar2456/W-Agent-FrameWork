# Locally configured agent runtime

English | [简体中文](./local-runtime.md)

Status: `Experimental` in `2.0.0a1`. Strict local JSON configuration, environment-variable credential references, provider/routing/ReAct assembly, explicit tool selection, persistent runs/sessions, Python API/CLI approval resume, and CLI/TUI text-run entry points are implemented. TUI tool-load/approval screens, checkpoint browsing, and live RunEvent inspection remain `Planned`.

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
    "max_input_tokens": 12000,
    "max_cumulative_output_tokens": 3000,
    "max_total_tokens": 15000,
    "require_usage": true
  },
  "invocation": {
    "max_attempts_per_route": 1,
    "max_routes": 1,
    "timeout": 60
  },
  "tools": {
    "enabled": ["repository_search", "save_note"]
  }
}
```

`template` accepts built-in `anthropic`, `gemini`, `ollama`, `qwen-native`, `deepseek`, `glm`, `qwen`, or `turbo`. `turbo` requires an explicit `base_url`. The loader rejects unknown fields, inline `api_key`, and credential-shaped extension fields. Credentials are resolved from `api_key_env` only during assembly and are not written to runs, sessions, or composition codes.

`tools.enabled` only selects names from the `tool_bindings` catalog explicitly supplied by the host. JSON imports no code, registers no unknown tool, and grants no permission or approval. `agent.max_tool_calls` must be positive when tools are enabled. Catalog tools that are not selected never enter this run's `ToolRegistry` or model context.

## CLI

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

Every command requires explicit `--confirm-model-call` authorization. A successful result contains session ID, run ID, stop reason, final text, step/tool counts, the per-attempt ledger, and input, output, cached-input, and total tokens plus the completeness flag. Use `--session <id>` to continue an existing text session.

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

## TUI

The Run screen reads the same configuration. The user must type `RUN` before a model call starts. After success it shows output and token usage and keeps the session ID for the next turn. The UI never stores that confirmation as durable authority. The TUI currently neither imports developer Python tools nor exposes approval resume; a configuration with `tools.enabled` fails closed and should be run through the Python API or CLI.

## Budget semantics

- `max_output_tokens` bounds one model request's output.
- `max_input_tokens`, `max_cumulative_output_tokens`, and `max_total_tokens` are cumulative within one run.
- With `require_usage=true`, any attempt without usage, including a failed attempt before a successful retry, stops the run as `token-usage-unavailable`.
- Provider-reported usage is enforceable only after a call. There is no pre-call token estimator yet, so the first call can cross a cumulative limit.
- Setting `max_attempts_per_route` or `max_routes` above one authorizes additional, potentially billable retry or failover calls.

## Open assembly boundary

`load_local_runtime_config()` and `assemble_local_runtime()` are convenience layers, not a second closed runtime. The returned `LocalAgentRuntime` exposes its definition, loop, ModelRegistry, ToolRegistry, and SessionManager. Applications can replace the template registry, provider transport, routing, tools, and stores.

Applications pass `{name: ToolBinding}` as `tool_bindings`; configuration selects only a subset. `LocalAgentRuntime.run()` accepts authority and optional approved IDs for that run, while `resume()` accepts session/run IDs, authority, and a non-empty exact approval set. Configuration, sessions, checkpoints, and composition codes cannot create permission, approval, or local-execution authority.
