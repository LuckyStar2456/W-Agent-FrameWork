import asyncio
import threading

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, TabbedContent

import w_agent.tui as tui_module
from w_agent import (
    DagWorkflowDefinition,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    SQLiteWorkflowPauseController,
    WorkflowContext,
    WorkflowNode,
    WorkflowNodeResult,
    WorkflowStopReason,
)
from w_agent.tui import WAgentTui


@pytest.fixture(autouse=True)
def disable_docker_probe(monkeypatch):
    async def unavailable():
        return False

    monkeypatch.setattr(
        tui_module.DockerSandboxProvider, "available", staticmethod(unavailable)
    )


def _authorize(app, run_id="controlled-1"):
    app.query_one("#workflow-checkpoint-run").value = run_id
    app.query_one("#workflow-checkpoint-entries").value = "example:workflow"
    app.query_one("#workflow-checkpoint-load-confirm").value = "LOAD WORKFLOW"
    app.query_one("#workflow-checkpoint-resume-confirm").value = "RESUME WORKFLOW"


@pytest.mark.asyncio
@pytest.mark.parametrize("threaded", [False, True])
async def test_tui_pause_is_responsive_bound_to_active_run_and_resumable(
    tmp_path, monkeypatch, threaded
):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = asyncio.Event()
    thread_release = threading.Event()
    calls = []

    def prepare(context):
        calls.append("prepare")
        return WorkflowNodeResult(output="SECRET_PREPARE", pause=True)

    async def async_node(context):
        calls.append("work")
        entered.set()
        await release.wait()
        return "SECRET_RESULT"

    def sync_node(context):
        calls.append("work")
        loop.call_soon_threadsafe(entered.set)
        assert thread_release.wait(timeout=5)
        return "SECRET_RESULT"

    def finish(context):
        calls.append("finish")
        return "SECRET_FINAL"

    definition = DagWorkflowDefinition(
        "controlled",
        (
            WorkflowNode("prepare", prepare),
            WorkflowNode("work", sync_node if threaded else async_node),
            WorkflowNode("finish", finish),
        ),
        {"work": ("prepare",), "finish": ("work",)},
    )
    store = JsonlWorkflowStore(tmp_path / ".wagent")
    first = await LocalWorkflowEngine(store).start(
        definition, WorkflowContext("controlled-1")
    )
    assert first.stop_reason is WorkflowStopReason.PAUSED

    monkeypatch.setattr(
        tui_module, "load_workflow_entries", lambda _: {("controlled", "1"): definition}
    )
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)) as pilot:
        app.query_one(TabbedContent).active = "checkpoints"
        await pilot.pause()
        _authorize(app)
        app.query_one("#workflow-checkpoint-threaded").value = threaded
        try:
            # The message handler must return while the workflow is still blocked.
            await asyncio.wait_for(
                app.on_button_pressed(
                    Button.Pressed(app.query_one("#workflow-checkpoint-resume", Button))
                ),
                timeout=2,
            )
            await asyncio.wait_for(entered.wait(), timeout=2)
            worker = app._workflow_worker
            active = app._active_workflow
            assert worker is not None and active is not None
            assert active.state_root == (tmp_path / ".wagent").resolve()
            assert app.query_one("#workflow-checkpoint-run").disabled
            assert app.query_one("#workflow-checkpoint-state-root").disabled
            assert app.query_one("#workflow-checkpoint-threaded").disabled
            assert app.query_one("#workflow-checkpoint-external-pause").disabled
            assert not app.query_one("#workflow-checkpoint-pause").disabled

            app._start_workflow_resume()
            await app._resume_workflow()
            assert app._workflow_worker is worker
            assert calls == ["prepare", "work"]

            # Even programmatic form edits cannot redirect the captured request.
            app.query_one("#workflow-checkpoint-run").value = "different-run"
            app.query_one("#workflow-checkpoint-state-root").value = "different-store"
            await app.on_button_pressed(
                Button.Pressed(app.query_one("#workflow-checkpoint-pause", Button))
            )
            assert active.control.is_pause_requested("controlled-1")
            assert not active.control.is_pause_requested("different-run")
            assert "Pause requested for controlled-1" in str(
                app.query_one("#workflow-control-status").content
            )
            assert not worker.is_finished
            assert app.query_one("#workflow-checkpoint-pause").disabled
            app.query_one("#workflow-checkpoint-run").value = "controlled-1"
            app.query_one("#workflow-checkpoint-state-root").value = ".wagent"
        finally:
            release.set()
            thread_release.set()
        await asyncio.wait_for(worker.wait(), timeout=5)
        assert app._active_workflow is None
        assert not active.control.is_pause_requested("controlled-1")
        assert not app.query_one("#workflow-checkpoint-run").disabled
        assert app.query_one("#workflow-checkpoint-pause").disabled
        assert calls == ["prepare", "work"]
        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        events = str(app.query_one("#workflow-checkpoint-events").content)
        assert "Stop: paused" in result
        assert "source=external-request" in events
        assert "SECRET" not in result + events
        assert app.query_one("#workflow-checkpoint-load-confirm").value == ""
        assert app.query_one("#workflow-checkpoint-resume-confirm").value == ""

        await app._resume_workflow()
        assert calls == ["prepare", "work"]
        _authorize(app)
        await app._resume_workflow()
        assert calls == ["prepare", "work", "finish"]
        assert "Stop: completed" in str(
            app.query_one("#workflow-checkpoint-resume-result").content
        )


