"""Draft regression coverage for node suspension and Agent approval cascading."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from w_agent import (
    AgentDefinition, AgentWorkflowApproval, BlockEnd, BlockStart, CheckpointStatus,
    DagWorkflowDefinition, FinishEvent, FinishReason, JsonlRunStore, JsonlWorkflowStore,
    LocalWorkflowEngine, ModelCapability, ModelDescriptor, ModelExecutor, ModelRegistry,
    ModelRouter, PythonWorkflowDefinition, ReactAgentLoop, ScriptedModelProvider,
    ScriptedModelTurn, StateGraphDefinition, TextContent, TextDelta, TokenUsage,
    ToolCallContent, ToolCallDelta, ToolExecutionContext, ToolExecutor, ToolRegistry,
    ToolSideEffect, UsageEvent, WeightedRoutingPolicy, WorkflowCheckpointStatus,
    WorkflowContext, WorkflowEventType, WorkflowNode, WorkflowNodeResult,
    WorkflowStopReason, approval_agent_workflow_node, python_tool,
    WorkflowApprovalGrants, review_workflow_approvals,
    resume_workflow_approval,
)


def _provider():
    events = []
    for index, call_id in enumerate(("call-1", "call-2")):
        arguments = '{"value":"PRIVATE_ARGUMENT"}'
        events.extend((
            BlockStart(index, "tool-call"),
            ToolCallDelta(index, call_id, "write", arguments),
            BlockEnd(index, ToolCallContent(call_id, "write", arguments)),
        ))
    events.extend((UsageEvent(TokenUsage(5, 2)), FinishEvent(FinishReason.TOOL_CALLS)))
    return ScriptedModelProvider(
        ModelDescriptor("fake", "chat", frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT,
            ModelCapability.STREAMING, ModelCapability.TOOL_CALLING,
        })),
        (
            ScriptedModelTurn(tuple(events)),
            ScriptedModelTurn((BlockStart(0, "text"), TextDelta(0, "PRIVATE_OUTPUT"),
                BlockEnd(0, TextContent("PRIVATE_OUTPUT")),
                UsageEvent(TokenUsage(8, 3)), FinishEvent(FinishReason.STOP))),
        ),
    )


def _loop(provider, store, calls):
    models = ModelRegistry()
    models.register("fake", provider)
    router = ModelRouter(models, WeightedRoutingPolicy(preferred_providers=("fake",)))
    registry = ToolRegistry()

    def write(value: str):
        calls.append(value)
        return "PRIVATE_TOOL_RESULT"

    registry.register_binding(python_tool(
        write, side_effect=ToolSideEffect.WRITE,
        required_permissions=frozenset({"write.allowed"}),
    ))
    return ReactAgentLoop(ModelExecutor(models, router), registry, ToolExecutor(registry), store=store)


def _workflow(kind, node, after):
    last = WorkflowNode("after", lambda _: after.append("after"))
    if kind == "dag":
        return DagWorkflowDefinition("approval", (node, last), {"after": (node.name,)})
    if kind == "graph":
        return StateGraphDefinition("approval", (node, last), node.name, {node.name: "after"})
    return PythonWorkflowDefinition("approval", node.handler)


async def test_managed_parent_approval_resume_continues_real_react_child(tmp_path):
    provider, calls, seen, closed = _provider(), [], [], []
    agents, parents = JsonlRunStore(tmp_path), JsonlWorkflowStore(tmp_path)
    definition = AgentDefinition("support")
    initial = approval_agent_workflow_node(
        "answer", _loop(provider, agents, calls), definition, agents,
        tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"write.allowed"})),
    )
    await LocalWorkflowEngine(parents).start(
        DagWorkflowDefinition("approval", (initial,)), WorkflowContext("parent", input="question"),
    )

    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        try:
            yield DagWorkflowDefinition("approval", (approval_agent_workflow_node(
                "answer", _loop(provider, context.agent_store, calls), definition,
                context.agent_store, approval_context=context.grants,
            ),))
        finally:
            closed.append(True)

    first = (await review_workflow_approvals(parents, agents, "parent"))[0].reference
    result = await resume_workflow_approval(
        parents, agents, first, factory, permissions={"write.allowed"},
    )
    assert result.stop_reason is WorkflowStopReason.PAUSED
    assert len(calls) == 1 and len(provider.requests) == 1
    second = (await review_workflow_approvals(parents, agents, "parent"))[0].reference
    assert second.call_id == "call-2" and second.agent_run_id == first.agent_run_id
    result = await resume_workflow_approval(
        parents, agents, second, factory, permissions={"write.allowed"},
    )
    assert result.stop_reason is WorkflowStopReason.COMPLETED
    assert len(calls) == 2 and len(provider.requests) == 2
    assert seen[0].grants is not seen[1].grants and closed == [True, True]
    assert await parents.load_checkpoint("parent") is None
    assert await agents.load_checkpoint(first.agent_run_id) is None


async def test_tui_approval_factory_continues_same_react_child_with_fresh_confirmations(tmp_path, monkeypatch):
    pytest.importorskip("textual")
    import w_agent.tui as tui_module

    async def unavailable():
        return False
    monkeypatch.setattr(tui_module.DockerSandboxProvider, "available", staticmethod(unavailable))
    root = tmp_path / ".wagent"
    parents, agents = JsonlWorkflowStore(root), JsonlRunStore(root)
    provider, calls = _provider(), []
    definition = AgentDefinition("support")
    initial = approval_agent_workflow_node(
        "answer", _loop(provider, agents, calls), definition, agents,
        tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"write.allowed"})),
    )
    await LocalWorkflowEngine(parents).start(
        DagWorkflowDefinition("approval", (initial,)), WorkflowContext("parent", input="question"),
    )

    @asynccontextmanager
    async def factory(context):
        yield DagWorkflowDefinition("approval", (approval_agent_workflow_node(
            "answer", _loop(provider, context.agent_store, calls), definition,
            context.agent_store, approval_context=context.grants,
        ),))

    monkeypatch.setattr(tui_module, "open_workflow_approval_entry", lambda _entry, context: factory(context))
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        app.query_one("#workflow-checkpoint-run").value = "parent"
        await app._review_workflow_approvals()
        assert app.query_one("#workflow-approval-call").value == ""
        child_run = None
        for call_id in ("call-1", "call-2"):
            ref = (await review_workflow_approvals(parents, agents, "parent"))[0].reference
            assert ref.call_id == call_id
            if child_run is not None:
                assert ref.agent_run_id == child_run
            child_run = ref.agent_run_id
            for suffix, value in (
                ("factory", "demo:factory"), ("node", ref.workflow_node),
                ("agent-run", ref.agent_run_id), ("agent-name", ref.agent_name),
                ("call", ref.call_id), ("tool", ref.tool_name),
                ("permissions", "write.allowed"), ("confirm", f"APPROVE {ref.call_id}"),
            ):
                app.query_one(f"#workflow-approval-{suffix}").value = value
            app.query_one("#workflow-checkpoint-load-confirm").value = "LOAD WORKFLOW"
            app.query_one("#workflow-checkpoint-resume-confirm").value = "RESUME WORKFLOW"
            await app._resume_workflow(approve=True)
            assert app.query_one("#workflow-approval-confirm").value == ""
            assert "PRIVATE" not in str(app.query_one("#workflow-checkpoint-resume-result").content)
            if call_id == "call-1":
                assert len(calls) == 1 and len(provider.requests) == 1
                await app._resume_workflow(approve=True)
                assert len(calls) == 1  # No second call without fresh confirmations.
        assert len(calls) == 2 and len(provider.requests) == 2
        assert await parents.load_checkpoint("parent") is None
        assert await agents.load_checkpoint(child_run) is None


@pytest.mark.parametrize("kind", ["dag", "graph", "python"])
async def test_approval_cascade_restarts_at_child_checkpoint_without_replaying(kind, tmp_path):
    provider = _provider()
    calls, after, offered = [], [], []
    grants = set()

    def authority(context, reference):
        offered.append(reference)
        return ToolExecutionContext(
            permissions=frozenset({"write.allowed"}), approved_call_ids=frozenset(grants)
        )

    def definition():
        store = JsonlRunStore(tmp_path)
        node = approval_agent_workflow_node(
            "answer", _loop(provider, store, calls), AgentDefinition("support"), store,
            tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"write.allowed"})),
            approval_context=authority,
        )
        return _workflow(kind, node, after)

    workflow = definition()
    engine = LocalWorkflowEngine(JsonlWorkflowStore(tmp_path))
    paused = await engine.start(workflow, WorkflowContext("parent", input="PRIVATE_PROMPT"))
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert not paused.completed_nodes and not paused.outputs
    assert calls == after == []
    assert len(provider.requests) == 1
    assert any(event.type is WorkflowEventType.NODE_SUSPENDED for event in paused.events)
    assert not any(event.type is WorkflowEventType.NODE_COMPLETED for event in paused.events)
    checkpoint = await engine.store.load_checkpoint("parent")
    link = AgentWorkflowApproval.from_dict(checkpoint.state["_w_agent_approval:answer"])
    assert link.call_id == "call-1"
    assert "PRIVATE" not in repr(link.to_dict()) + repr(paused.events)

    # Reconstructed objects use the same two stores; an absent/wrong grant does no work.
    workflow = definition()
    engine = LocalWorkflowEngine(JsonlWorkflowStore(tmp_path))
    grants.add("unrelated")
    assert (await engine.resume(workflow, "parent")).stop_reason is WorkflowStopReason.PAUSED
    assert len(provider.requests) == 1 and calls == []

    # Even granting both IDs to this callback forwards only the current pending ID.
    grants.update({"call-1", "call-2"})
    second = await engine.resume(workflow, "parent")
    assert second.stop_reason is WorkflowStopReason.PAUSED
    assert calls == ["PRIVATE_ARGUMENT"] and after == []
    assert len(provider.requests) == 1
    checkpoint = await engine.store.load_checkpoint("parent")
    second_link = AgentWorkflowApproval.from_dict(checkpoint.state["_w_agent_approval:answer"])
    assert second_link.agent_run_id == link.agent_run_id and second_link.call_id == "call-2"
    completed = await engine.resume(workflow, "parent")
    assert completed.stop_reason is WorkflowStopReason.COMPLETED
    assert calls == ["PRIVATE_ARGUMENT", "PRIVATE_ARGUMENT"]
    assert after == ([] if kind == "python" else ["after"])
    assert len(provider.requests) == 2
    assert [ref.call_id for ref in offered] == ["call-1", "call-1", "call-2"]
    assert await engine.store.load_checkpoint("parent") is None
    assert await JsonlRunStore(tmp_path).load_checkpoint(link.agent_run_id) is None
    assert completed.state["_w_agent_approval:answer"] is None


@pytest.mark.parametrize("damage", ["missing", "definition", "claimed", "call-id"])
async def test_changed_child_is_not_replayed_or_implicitly_approved(tmp_path, damage):
    provider, calls = _provider(), []
    store = JsonlRunStore(tmp_path)
    node = approval_agent_workflow_node(
        "answer", _loop(provider, store, calls), AgentDefinition("support"), store,
        tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"write.allowed"})),
    )
    workflow = DagWorkflowDefinition("approval", (node,))
    engine = LocalWorkflowEngine(JsonlWorkflowStore(tmp_path))
    await engine.start(workflow, WorkflowContext("parent", input="question"))
    parent = await engine.store.load_checkpoint("parent")
    link = AgentWorkflowApproval.from_dict(parent.state["_w_agent_approval:answer"])
    child = await store.load_checkpoint(link.agent_run_id)
    if damage == "missing":
        await store.delete_checkpoint(link.agent_run_id)
    elif damage == "definition":
        await store.save_checkpoint(replace(child, definition=AgentDefinition("changed")))
    elif damage == "claimed":
        await store.save_checkpoint(replace(child, status=CheckpointStatus.RESUMING))
    else:
        await store.save_checkpoint(replace(child, pending_tool_call=replace(
            child.pending_tool_call, id="changed-id"
        )))
    failed = await engine.resume(workflow, "parent")
    assert failed.stop_reason is WorkflowStopReason.FAILED
    assert calls == [] and len(provider.requests) == 1
    assert (await engine.store.load_checkpoint("parent")).status is WorkflowCheckpointStatus.RESUMING


async def test_parallel_suspend_commits_siblings_without_unlocking_dependents(tmp_path):
    calls = []
    ready = False

    def pending(context):
        calls.append("pending")
        return WorkflowNodeResult(output="done") if ready else WorkflowNodeResult(
            pause=True, suspend=True, state_updates={"reference": "checkpoint-id"}
        )

    def sibling(context):
        calls.append("sibling")
        return "sibling-result"

    workflow = DagWorkflowDefinition(
        "batch", (WorkflowNode("pending", pending), WorkflowNode("sibling", sibling),
                  WorkflowNode("join", lambda _: calls.append("join"))),
        {"join": ("pending", "sibling")},
    )
    engine = LocalWorkflowEngine(JsonlWorkflowStore(tmp_path), max_parallel_nodes=2)
    paused = await engine.start(workflow, WorkflowContext("parent"))
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert paused.completed_nodes == ("sibling",)
    assert "pending" not in paused.outputs
    assert "join" not in calls
    ready = True
    completed = await engine.resume(workflow, "parent")
    assert completed.stop_reason is WorkflowStopReason.COMPLETED
    assert calls == ["pending", "sibling", "pending", "join"]


async def test_host_grants_drive_exact_parent_resume_once_per_pending_call(tmp_path):
    provider, calls = _provider(), []
    agent_store = JsonlRunStore(tmp_path)
    grants = WorkflowApprovalGrants()
    node = approval_agent_workflow_node(
        "answer", _loop(provider, agent_store, calls), AgentDefinition("support"), agent_store,
        tool_context=lambda _: ToolExecutionContext(permissions=frozenset({"write.allowed"})),
        approval_context=grants,
    )
    workflow = DagWorkflowDefinition("approval", (node,))
    engine = LocalWorkflowEngine(JsonlWorkflowStore(tmp_path))
    await engine.start(workflow, WorkflowContext("parent", input="question"))
    review = (await review_workflow_approvals(engine.store, agent_store, "parent"))[0]
    parent = await engine.store.load_checkpoint("parent")
    grants.grant(review.reference, scope=parent.scope, permissions={"write.allowed"})
    second = await engine.resume(workflow, "parent")
    assert second.stop_reason is WorkflowStopReason.PAUSED
    assert len(calls) == 1 and len(provider.requests) == 1
    # The consumed call-1 grant cannot release the new call-2 boundary.
    await engine.resume(workflow, "parent")
    assert len(calls) == 1 and len(provider.requests) == 1
    review = (await review_workflow_approvals(engine.store, agent_store, "parent"))[0]
    assert review.reference.call_id == "call-2"
    grants.grant(review.reference, scope=parent.scope, permissions={"write.allowed"})
    completed = await engine.resume(workflow, "parent")
    assert completed.stop_reason is WorkflowStopReason.COMPLETED
    assert len(calls) == 2 and len(provider.requests) == 2


@pytest.mark.parametrize("kwargs", [
    {"suspend": True}, {"pause": True, "suspend": True, "output": "not-completed"},
    {"pause": True, "suspend": True, "next_node": "other"}, {"suspend": "true"},
])
def test_invalid_suspension_results_are_rejected(kwargs):
    with pytest.raises(ValueError):
        WorkflowNodeResult(**kwargs)
