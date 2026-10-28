"""Continuation contracts and persistence regressions."""

from dataclasses import replace

import pytest

from w_agent import (
    AgentDefinition, CheckpointStatus, JsonlRunStore, RunCheckpoint, ScopePath,
    ToolBinding, ToolCall, ToolContinuation, ToolContinuationError, ToolDefinition,
    ToolExecutionContext, ToolExecutor, ToolOutcome, ToolRegistry, ToolResult,
)
from w_agent.agents.persistence import _checkpoint_from_data, _checkpoint_to_data


def _binding(started, resumed):
    async def start(arguments, context):
        started.append(context.invocation)
        return ToolContinuation("example.wait", {"child": "child-1", "phase": "prepared"})
    async def resume(arguments, continuation, context):
        assert continuation.kind == "example.wait" and continuation.version == 1
        resumed.append((continuation, context.invocation))
        return {"done": True}
    return ToolBinding(
        ToolDefinition("wait", "Prepare a wait", {"type": "object"}), start,
        required_permissions=frozenset({"workflow.execute"}),
        metadata={"adapter": "example"}, resume_handler=resume,
    )


async def test_executor_suspends_and_rechecks_permission_and_exact_call_authority():
    started, resumed = [], []
    registry = ToolRegistry()
    binding = _binding(started, resumed)
    registry.register_binding(binding)
    assert registry.binding("wait") is binding
    assert registry.binding("wait").metadata["adapter"] == "example"
    executor = ToolExecutor(registry)
    call = ToolCall("call-1", "wait", {})
    permissions = frozenset({"workflow.execute"})
    suspended = await executor.execute(call, ToolExecutionContext(permissions=permissions))
    assert suspended.outcome is ToolOutcome.NEEDS_APPROVAL
    assert suspended.content == "" and suspended.data is None
    assert started == [call] and resumed == []
    for context in (
        ToolExecutionContext(permissions=permissions),
        ToolExecutionContext(permissions=permissions, approved_call_ids={"wrong"}),
        ToolExecutionContext(approved_call_ids={"call-1"}),
    ):
        held = await executor.resume(call, suspended.continuation, context)
        assert held.outcome is ToolOutcome.NEEDS_APPROVAL
        assert held.continuation == suspended.continuation and resumed == []
    result = await executor.resume(call, suspended.continuation, ToolExecutionContext(
        permissions=permissions, approved_call_ids={"call-1"},
        invocation=ToolCall("forged", "other", {}),
    ))
    assert result.outcome is ToolOutcome.SUCCEEDED and result.data == {"done": True}
    assert resumed == [(suspended.continuation, call)] and started == [call]
    assert executor.audit.records[-1].outcome is ToolOutcome.SUCCEEDED


async def test_missing_resume_handler_never_falls_back_to_start():
    started = []
    async def start(arguments, context):
        started.append(True)
    registry = ToolRegistry()
    registry.register_binding(ToolBinding(ToolDefinition("wait", "wait", {"type": "object"}), start))
    executor = ToolExecutor(registry)
    with pytest.raises(ToolContinuationError):
        await executor.resume(ToolCall("call", "wait", {}), ToolContinuation("kind", {}),
                              ToolExecutionContext(approved_call_ids={"call"}))
    assert not started
    assert executor.audit.records[-1].failure_code == "tool-continuation-invalid"


@pytest.mark.parametrize("value", [object(), {"value": float("nan")}, {"value": b"bytes"}])
def test_continuation_rejects_non_json_payload(value):
    with pytest.raises(ValueError):
        ToolContinuation("kind", value)


def test_continuation_envelope_and_result_are_explicit():
    token = ToolContinuation("kind", {"reference": "child"})
    assert ToolContinuation.from_dict(token.to_dict()) == token
    with pytest.raises(ValueError):
        ToolContinuation.from_dict({**token.to_dict(), "approved": True})
    with pytest.raises(ValueError):
        ToolContinuation("kind", {}, version=True)
    with pytest.raises(ValueError):
        ToolResult("call", "wait", ToolOutcome.SUCCEEDED, continuation=token)


async def test_checkpoint_roundtrip_requires_v2_and_cannot_drop_ticket(tmp_path):
    checkpoint = RunCheckpoint(
        "run", AgentDefinition("agent"), ScopePath.application(), (),
        ToolCall("call", "wait", {}), (), 1, 1, "",
        schema_version=2, tool_continuation=ToolContinuation("kind", {"child": "one"}),
    )
    store = JsonlRunStore(tmp_path)
    await store.save_checkpoint(checkpoint)
    assert await JsonlRunStore(tmp_path).load_checkpoint("run") == checkpoint
    claimed = await store.claim_checkpoint("run")
    assert claimed.status is CheckpointStatus.RESUMING
    assert claimed.tool_continuation == checkpoint.tool_continuation
    data = _checkpoint_to_data(checkpoint)
    with pytest.raises(ValueError):
        _checkpoint_from_data({**data, "schema_version": 1})
    with pytest.raises(ValueError):
        _checkpoint_from_data({**data, "tool_continuation": None})
    with pytest.raises(ValueError):
        replace(checkpoint, pending_tool_call=None)
    legacy = replace(checkpoint, schema_version=1, tool_continuation=None)
    assert "tool_continuation" not in _checkpoint_to_data(legacy)
    assert _checkpoint_from_data(_checkpoint_to_data(legacy)) == legacy
