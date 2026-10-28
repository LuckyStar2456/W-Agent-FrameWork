"""Two-layer review and coordination regressions."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

import w_agent.workflows.tool_approval as approval_module
from w_agent import (
    AgentDefinition, AgentWorkflowApproval, CheckpointStatus, InMemoryRunStore,
    InMemoryWorkflowStore, RunCheckpoint, RunResult, ScopePath, StopReason,
    ToolCall, ToolContinuation, WorkflowCheckpoint, WorkflowCheckpointStatus,
    WorkflowEvent, WorkflowEventType, WorkflowKind, WorkflowNodeContext,
    WorkflowToolApprovalError, WorkflowToolReference,
    open_workflow_tool_approval_entry, resume_workflow_tool_approval,
    review_workflow_tool_approvals,
)


async def _fixtures():
    scope = ScopePath.application("PRIVATE_SCOPE")
    outer = WorkflowToolReference("outer", "outer-call", "workflow", "workflow-run", "flow", "1", WorkflowKind.DAG, scope)
    inner = AgentWorkflowApproval("workflow-run", "node", "inner", "coder", "inner-call", "write")
    ticket = ToolContinuation("w-agent.workflow-tool", {"reference": outer.to_dict(), "sequence": 1})
    parent = RunCheckpoint("outer", AgentDefinition("parent"), scope, (),
                           ToolCall("outer-call", "workflow", {"input": {"value": "PRIVATE_INPUT"}}, scope),
                           (), 1, 1, "", schema_version=2, tool_continuation=ticket)
    workflow = WorkflowCheckpoint(
        "workflow-run", "flow", "1", WorkflowKind.DAG, scope, None,
        {"_w_agent_approval:node": inner.to_dict()}, {}, (), remaining_nodes=("node",),
        metadata={"_w_agent_workflow_tool": outer.to_dict()}, status=WorkflowCheckpointStatus.PAUSED,
    )
    child = RunCheckpoint("inner", AgentDefinition("coder"), scope, (),
                          ToolCall("inner-call", "write", {"value": "PRIVATE_ARGUMENT"}, scope), (), 1, 1, "")
    parents, workflows, children = InMemoryRunStore(), InMemoryWorkflowStore(), InMemoryRunStore()
    await parents.save_checkpoint(parent)
    await workflows.save_checkpoint(workflow)
    await children.save_checkpoint(child)
    await workflows.append(WorkflowEvent(1, WorkflowEventType.WORKFLOW_PAUSED, "workflow-run"))
    selection, = await review_workflow_tool_approvals(parents, workflows, children, "outer")
    return parents, workflows, children, selection


def _node_context(context):
    reference = context.selection.child.reference
    return WorkflowNodeContext(reference.workflow_run_id, reference.workflow_node, None, {}, {},
                               context.selection.parent.scope, None)


def _factory(seen, calls, *, failure=None):
    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        reference = context.selection.child.reference
        class Loop:
            store = context.parent_store
            async def resume(self, run_id, *, tool_context, cancellation):
                if failure == "unused":
                    return RunResult(run_id, StopReason.NEEDS_APPROVAL, "", (), (), 1, 1)
                calls.append((run_id, tool_context, context.grants(_node_context(context), reference)))
                if failure == "resume":
                    raise asyncio.CancelledError()
                return RunResult(run_id, StopReason.NEEDS_APPROVAL, "", (), (), 1, 1)
        try:
            if failure == "enter":
                context.grants.grant(reference, scope=context.selection.parent.scope)
                raise ValueError("PRIVATE_FAILURE")
            yield Loop()
        finally:
            if failure == "exit":
                context.grants.grant(reference, scope=context.selection.parent.scope)
                raise ValueError("PRIVATE_FAILURE")
    return factory


async def test_review_is_read_only_and_projection_excludes_values():
    parents, workflows, children, selected = await _fixtures()
    before = await parents.load_checkpoint("outer")
    assert selected.sequence == 1
    data = json.dumps(selected.to_dict())
    assert "PRIVATE" not in data and selected.to_dict()["authorized"] is False
    assert await parents.load_checkpoint("outer") == before
    assert len(await workflows.events("workflow-run")) == 1


async def test_service_separates_exact_permissions_and_clears_authority():
    parents, workflows, children, selected = await _fixtures()
    seen, calls = [], []
    result = await resume_workflow_tool_approval(
        parents, workflows, children, selected, _factory(seen, calls),
        parent_permissions={"workflow.execute"}, child_permissions={"write.allowed"},
    )
    assert result.run_id == "outer"
    assert seen[0].parent_store is parents and seen[0].workflow_store is workflows
    assert seen[0].child_store is children
    run_id, outer, inner = calls[0]
    assert run_id == "outer" and outer.approved_call_ids == {"outer-call"}
    assert outer.permissions == {"workflow.execute"}
    assert inner.approved_call_ids == {"inner-call"} and inner.permissions == {"write.allowed"}
    assert not seen[0].grants(_node_context(seen[0]), selected.child.reference).approved_call_ids


@pytest.mark.parametrize("damage", ["outer-uncertain", "inner-mismatch", "boundary", "selection"])
async def test_stale_selection_rejected_before_factory(damage):
    parents, workflows, children, selected = await _fixtures()
    if damage == "outer-uncertain":
        await parents.save_checkpoint(replace(await parents.load_checkpoint("outer"), status=CheckpointStatus.RESUMING))
    elif damage == "inner-mismatch":
        child = await children.load_checkpoint("inner")
        await children.save_checkpoint(replace(child, pending_tool_call=replace(child.pending_tool_call, id="other")))
    elif damage == "boundary":
        await workflows.append(WorkflowEvent(2, WorkflowEventType.WORKFLOW_PAUSED, "workflow-run"))
    else:
        selected = replace(selected, sequence=2)
    seen, calls = [], []
    with pytest.raises(WorkflowToolApprovalError):
        await resume_workflow_tool_approval(parents, workflows, children, selected, _factory(seen, calls))
    assert not seen and not calls


@pytest.mark.parametrize("damage", ["nested-argument", "child-definition", "workflow-state", "wrong-store"])
async def test_assembly_mutation_is_rechecked(damage):
    parents, workflows, children, selected = await _fixtures()
    seen, calls = [], []
    @asynccontextmanager
    async def factory(context):
        if damage == "nested-argument":
            # Same frozen checkpoint object, changed nested dict: value snapshot must catch it.
            (await parents.load_checkpoint("outer")).pending_tool_call.arguments["input"]["value"] = "CHANGED"
        elif damage == "child-definition":
            await children.save_checkpoint(replace(await children.load_checkpoint("inner"),
                                                   definition=AgentDefinition("coder", system_prompt="CHANGED")))
        elif damage == "workflow-state":
            workflow = await workflows.load_checkpoint("workflow-run")
            await workflows.save_checkpoint(replace(workflow, state={**workflow.state, "changed": True}))
        async with _factory(seen, calls)(context) as loop:
            if damage == "wrong-store":
                loop.store = InMemoryRunStore()
            yield loop
    with pytest.raises(WorkflowToolApprovalError):
        await resume_workflow_tool_approval(parents, workflows, children, selected, factory)
    assert not calls
    assert not seen[0].grants(_node_context(seen[0]), selected.child.reference).approved_call_ids


@pytest.mark.parametrize("failure", ["enter", "resume", "exit"])
async def test_cleanup_on_factory_failure_or_cancellation(failure):
    parents, workflows, children, selected = await _fixtures()
    seen, calls = [], []
    with pytest.raises(asyncio.CancelledError if failure == "resume" else ValueError):
        await resume_workflow_tool_approval(parents, workflows, children, selected,
                                           _factory(seen, calls, failure=failure))
    assert not seen[0].grants(_node_context(seen[0]), selected.child.reference).approved_call_ids


async def test_loader_defers_import_until_context_entry(monkeypatch):
    imports = []
    @asynccontextmanager
    async def factory(context):
        yield context
    def load(name):
        imports.append(name)
        return SimpleNamespace(factory=factory)
    monkeypatch.setattr(approval_module.importlib, "import_module", load)
    manager = open_workflow_tool_approval_entry("demo:factory", "context")
    assert not imports
    async with manager as value:
        assert value == "context" and imports == ["demo"]


async def test_unused_grant_is_cleared_when_parent_remains_paused():
    parents, workflows, children, selected = await _fixtures()
    seen, calls = [], []
    result = await resume_workflow_tool_approval(
        parents, workflows, children, selected, _factory(seen, calls, failure="unused"),
        child_permissions={"write.allowed"},
    )
    assert result.stop_reason is StopReason.NEEDS_APPROVAL and not calls
    assert not seen[0].grants(_node_context(seen[0]), selected.child.reference).approved_call_ids
    assert (await parents.load_checkpoint("outer")).status is CheckpointStatus.PENDING_APPROVAL


async def test_child_call_scope_mismatch_cannot_receive_grant():
    parents, workflows, children, selected = await _fixtures()
    child = await children.load_checkpoint("inner")
    await children.save_checkpoint(replace(child, pending_tool_call=replace(
        child.pending_tool_call, scope=ScopePath.application("other"),
    )))
    seen, calls = [], []
    with pytest.raises(WorkflowToolApprovalError):
        await resume_workflow_tool_approval(parents, workflows, children, selected, _factory(seen, calls))
    assert not seen and not calls
