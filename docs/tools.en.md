# Tool registration, policy, and execution

English | [简体中文](./tools.md)

Status: Python, HTTP, shell-free command, sandbox-command templates, MCP client binding, scoped registration, argument validation, permission/approval policy, timeout, cancellation, and audit are `Implemented` in Phase 3/5 / `2.0.0a1`. First-party MCP session clients and remote tools remain `Planned` or `Reserved`.

## Layers

```text
ToolDefinition (model-visible schema)
        + ToolBinding (handler, permissions, effect)
        ↓
ToolRegistry (unified Registry, version, Scope)
        ↓
ToolPolicy (replaceable permission and per-call approval)
        ↓
ToolExecutor (validation, timeout, cancellation, execution, audit)
        ↓
ToolResult
```

A definition owns no execution policy. `ToolBinding` only joins a public definition to a handler; permission, approval, and audit remain enforced by the execution path. The default executor never retries a tool call because a failed call may already have produced side effects.

## Python tools

```python
from w_agent import (
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolSideEffect,
    python_tool,
)


def save_note(text: str) -> dict[str, str]:
    return {"saved": text}


binding = python_tool(
    save_note,
    side_effect=ToolSideEffect.WRITE,
    required_permissions=frozenset({"notes.write"}),
)
tools = ToolRegistry()
tools.register_binding(binding, version="1.0.0")
executor = ToolExecutor(tools)

call = ToolCall("call-1", "save_note", {"text": "hello"})
pending = await executor.execute(
    call,
    ToolExecutionContext(permissions=frozenset({"notes.write"})),
)
assert pending.outcome == "needs-approval"

result = await executor.execute(
    call,
    ToolExecutionContext(
        permissions=frozenset({"notes.write"}),
        approved_call_ids=frozenset({"call-1"}),
    ),
)
```

`python_tool()` derives a basic JSON Schema from a finite named signature and also accepts a caller-supplied `input_schema`. Both synchronous and asynchronous functions work. `ToolRegistry.register()` can directly attach any implementation satisfying the public `ToolHandler` protocol.

## HTTP tools

`http_tool()` maps GET/HEAD arguments to query parameters by default and uses a JSON body for other methods. The URL, method, and headers come from local configuration rather than model arguments; provide an explicit `request_builder` for another mapping. The default `HttpxToolTransport` validates TLS, does not follow redirects, and streams into a response byte limit. Private transports can replace it.

```python
from w_agent import http_tool

binding = http_tool(
    "ticket_create",
    "Create one support ticket.",
    {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    },
    url="https://support.example/api/tickets",
    headers={"authorization": "Bearer <local-secret>"},
)
```

The default permission is `network.http` and the default effect is `EXTERNAL`, so both authority and per-call ID approval are required. Fixed headers never enter the tool definition, result, or audit record.

## Command tools

`command_tool()` calls only `asyncio.create_subprocess_exec()` and never invokes a shell. Its `argument_builder` returns separate argv strings; semicolons, pipes, and redirection characters remain literal content. stdout and stderr each have a byte limit, and timeout or cancellation terminates the child process.

```python
from w_agent import command_tool

binding = command_tool(
    "git_status",
    "Read repository status.",
    {"type": "object", "additionalProperties": False},
    executable="git",
    base_arguments=("status", "--short"),
    argument_builder=lambda arguments: (),
)
```

The default permission is `process.execute` and the default effect is `EXTERNAL`. Commands inherit the current environment by default for local development. Set `inherit_environment=False` and inject only required values when handling untrusted plugins. This adapter provides shell-free argv, bounds, and policy enforcement; it is **not a sandbox**. Untrusted code belongs in `sandbox_command_tool()` with `DockerSandboxProvider`.

`sandbox_command_tool()` opens a `SandboxProvider` handle for each tool call, executes `SandboxCommand`, and closes in `finally`. It requires `sandbox.execute` and declares a `WRITE` effect by default. An upper runtime should hold a handle directly when one container must span multiple agent steps instead of using the one-call template.

## MCP tools

`McpRemoteTool` describes a remote name, description, and input schema. `mcp_tool()` binds any implementation of `McpToolClient.call_tool()` into the common tool runtime and propagates cancellation. It requires `mcp.call` authority and per-call approval by default.

The adapter does not constrain MCP transport, allowing custom stdio, HTTP, or in-process clients. The framework does not yet include first-party session management, discovery, or connection lifecycle. Client values still pass through `ToolExecutor` result normalization, exception sanitization, timeout, and audit.

## Default safety semantics

- Arguments are validated before the handler runs. The built-in validator covers objects, required and extra fields, basic JSON types, and enums. A fuller schema validator can replace this layer.
- `PermissionPolicy` denies execution when authority is missing.
- `SideEffectApprovalPolicy` requires per-call ID approval for `WRITE`, `DESTRUCTIVE`, and `EXTERNAL` effects by default; read-only calls need no approval.
- Values from composition codes, model output, or tool arguments never become approval credentials automatically.
- Timeout and cooperative cancellation return normalized `ToolResult` objects; cancellation of the outer task still propagates.
- `ToolAuditRecord` includes tool name, call ID, argument names, outcome, duration, and policy, but excludes argument values, output, and credentials.
- Handler exceptions are normalized without exposing exception text directly to the model.

Applications can replace the complete `ToolPolicy` or audit sink. Custom policies and adapters remain enforced in the real execution path and cannot rely only on hiding tools in prompts.

## Not implemented yet

- First-party MCP stdio/HTTP session clients, discovery, and connection lifecycle.
- Durable sandbox sessions across tool calls and coding-agent workspace writeback review.
- Durable audit, tool caching, record/replay, and result streaming.
- TUI approval surfaces and cross-process approval recovery.