@pytest.mark.asyncio
async def test_tui_failed_workflow_load_releases_controls_without_error_body(tmp_path, monkeypatch):
    definition = DagWorkflowDefinition(
        "bad-import",
        (WorkflowNode("first", lambda _: WorkflowNodeResult(pause=True)),),
    )
    await LocalWorkflowEngine(JsonlWorkflowStore(tmp_path / ".wagent")).start(
        definition, WorkflowContext("controlled-1")
    )

    def bad_load(entries):
        raise ValueError("SECRET_PLUGIN_ERROR")

    monkeypatch.setattr(tui_module, "load_workflow_entries", bad_load)
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        await app._resume_workflow()
        assert app._active_workflow is None
        assert not app.query_one("#workflow-checkpoint-resume").disabled
        assert app.query_one("#workflow-checkpoint-pause").disabled
        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        assert "ValueError" in result
        assert "SECRET_PLUGIN_ERROR" not in result
        app._request_workflow_pause()
        assert app._active_workflow is None


@pytest.mark.asyncio
@pytest.mark.parametrize("observe_external", [False, True])
async def test_tui_external_pause_is_opt_in_captured_and_never_cleared(
    tmp_path, monkeypatch, observe_external
):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    def prepare(context):
        calls.append("prepare")
        return WorkflowNodeResult(pause=True)

    async def work(context):
        calls.append("work")
        entered.set()
        await release.wait()
        return "SECRET_WORK"

    def finish(context):
        calls.append("finish")
        return "SECRET_FINISH"

    definition = DagWorkflowDefinition(
        "external-ui",
        (WorkflowNode("prepare", prepare), WorkflowNode("work", work),
         WorkflowNode("finish", finish)),
        {"work": ("prepare",), "finish": ("work",)},
    )
    root = tmp_path / ".wagent"
    await LocalWorkflowEngine(JsonlWorkflowStore(root)).start(
        definition, WorkflowContext("controlled-1")
    )
    monkeypatch.setattr(tui_module, "load_workflow_entries", lambda _: {
        (definition.name, definition.version): definition,
    })
    external = SQLiteWorkflowPauseController(root)
    unrelated = SQLiteWorkflowPauseController(tmp_path / "unrelated")
    unrelated.request_pause("controlled-1")
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        option = app.query_one("#workflow-checkpoint-external-pause")
        assert option.value is False
        option.value = observe_external
        app._start_workflow_resume()
        try:
            await asyncio.wait_for(entered.wait(), timeout=3)
            worker = app._workflow_worker
            active = app._active_workflow
            assert worker is not None and active is not None
            assert active.observe_external_pause is observe_external
            assert option.disabled
            # Edits after launch cannot change the captured mode/root/run.
            option.value = not observe_external
            app.query_one("#workflow-checkpoint-state-root").value = "unrelated"
            app.query_one("#workflow-checkpoint-run").value = "different-run"
            external.request_pause("controlled-1")
            assert not worker.is_finished
        finally:
            release.set()
        await asyncio.wait_for(worker.wait(), timeout=5)
        assert external.is_pause_requested("controlled-1")
        assert unrelated.is_pause_requested("controlled-1")
        assert not active.control.is_pause_requested("controlled-1")
        assert not option.disabled
        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        assert "SECRET" not in result
        if observe_external:
            assert "Stop: paused" in result
            assert calls == ["prepare", "work"]
            assert "Persistent SQLite requests were not cleared" in str(
                app.query_one("#workflow-control-status").content
            )
            app.query_one("#workflow-checkpoint-state-root").value = ".wagent"
            option.value = True
            _authorize(app)
            await app._resume_workflow()
            assert calls == ["prepare", "work"]
            external.clear("controlled-1")
            _authorize(app)
            await app._resume_workflow()
            assert calls == ["prepare", "work", "finish"]
        else:
            assert "Stop: completed" in result
            assert calls == ["prepare", "work", "finish"]


@pytest.mark.asyncio
async def test_tui_unreadable_external_control_restores_widgets_without_running_nodes(
    tmp_path, monkeypatch
):
    calls = []
    definition = DagWorkflowDefinition(
        "unreadable-ui",
        (WorkflowNode("prepare", lambda _: WorkflowNodeResult(pause=True)),
         WorkflowNode("finish", lambda _: calls.append("finish"))),
        {"finish": ("prepare",)},
    )
    root = tmp_path / ".wagent"
    await LocalWorkflowEngine(JsonlWorkflowStore(root)).start(
        definition, WorkflowContext("controlled-1")
    )
    monkeypatch.setattr(tui_module, "load_workflow_entries", lambda _: {
        (definition.name, definition.version): definition,
    })
    control = SQLiteWorkflowPauseController(root)
    control.database_path.write_bytes(b"SECRET_BAD_DATABASE")
    app = WAgentTui(tmp_path)
    async with app.run_test(size=(160, 90)):
        _authorize(app)
        app.query_one("#workflow-checkpoint-external-pause").value = True
        await app._resume_workflow()
        assert calls == []
        assert app._active_workflow is None
        assert not app.query_one("#workflow-checkpoint-external-pause").disabled
        assert not app.query_one("#workflow-checkpoint-resume").disabled
        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        assert "WorkflowPauseControlError" in result
        assert "SECRET_BAD_DATABASE" not in result
        assert control.database_path.read_bytes() == b"SECRET_BAD_DATABASE"
