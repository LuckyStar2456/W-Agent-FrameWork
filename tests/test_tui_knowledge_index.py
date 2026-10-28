"""Draft index-panel consent/capture/cancellation tests; unexecuted."""

import asyncio

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button

import w_agent.tui_knowledge_index as panel_module
from w_agent.tui_knowledge_index import KnowledgeIndexPanel, _CONFIRMATIONS


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def compose(self):
        yield KnowledgeIndexPanel(self.workspace)


@pytest.mark.asyncio
async def test_capture_exact_decision_and_consume_confirmations(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeIndexPanel)
        for key, value in {
            "manifest": "a" * 64, "plan": "b" * 64, "attempt": "a", "expected": "unknown",
            "outcome": "not-applied", "decision": "r", "evidence": "PRIVATE", "actor": "me",
        }.items():
            app.query_one(f"#ki-{key}").value = value
        app.query_one("#ki-read").value = "READ INDEX"
        with pytest.raises(ValueError):
            panel._capture(True)
        assert app.query_one("#ki-read").value == ""
        for key in ("read", "write", "inactive"):
            app.query_one(f"#ki-{key}").value = _CONFIRMATIONS[key]
        request = panel._capture(True)
        app.query_one("#ki-attempt").value = "changed"
        assert request.decision.attempt_id == "a"
        assert request.decision.evidence_ref == "PRIVATE"
        assert request.include_details is False
        assert all(app.query_one(f"#ki-{key}").value == "" for key in _CONFIRMATIONS)
        for key in ("read", "write", "inactive"):
            app.query_one(f"#ki-{key}").value = _CONFIRMATIONS[key]
        with pytest.raises(ValueError):
            panel._capture(False)  # Inspection never silently accepts write consent.


@pytest.mark.asyncio
async def test_panel_locks_and_cancellation_never_claims_rollback(tmp_path, monkeypatch):
    entered = asyncio.Event()

    async def blocked(request):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(panel_module, "review_local_knowledge_index", blocked)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeIndexPanel)
        app.query_one("#ki-read").value = "READ INDEX"
        app.query_one("#ki-manifest").value = "a" * 64
        await panel.on_button_pressed(Button.Pressed(app.query_one("#ki-inspect", Button)))
        await entered.wait()
        assert app.query_one("#ki-manifest").disabled
        await panel.on_button_pressed(Button.Pressed(app.query_one("#ki-cancel", Button)))
        await panel._operation_task
        assert not app.query_one("#ki-manifest").disabled
        assert "may be committed" in str(app.query_one("#ki-result").content)


@pytest.mark.asyncio
async def test_cancel_before_worker_starts_unlocks_inputs(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgeIndexPanel)
        app.query_one("#ki-read").value = "READ INDEX"
        app.query_one("#ki-manifest").value = "a" * 64
        await panel.on_button_pressed(Button.Pressed(app.query_one("#ki-inspect", Button)))
        panel._operation_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await panel._operation_task
        assert not app.query_one("#ki-manifest").disabled
