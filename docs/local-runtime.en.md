# Locally configured agent runtime

English | [简体中文](./local-runtime.md)

Status: `Experimental` in `2.0.0a1`. Strict local JSON configuration, environment-variable credential references, provider/routing/ReAct assembly, persistent runs/sessions, and CLI/TUI text-run entry points are implemented. Configured tool selection, approval-resume UI, and live RunEvent inspection remain `Planned`.

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
    "max_tool_calls": 0,
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
  }
}
```

`template` accepts built-in `anthropic`, `gemini`, `ollama`, `qwen-native`, `deepseek`, `glm`, `qwen`, or `turbo`. `turbo` requires an explicit `base_url`. The loader rejects unknown fields, inline `api_key`, and credential-shaped extension fields. Credentials are resolved from `api_key_env` only during assembly and are not written to runs, sessions, or composition codes.

## CLI

```powershell
$env:DEEPSEEK_API_KEY = "..."
wagent run "Explain this repository" `
  --config .wagent/config.json `
  --confirm-model-call `
  --json
```

Every command requires explicit `--confirm-model-call` authorization. A successful result contains session ID, run ID, stop reason, final text, step/tool counts, the per-attempt ledger, and input, output, cached-input, and total tokens plus the completeness flag. Use `--session <id>` to continue an existing text session.

## TUI

The Run screen reads the same configuration. The user must type `RUN` before a model call starts. After success it shows output and token usage and keeps the session ID for the next turn. The UI never stores that confirmation as durable authority.

## Budget semantics

- `max_output_tokens` bounds one model request's output.
- `max_input_tokens`, `max_cumulative_output_tokens`, and `max_total_tokens` are cumulative within one run.
- With `require_usage=true`, any attempt without usage, including a failed attempt before a successful retry, stops the run as `token-usage-unavailable`.
- Provider-reported usage is enforceable only after a call. There is no pre-call token estimator yet, so the first call can cross a cumulative limit.
- Setting `max_attempts_per_route` or `max_routes` above one authorizes additional, potentially billable retry or failover calls.

## Open assembly boundary

`load_local_runtime_config()` and `assemble_local_runtime()` are convenience layers, not a second closed runtime. The returned `LocalAgentRuntime` exposes its definition, loop, ModelRegistry, ToolRegistry, and SessionManager. Applications can replace the template registry, provider transport, routing, tools, and stores.

The configuration entry point loads no tool and grants no permission, approval, or local-execution authority. Tool-enabled applications register `ToolBinding` values through the public Python API and explicitly supply policy and `ToolExecutionContext`. Future configured tool selection must preserve the same authority boundary.
