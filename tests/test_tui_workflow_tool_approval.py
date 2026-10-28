"""TUI chain approval regressions."""

import asyncio
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("textual")
from textual.worker import WorkerCancelled

import w_agent.tui as tui_module
from w_agent import (
    AgentDefinition, AgentWorkflowApproval, JsonlRunStore, JsonlWorkflowStore,
    RunCheckpoint, RunResult, ScopePath, StopReason, ToolCall, ToolContinuation,
    WorkflowCheckpoint, WorkflowCheckpointStatus, WorkflowEvent, WorkflowEventType,
    WorkflowKind, WorkflowNodeContext, WorkflowToolReference,
)


@pytest.fixture(autouse=True)
def no_docker_probe(monkeypatch):
    async def unavailable():
        return False
    monkeypatch.setattr(tui_module.DockerSandboxProvider, "available", staticmethod(unavailable))


async def _seed(root):
    scope = ScopePath.application("PRIVATE_SCOPE")
    outer = WorkflowToolReference("outer", "outer-call", "workflow", "wf-run", "flow", "1", WorkflowKind.DAG, scope)
    inner = AgentWorkflowApproval("wf-run", "node", "inner", "coder", "inner-call", "write")
    parents, workflows, children = JsonlRunStore(root / "parent"), JsonlWorkflowStore(root / "workflow"), JsonlRunStore(root / "child")
    await parents.save_checkpoint(RunCheckpoint(
        "outer", AgentDefinition("parent"), scope, (), ToolCall("outer-call", "workflow", {}, scope),
        (), 1, 1, "PRIVATE_OUTPUT", schema_version=2,
        tool_continuation=ToolContinuation("w-agent.workflow-tool", {"reference": outer.to_dict(), "sequence": 1}),
    ))
    await workflows.save_checkpoint(WorkflowCheckpoint(
        "wf-run", "flow", "1", WorkflowKind.DAG, scope, "PRIVATE_INPUT",
        {"custom": inner.to_dict()}, {}, (), remaining_nodes=("node",),
        status=WorkflowCheckpointStatus.PAUSED, metadata={"_w_agent_workflow_tool": outer.to_dict()},
    ))
    await workflows.append(WorkflowEvent(1, WorkflowEventType.WORKFLOW_PAUSED, "wf-run"))
    await children.save_checkpoint(RunCheckpoint(
        "inner", AgentDefinition("coder"), scope, (), ToolCall("inner-call", "write", {"secret": "PRIVATE_ARGUMENT"}, scope),
        (), 1, 1, "",
    ))
    return workflows


async def _select(app):
    for name, value in {"parent-root": "parent", "workflow-root": "workflow", "child-root": "child",
                        "run": "outer", "state-keys": "custom"}.items():
        app.query_one(f"#chain-{name}").value = value
    await app._review_chain()
    assert app._chain_review is not None and app._chain_selection is None
    assert app.query_one("#chain-row").value == ""
    app.query_one("#chain-row").value = "1"
    app._select_chain_row()
    assert app._chain_selection is not None


def _authorize(app):
    for name, value in {
        "factory": "app:factory", "parent-permissions": "workflow.execute", "child-permissions": "write.allowed",
        "code-confirm": "LOAD AGENT", "parent-confirm": "APPROVE PARENT outer-call",
        "child-confirm": "APPROVE CHILD inner-call", "resume-confirm": "RESUME AGENT outer",
    }.items():
        app.query_one(f"#chain-{name}").value = value


def _node(context):
    ref = context.selection.child.reference
    return WorkflowNodeContext(ref.workflow_run_id, ref.workflow_node, None, {}, {}, context.selection.parent.scope, None)


@pytest.mark.parametrize("field", tui_module._CHAIN_CONFIRMATIONS)
async def test_four_exact_confirmations_required(tmp_path, monkeypatch, field):
    await _seed(tmp_path)
    def forbidden(*args):
        pytest.fail("factory must not load without four confirmations")
    monkeypatch.setattr(tui_module, "open_workflow_tool_approval_entry", forbidden)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(140, 75)):
        await _select(app)
        _authorize(app)
        app.query_one(f"#chain-{field}").value = "wrong"
        await app._resume_chain()
        assert "rejected" in str(app.query_one("#chain-result").content)
        assert not app._chain_busy


