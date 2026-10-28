# Tool registration, policy, and execution

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./tools.md)

Tool-result event recording (2.0.0a7; focused regressions passed): ReAct can explicitly record model-visible result text through an Agent-loop-injected encoder without changing tool implementations. Recording off does not affect execution; encoding failure never replays a tool, and approval tickets are not result bodies. Hosts can redact/omit and separately authorize replay disclosure. See [tool-result bodies](./event-replay.en.md).

Status: Python, HTTP, shell-free command, sandbox-command templates, MCP binding, MCP 2026-07-28 stdio/Streamable HTTP clients, scoped registration, argument validation, permission/approval policy, timeout, cancellation, and audit are `Implemented`. The workspace also implements legacy initialization, explicit handlers, bounded MRTR, and duplex stdio subscriptions. Persistent HTTP subscriptions and legacy HTTP server requests remain pending. See [MCP interactions](mcp-interactions.en.md).

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

`McpClient` implements the current stable MCP `2026-07-28` request model: every request carries protocol version, client identity, and capabilities, without an implicit protocol session. `list_tools()` follows `nextCursor` within explicit bounds. `discover_mcp_bindings()` converts discovered definitions to bindings but **never registers, exposes, authorizes, or approves** a tool automatically. The caller explicitly registers selected return values.

```python
from w_agent import (
    McpClient,
    McpStdioTransport,
    ToolRegistry,
    discover_mcp_bindings,
)

transport = McpStdioTransport(("python", "-m", "my_mcp_server"))
client = McpClient(transport)
bindings = await discover_mcp_bindings(client, local_name_prefix="docs_")

registry = ToolRegistry()
for binding in bindings:
    registry.register_binding(binding, version="1.0.0")
```

The `2.0.0a4` release also offers opt-in `McpLegacyClient` for the 2025-03-26, 2025-06-18, and 2025-11-25 `initialize` / `notifications/initialized` lifecycle. It reuses `McpStdioTransport` or pairs with `McpLegacyStreamableHttpTransport`; the latter retains the server-provided `Mcp-Session-Id` and sends the negotiated version header on later requests. Legacy requests do not add 2026 per-request `_meta`. Unsupported negotiated versions or failed initialization make that client instance unusable; missing tool capability rejects tool requests. No protocol fallback, side-effecting tool-call replay, or automatic approval of discovered tools occurs. For example:

```python
from w_agent import McpLegacyClient, McpLegacyStreamableHttpTransport

client = McpLegacyClient(
    McpLegacyStreamableHttpTransport("https://mcp.example/mcp")
)
bindings = await discover_mcp_bindings(client)
```

By default no server-request capabilities are advertised. Applications may explicitly supply `McpClientHandlers` with `McpDuplexStdioTransport` for legacy server requests and notifications. Legacy HTTP server requests, the 2024 HTTP+SSE endpoint pair, automatic reconnection, and broad interoperability acceptance remain unsupported. Unified tool permission and per-call approval still apply.

`McpStdioTransport` starts explicit argv through `create_subprocess_exec()` with no shell. Stdin/stdout carry one-line UTF-8 JSON-RPC; the reader skips notifications until the matching response, cancellation sends `notifications/cancelled`, and shutdown closes stdin before bounded termination. Environment inheritance defaults on for local development. Use an absolute executable, `inherit_environment=False`, and a minimal environment—or a sandbox—for untrusted servers.

`McpStreamableHttpTransport` uses a fixed HTTP(S) endpoint, `POST`, JSON/SSE responses, and a replaceable `McpHttpExchange`. The default `HttpxMcpExchange` disables redirects and bounds response bytes. The transport owns `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, and valid `x-mcp-header` parameter headers, using UTF-8 Base64 when required. Static configuration cannot override these headers. Credentials may be fixed headers but never enter the request body, tool definition, or audit.

```python
from w_agent import McpClient, McpStreamableHttpTransport

