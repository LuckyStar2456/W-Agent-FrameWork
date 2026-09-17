import asyncio

import pytest

from w_agent import (
    CancellationToken,
    InMemoryToolAuditSink,
    ScopePath,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolOutcome,
    ToolRegistry,
    ToolSideEffect,
    python_tool,
)


@pytest.mark.asyncio
async def test_python_tool_registers_validates_executes_and_audits():
    def add(left: int, right: int = 1) -> int:
        """Add two integers."""

        return left + right

    binding = python_tool(add)
    tools = ToolRegistry()
    registration = tools.register_binding(binding, version="1")
    audit = InMemoryToolAuditSink()
    executor = ToolExecutor(tools, audit=audit)

    result = await executor.execute(ToolCall("call-1", "add", {"left": 2}))

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.content == "3"
    assert result.data == 3
    assert tools.definitions() == (binding.definition,)
    assert binding.definition.description == "Add two integers."
    assert binding.definition.input_schema["required"] == ["left"]
    assert audit.records[0].argument_keys == ("left",)
    assert not hasattr(audit.records[0], "arguments")

    registration.dispose()
    assert tools.bindings() == ()


@pytest.mark.asyncio
async def test_invalid_arguments_fail_before_handler_execution():
    calls = 0

    async def save(value: str) -> str:
        nonlocal calls
        calls += 1
        return value

    tools = ToolRegistry()
    tools.register_binding(python_tool(save))
    executor = ToolExecutor(tools)

    missing = await executor.execute(ToolCall("missing", "save", {}))
    unknown = await executor.execute(
        ToolCall("unknown", "save", {"value": "ok", "extra": True})
    )

    assert missing.failure is not None
    assert missing.failure.code == "invalid-tool-arguments"
    assert unknown.failure is not None
    assert unknown.failure.code == "invalid-tool-arguments"
    assert calls == 0


@pytest.mark.asyncio
async def test_permissions_deny_and_write_effect_requires_per_call_approval():
    values = []

    def save(value: str) -> str:
        values.append(value)
        return "saved"

    binding = python_tool(
        save,
        side_effect=ToolSideEffect.WRITE,
        required_permissions=frozenset({"files.write"}),
    )
    tools = ToolRegistry()
    tools.register_binding(binding)
    executor = ToolExecutor(tools)
    call = ToolCall("write-1", "save", {"value": "secret"})

    denied = await executor.execute(call)
    needs_approval = await executor.execute(
        call,
        ToolExecutionContext(permissions=frozenset({"files.write"})),
    )
    allowed = await executor.execute(
        call,
        ToolExecutionContext(
            permissions=frozenset({"files.write"}),
            approved_call_ids=frozenset({"write-1"}),
        ),
    )

    assert denied.outcome == ToolOutcome.DENIED
    assert needs_approval.outcome == ToolOutcome.NEEDS_APPROVAL
    assert allowed.outcome == ToolOutcome.SUCCEEDED
    assert values == ["secret"]


@pytest.mark.asyncio
async def test_tool_timeout_and_cooperative_cancellation_are_results():
    async def slow(delay: float) -> str:
        await asyncio.sleep(delay)
        return "done"

    tools = ToolRegistry()
    tools.register_binding(python_tool(slow))
    timed_executor = ToolExecutor(tools, timeout=0.01)

    timed_out = await timed_executor.execute(
        ToolCall("timeout", "slow", {"delay": 1.0})
    )

    cancellation = CancellationToken()
    normal_executor = ToolExecutor(tools, timeout=1)
    pending = asyncio.create_task(
        normal_executor.execute(
            ToolCall("cancel", "slow", {"delay": 1.0}),
            ToolExecutionContext(cancellation=cancellation),
        )
    )
    await asyncio.sleep(0)
    cancellation.cancel()
    cancelled = await pending

    assert timed_out.outcome == ToolOutcome.TIMED_OUT
    assert cancelled.outcome == ToolOutcome.CANCELLED


@pytest.mark.asyncio
async def test_unknown_and_failing_tools_return_normalized_failures():
    def explode() -> None:
        raise RuntimeError("sensitive detail")

    tools = ToolRegistry()
    tools.register_binding(python_tool(explode))
    executor = ToolExecutor(tools)

    unknown = await executor.execute(
        ToolCall(
            "not-found",
            "absent",
            {},
            scope=ScopePath.application("test"),
        )
    )
    failed = await executor.execute(ToolCall("explode", "explode", {}))

    assert unknown.failure is not None
    assert unknown.failure.code == "tool-not-found"
    assert failed.failure is not None
    assert failed.failure.code == "tool-execution-failed"
    assert "sensitive detail" not in failed.failure.message
