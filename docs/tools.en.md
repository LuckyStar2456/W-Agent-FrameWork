# Tool registration, policy, and execution

English | [简体中文](./tools.md)

Status: the Python-function template, scoped registration, argument validation, permission/approval policies, timeout, cancellation, and auditing are `Implemented` in Phase 3 / `2.0.0a1`. HTTP, MCP, command-line, and remote tool templates remain `Planned` or `Reserved`.

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

- HTTP, MCP, command-line, and remote tool adapters.
- Sandbox binding and Docker/OCI coding execution.
- Durable audit, tool caching, record/replay, and result streaming.
- TUI approval surfaces and cross-process approval recovery.
