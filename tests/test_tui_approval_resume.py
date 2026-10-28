"""TUI approval-recovery regressions."""

import asyncio
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("textual")
from textual.widgets import Button

import w_agent.tui as tui_module
from w_agent import (
    AgentDefinition, AgentWorkflowApproval, DagWorkflowDefinition, JsonlRunStore,
    JsonlWorkflowStore, RunCheckpoint, ScopePath, SQLiteWorkflowPauseController,
    ToolCall, WorkflowCheckpoint, WorkflowCheckpointStatus, WorkflowKind,
    WorkflowNode, WorkflowNodeContext,
)


@pytest.fixture(autouse=True)
def disable_docker_probe(monkeypatch):
    async def unavailable():
        return False
    monkeypatch.setattr(tui_module.DockerSandboxProvider, "available", staticmethod(unavailable))


async def _fixtures(workspace):
    root = workspace / ".wagent"
    scope = ScopePath.application()
    ref = AgentWorkflowApproval("parent", "answer", "child", "coding", "call", "write")
    parents, agents = JsonlWorkflowStore(root), JsonlRunStore(workspace / "agent-state")
    parent = WorkflowCheckpoint(
        "parent", "workflow", "1", WorkflowKind.DAG, scope, "PRIVATE_INPUT",
        {"custom": ref.to_dict()}, {}, (), remaining_nodes=("answer", "after"),
        status=WorkflowCheckpointStatus.PAUSED,
    )
    child = RunCheckpoint(
        "child", AgentDefinition("coding"), scope, (),
        ToolCall("call", "write", {"secret": "PRIVATE_ARGUMENT"}), (), 1, 0, "",
    )
    await parents.save_checkpoint(parent)
    await agents.save_checkpoint(child)
    return parents, agents, parent, child, ref


def _authorize(app):
    values = {
        "workflow-checkpoint-run": "parent",
        "workflow-checkpoint-load-confirm": "LOAD WORKFLOW",
        "workflow-checkpoint-resume-confirm": "RESUME WORKFLOW",
        "workflow-approval-agent-root": "agent-state",
        "workflow-approval-state-keys": "custom",
        "workflow-approval-factory": "demo:factory",
        "workflow-approval-node": "answer",
        "workflow-approval-agent-run": "child",
        "workflow-approval-agent-name": "coding",
        "workflow-approval-call": "call",
        "workflow-approval-tool": "write",
        "workflow-approval-permissions": "write.allowed",
        "workflow-approval-confirm": "APPROVE call",
    }
    for widget, value in values.items():
        app.query_one(f"#{widget}").value = value


def _context(assembly):
    return WorkflowNodeContext("parent", "answer", None, {}, {}, assembly.scope, None)


@pytest.mark.parametrize("field", [
    "workflow-checkpoint-load-confirm", "workflow-checkpoint-resume-confirm", "workflow-approval-confirm",
])
async def test_each_confirmation_is_required_before_import(tmp_path, monkeypatch, field):
    parents, agents, parent, child, _ref = await _fixtures(tmp_path)
    def forbidden(*_args):
        pytest.fail("missing authorization must not import code")
    monkeypatch.setattr(tui_module, "open_workflow_approval_entry", forbidden)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        app.query_one(f"#{field}").value = "wrong"
        await app._resume_workflow(approve=True)
        assert app._active_workflow is None
        assert "Rejected" in str(app.query_one("#workflow-checkpoint-resume-result").content)
        assert await parents.load_checkpoint("parent") == parent
        assert await agents.load_checkpoint("child") == child


async def test_stale_call_rejected_before_factory_and_confirmations_consumed(tmp_path, monkeypatch):
    await _fixtures(tmp_path)
    def forbidden(*_args):
        pytest.fail("stale approval must fail before factory import")
    monkeypatch.setattr(tui_module, "open_workflow_approval_entry", forbidden)
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        app.query_one("#workflow-approval-call").value = "old"
        app.query_one("#workflow-approval-confirm").value = "APPROVE old"
        await app._resume_workflow(approve=True)
        assert "WorkflowApprovalResumeError" in str(app.query_one("#workflow-checkpoint-resume-result").content)
        for widget in ("workflow-checkpoint-load-confirm", "workflow-checkpoint-resume-confirm", "workflow-approval-confirm"):
            assert app.query_one(f"#{widget}").value == ""
        assert not app.query_one("#workflow-approval-resume").disabled
        assert app._active_workflow is None