client = McpClient(
    McpStreamableHttpTransport(
        "https://mcp.example/mcp",
        headers={"authorization": "Bearer <local-secret>"},
    )
)
tools = await client.list_tools()
```

The client preserves JSON-RPC error codes and routes remote `isError: true` results through local failure handling. Modern `input_required` replies are fulfilled only through explicit handlers within round/request bounds. Missing handlers or exhausted rounds raise `McpInputRequiredError` with the structured result. Duplex stdio supports `subscriptions/listen`, validates acknowledgment order, filter scope and correlation, and distinguishes graceful completion from disconnect. Protocol references: [MCP 2026-07-28 transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports) and [tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

## Default safety semantics

- Arguments are validated before the handler runs. The built-in validator covers objects, required and extra fields, basic JSON types, and enums. A fuller schema validator can replace this layer.
- `PermissionPolicy` denies execution when authority is missing.
- `SideEffectApprovalPolicy` requires per-call ID approval for `WRITE`, `DESTRUCTIVE`, and `EXTERNAL` effects by default; read-only calls need no approval.
- Values from composition codes, model output, or tool arguments never become approval credentials automatically.
- Timeout and cooperative cancellation return normalized `ToolResult` objects; cancellation of the outer task still propagates.
- `ToolAuditRecord` includes tool name, call ID, argument names, outcome, duration, and policy, but excludes argument values, output, and credentials.
- Handler exceptions are normalized without exposing exception text directly to the model.

Applications can replace the complete `ToolPolicy` or audit sink. Custom policies and adapters remain enforced in the real execution path and cannot rely only on hiding tools in prompts.

## Typed tool continuation (a6, focused regressions passed)

These optional protocols support reverse Agent-to-Workflow suspension. The a6 release also has a dedicated `resumable_workflow_tool()` bridge (see [Workflows](./workflows.en.md)); two-layer approval coordination services are now in the a6 release (focused regressions passed), while UI guidance is also present in the a6 release (focused regressions passed):

- `ToolContinuation(kind, payload, version=1)` carries finite JSON reference data, not authority, callbacks, or executable objects. Each adapter validates its kind, version, and ownership.
- Optional `ToolBinding.resume_handler(arguments, continuation, context)` continues work. An explicit `ToolContinuation` return produces `NEEDS_APPROVAL`, not a model-visible successful serialization of the ticket. Ordinary dictionary outputs remain ordinary tool results.
- `ToolExecutor.resume()` / replaceable `ResumableToolExecutorProtocol` invokes only the resume handler, never the start handler as a fallback. Every resume revalidates arguments, permissions, and policy and requires host-supplied exact-call approval. Missing permission/approval retains the ticket while waiting.
- The built-in executor binds `ToolExecutionContext.invocation` to the actual `ToolCall`, overriding a caller-supplied value. `ToolRegistry.register_binding()` retains the original binding, resume handler, and metadata.
- ReAct persists `RunCheckpoint.tool_continuation` using schema 2. Ordinary checkpoints retain schema 1. Older readers must reject schema 2 rather than ignore the ticket and restart the tool. Upgrade readers first; never manually downgrade or remove a ticket.
- While suspended, no tool result is appended to the model conversation, no queued sibling call runs, and the tool-call counter is not incremented again. Completion appends one result before returning to the model loop. Default events/checkpoint summaries do not expose tickets.

```python
from w_agent import ToolBinding, ToolContinuation, ToolDefinition

async def prepare(arguments, context):
    # Prepare a reference only; put actual side effects in resume after persistence.
    return ToolContinuation("my-workflow", {"phase": "prepared", "child": "host-owned-id"})

async def resume(arguments, ticket, context):
    # Validate kind/version, child checkpoint, and ownership before one authorized step.
    # Return another ToolContinuation to wait again, or a normal result on completion.
    return await continue_owned_child(ticket, context)

binding = ToolBinding(
    ToolDefinition("workflow", "Prepare a workflow", {"type": "object"}),
    prepare, resume_handler=resume,
)
```

`continue_owned_child` is application-provided; this is not a bundled Workflow bridge. Start handlers should prepare references only and avoid unreplayable effects before ticket persistence. Tickets cannot protect arbitrary handlers crashing before their first return; no cross-store atomic commit is promised. Failed, timed-out, cancelled, or unsupported continuation leaves ReAct's ticket-bearing checkpoint `RESUMING` and raises a safe error instead of discarding pending work or reporting completion to the model. Direct executor calls provide no durable claim; hosts manage ownership, stale references, and replay protection. Approval authorizes only this layer's call, never internal writes by a child Agent/Workflow implicitly.

Optional `ToolExecutionContext.agent_run_id` is host identity; ReAct overwrites it with the actual Run ID for every call. The Workflow bridge validates it alongside `invocation`, scope, and child references. Custom loops must supply trusted identity themselves. This field is neither authorization nor a sandbox security boundary.

## Not implemented yet

- Persistent HTTP subscriptions, legacy HTTP server requests, and legacy HTTP+SSE compatibility. MCP 2025 initialization, explicit MRTR fulfillment, and duplex stdio subscriptions are implemented.
- Durable sandbox sessions across tool calls and coding-agent workspace writeback review.
- Durable audit, tool caching, record/replay, and result streaming.
- Agent-to-Workflow arbitrary-depth recursive approval coordination. Ordinary Agent TUI approval is available; the a6 release also has explicit factory-based CLI/TUI recovery for an Agent inside Workflow (focused regressions passed).
