"""Workflow tool continuation regressions."""

from dataclasses import replace

import pytest

from w_agent import (
    DagWorkflowDefinition, InMemoryWorkflowStore, JsonlWorkflowStore,
    LocalWorkflowEngine, PythonWorkflowDefinition, ScopePath, StateGraphDefinition,
    ToolCall, ToolContinuation, ToolContinuationError, ToolExecutionContext,
    WorkflowCheckpointStatus, WorkflowNode, WorkflowNodeResult, WorkflowToolReference,
    resumable_workflow_tool,
)


def _authority():
    call = ToolCall("call", "run_child", {"input": "PRIVATE"}, scope=ScopePath.application("project"))
    return ToolExecutionContext(
        permissions={"workflow.execute"}, approved_call_ids={call.id},
        invocation=call, agent_run_id="parent",
    )


def _definition(kind, calls):
    def first(context):
        calls.append("first")
        return WorkflowNodeResult(output="one", pause=True)
    def second(context):
        calls.append("second")
        return "two"
    nodes = (WorkflowNode("first", first), WorkflowNode("second", second))
    if kind == "dag":
        return DagWorkflowDefinition("child", nodes, {"second": ("first",)})
    if kind == "graph":
        return StateGraphDefinition("child", nodes, "first", {"first": "second"})
    def python(context):
        return first(context) if context.resume_count == 0 else second(context)
    return PythonWorkflowDefinition("child", python)


@pytest.mark.parametrize("kind", ["dag", "graph", "python"])
async def test_prepare_has_no_child_effect_and_reassembly_continues_boundary(tmp_path, kind):
    calls = []
    definition = _definition(kind, calls)
    store = JsonlWorkflowStore(tmp_path)
    binding = resumable_workflow_tool(LocalWorkflowEngine(store), definition, store)
    context = _authority()
    ticket = await binding.handler(context.invocation.arguments, context)
    reference = WorkflowToolReference.from_dict(ticket.payload["reference"])
    assert WorkflowToolReference.from_dict(reference.to_dict()) == reference
    assert calls == [] and await store.events(reference.workflow_run_id) == ()
    assert await store.load_checkpoint(reference.workflow_run_id) is None
    paused = await binding.resume_handler(context.invocation.arguments, ticket, context)
    assert isinstance(paused, ToolContinuation) and paused.payload["sequence"] > 0
    checkpoint = await store.load_checkpoint(reference.workflow_run_id)
    assert checkpoint.scope == context.invocation.scope
    assert checkpoint.status is WorkflowCheckpointStatus.PAUSED and calls == ["first"]

    # Rebuild the binding and store; no hidden in-memory child handle is needed.
    restarted_store = JsonlWorkflowStore(tmp_path)
    restarted = resumable_workflow_tool(LocalWorkflowEngine(restarted_store), definition, restarted_store)
    completed = await restarted.resume_handler(context.invocation.arguments, paused, context)
    assert completed["stop_reason"] == "completed" and calls == ["first", "second"]
    assert await restarted_store.load_checkpoint(reference.workflow_run_id) is None
    with pytest.raises(ToolContinuationError):
        await restarted.resume_handler(context.invocation.arguments, paused, context)
    assert calls == ["first", "second"]


@pytest.mark.parametrize("mismatch", ["parent", "call", "scope", "tool", "permission", "approval", "version"])
async def test_foreign_or_unapproved_reference_never_starts_child(mismatch):
    calls = []
    store = InMemoryWorkflowStore()
    definition = _definition("dag", calls)
    engine = LocalWorkflowEngine(store)
    binding = resumable_workflow_tool(engine, definition, store)
    context = _authority()
    ticket = await binding.handler(context.invocation.arguments, context)
    if mismatch == "parent":
        context = replace(context, agent_run_id="other")
    elif mismatch == "call":
        context = replace(context, invocation=replace(context.invocation, id="other"))
    elif mismatch == "scope":
        context = replace(context, invocation=replace(context.invocation, scope=ScopePath.application("other")))
    elif mismatch == "tool":
        context = replace(context, invocation=replace(context.invocation, name="other"))
    elif mismatch == "permission":
        context = replace(context, permissions=frozenset())
    elif mismatch == "approval":
        context = replace(context, approved_call_ids=frozenset())
    else:
        binding = resumable_workflow_tool(engine, replace(definition, version="2"), store)
    with pytest.raises(ToolContinuationError):
        await binding.resume_handler(context.invocation.arguments, ticket, context)
    assert calls == []


@pytest.mark.parametrize("corruption", ["owner", "uncertain", "sequence", "prepared-replay"])
async def test_stale_or_uncertain_child_is_not_replayed(corruption):
    calls = []
    store = InMemoryWorkflowStore()
    binding = resumable_workflow_tool(LocalWorkflowEngine(store), _definition("dag", calls), store)
    context = _authority()
    prepared = await binding.handler({}, context)
    paused = await binding.resume_handler({}, prepared, context)
    reference = WorkflowToolReference.from_dict(paused.payload["reference"])
    checkpoint = await store.load_checkpoint(reference.workflow_run_id)
    if corruption == "owner":
        await store.save_checkpoint(replace(checkpoint, metadata={}))
    elif corruption == "uncertain":
        await store.save_checkpoint(replace(checkpoint, status=WorkflowCheckpointStatus.RESUMING))
    elif corruption == "sequence":
        paused = ToolContinuation(paused.kind, {**paused.payload, "sequence": paused.payload["sequence"] + 1})
    else:
        paused = prepared
    with pytest.raises(ToolContinuationError):
        await binding.resume_handler({}, paused, context)
    assert calls == ["first"]


def test_wrong_store_rejected_at_assembly():
    with pytest.raises(ValueError):
        resumable_workflow_tool(LocalWorkflowEngine(), _definition("dag", []), InMemoryWorkflowStore())