@pytest.mark.parametrize("pause_origin", ["ui", "sqlite"])
async def test_background_recovery_captures_fields_and_preserves_external_requests(tmp_path, monkeypatch, pause_origin):
    parents, agents, parent, child, ref = await _fixtures(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    seen, calls, closed = [], [], []
    @asynccontextmanager
    async def factory(assembly):
        seen.append(assembly)
        async def answer(context):
            authority = assembly.grants(context, assembly.reference)
            calls.append(authority)
            entered.set()
            await release.wait()
            return "PRIVATE_OUTPUT"
        try:
            yield DagWorkflowDefinition("workflow", (
                WorkflowNode("answer", answer), WorkflowNode("after", lambda _: calls.append("after")),
            ), {"after": ("answer",)})
        finally:
            closed.append(True)
    monkeypatch.setattr(tui_module, "open_workflow_approval_entry", lambda _entry, context: factory(context))
    external = SQLiteWorkflowPauseController(tmp_path / ".wagent")
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        app.query_one("#workflow-checkpoint-external-pause").value = True
        await app.on_button_pressed(Button.Pressed(app.query_one("#workflow-approval-resume", Button)))
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            worker, active = app._workflow_worker, app._active_workflow
            assert worker is not None and active is not None
            for suffix in ("factory", "node", "agent-run", "call", "permissions", "agent-root", "resume", "review"):
                assert app.query_one(f"#workflow-approval-{suffix}").disabled
            assert app.query_one("#workflow-checkpoint-resume").disabled
            app._start_workflow_resume()
            app._start_workflow_resume(approve=True)
            assert app._workflow_worker is worker
            # Disabled input values may still be mutated by application code.
            app.query_one("#workflow-checkpoint-run").value = "other"
            app.query_one("#workflow-approval-call").value = "other"
            app.query_one("#workflow-approval-agent-root").value = "missing"
            if pause_origin == "ui":
                app._request_workflow_pause()
                assert active.control.is_pause_requested("parent")
                assert not active.control.is_pause_requested("other")
            else:
                external.request_pause("parent")
        finally:
            release.set()
        await asyncio.wait_for(worker.wait(), timeout=5)
        assert closed == [True] and len(calls) == 1
        assert calls[0].approved_call_ids == frozenset({"call"})
        assert calls[0].permissions == frozenset({"write.allowed"})
        assert not seen[0].grants(_context(seen[0]), ref).approved_call_ids
        assert not active.control.is_pause_requested("parent")
        assert external.is_pause_requested("parent") is (pause_origin == "sqlite")
        assert app._active_workflow is None
        assert not app.query_one("#workflow-approval-resume").disabled
        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        events = str(app.query_one("#workflow-checkpoint-events").content)
        assert "Stop: paused" in result and "PRIVATE" not in result + events
        assert (await parents.load_checkpoint("parent")).completed_nodes == ("answer",)


@pytest.mark.parametrize("cancel", [False, True])
async def test_factory_failure_or_worker_cancel_closes_and_revokes(tmp_path, monkeypatch, cancel):
    await _fixtures(tmp_path)
    entered = asyncio.Event()
    seen, closed = [], []
    @asynccontextmanager
    async def factory(assembly):
        seen.append(assembly)
        try:
            # Model resource initialization may await or fail during assembly.
            assembly.grants.grant(assembly.reference, scope=assembly.scope)
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise ValueError("PRIVATE_FACTORY_FAILURE")
            yield  # pragma: no cover - declares an async context manager
        finally:
            closed.append(True)
    monkeypatch.setattr(tui_module, "open_workflow_approval_entry", lambda _entry, context: factory(context))
    app = tui_module.WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        app._start_workflow_resume(approve=True)
        await asyncio.wait_for(entered.wait(), timeout=3)
        worker = app._workflow_worker
        if cancel:
            worker.cancel()
            with pytest.raises(tui_module.WorkerCancelled):
                await asyncio.wait_for(worker.wait(), timeout=5)
        else:
            await asyncio.wait_for(worker.wait(), timeout=5)
        assert closed == [True]
        assert not seen[0].grants(_context(seen[0]), seen[0].reference).approved_call_ids
        assert not app.query_one("#workflow-approval-resume").disabled
        assert app._active_workflow is None
        assert "PRIVATE" not in str(app.query_one("#workflow-checkpoint-resume-result").content)