@pytest.mark.parametrize("field,value", [("child-root", "missing"), ("row", "2"), ("run", "other")])
async def test_changed_query_or_row_cannot_reuse_selection(tmp_path, monkeypatch, field, value):
    await _seed(tmp_path)
    def forbidden(*args):
        pytest.fail("changed query must not load code")
    monkeypatch.setattr(tui_module, "open_workflow_tool_approval_entry", forbidden)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(140, 75)):
        await _select(app)
        _authorize(app)
        app.query_one(f"#chain-{field}").value = value
        await app._resume_chain()
        assert "rejected" in str(app.query_one("#chain-result").content)
        assert not (tmp_path / "missing").exists()


async def test_review_hides_values_and_new_selection_discards_old_confirmations(tmp_path):
    await _seed(tmp_path)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(140, 75)):
        await _select(app)
        assert "PRIVATE" not in str(app.query_one("#chain-review-result").content)
        assert "PRIVATE" not in str(app.query_one("#chain-selected").content)
        _authorize(app)
        app._select_chain_row()
        assert all(app.query_one(f"#chain-{name}").value == "" for name in tui_module._CHAIN_CONFIRMATIONS)


async def test_stale_boundary_rejected_before_factory_and_selection_consumed(tmp_path, monkeypatch):
    workflows = await _seed(tmp_path)
    def forbidden(*args):
        pytest.fail("stale boundary must fail preflight")
    monkeypatch.setattr(tui_module, "open_workflow_tool_approval_entry", forbidden)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(140, 75)):
        await _select(app)
        _authorize(app)
        await workflows.append(WorkflowEvent(2, WorkflowEventType.WORKFLOW_PAUSED, "wf-run"))
        await app._resume_chain()
        assert "WorkflowToolApprovalError" in str(app.query_one("#chain-result").content)
        assert app._chain_selection is None and app._chain_review is None
        assert all(app.query_one(f"#chain-{name}").value == "" for name in tui_module._CHAIN_CONFIRMATIONS)
        assert not app.query_one("#chain-resume").disabled


@pytest.mark.parametrize("cancel", [False, True])
async def test_background_request_is_frozen_deduplicated_and_grants_cleared(tmp_path, monkeypatch, cancel):
    await _seed(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    seen, calls, closed = [], [], []
    @asynccontextmanager
    async def factory(context):
        seen.append(context)
        class Loop:
            store = context.parent_store
            async def resume(self, run_id, *, tool_context, cancellation):
                entered.set()
                await release.wait()
                calls.append((run_id, tool_context, context.grants(_node(context), context.selection.child.reference)))
                return RunResult(run_id, StopReason.NEEDS_APPROVAL, "PRIVATE_OUTPUT", (), (), 1, 1)
        try:
            yield Loop()
        finally:
            closed.append(not context.grants(_node(context), context.selection.child.reference).approved_call_ids)
    monkeypatch.setattr(tui_module, "open_workflow_tool_approval_entry", lambda entry, ctx: factory(ctx))
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(140, 75)):
        await _select(app)
        _authorize(app)
        app._start_chain_operation(review=False)
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            worker = app._workflow_worker
            assert worker is not None and app._chain_busy
            assert app.query_one("#chain-run").disabled and app.query_one("#workflow-approval-resume").disabled
            app._start_chain_operation(review=False)
            app._start_chain_operation(review=True)
            app._start_workflow_resume()
            assert app._workflow_worker is worker
            # Application code can mutate disabled controls; captured values must win.
            app.query_one("#chain-run").value = "different"
            app.query_one("#chain-parent-permissions").value = "different"
            if cancel:
                worker.cancel()
                with pytest.raises(WorkerCancelled):
                    await worker.wait()
            else:
                release.set()
                await asyncio.wait_for(worker.wait(), timeout=3)
                run, outer, inner = calls[0]
                assert run == "outer" and outer.permissions == {"workflow.execute"}
                assert inner.permissions == {"write.allowed"}
                assert "PRIVATE" not in str(app.query_one("#chain-result").content)
            assert closed == [True] and not app._chain_busy
            assert app._chain_review is None and app._chain_selection is None
            assert not app.query_one("#chain-resume").disabled
        finally:
            release.set()
