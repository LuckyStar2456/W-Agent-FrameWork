"""Draft local knowledge panel consent/capture/cancellation tests; unexecuted."""

import asyncio

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button

import w_agent.tui_knowledge as panel_module
from w_agent.tui_knowledge import KnowledgePanel


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def compose(self):
        yield KnowledgePanel(self.workspace)


@pytest.mark.asyncio
async def test_capture_consumes_confirmations_and_pins_values(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePanel)
        with pytest.raises(ValueError):
            panel._capture("list")
        app.query_one("#km-read").value = "READ KNOWLEDGE"
        app.query_one("#km-namespace").value = "manual"
        request = panel._capture("list")
        app.query_one("#km-namespace").value = "different"
        assert request.namespace == "manual"
        assert app.query_one("#km-read").value == ""
        app.query_one("#km-read").value = "READ KNOWLEDGE"
        app.query_one("#km-write").value = "WRITE KNOWLEDGE"
        with pytest.raises(ValueError):
            panel._capture("list")
        assert app.query_one("#km-write").value == ""


@pytest.mark.asyncio
async def test_running_operation_locks_fields_and_cancel_does_not_claim_rollback(tmp_path, monkeypatch):
    entered = asyncio.Event()

    async def blocked(request):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(panel_module, "manage_local_knowledge", blocked)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePanel)
        app.query_one("#km-read").value = "READ KNOWLEDGE"
        await panel.on_button_pressed(Button.Pressed(app.query_one("#km-list", Button)))
        await entered.wait()
        assert app.query_one("#km-database").disabled
        assert not app.query_one("#km-cancel").disabled
        await panel.on_button_pressed(Button.Pressed(app.query_one("#km-cancel", Button)))
        await panel._operation_task
        assert not app.query_one("#km-database").disabled
        assert "may have completed" in str(app.query_one("#km-result").content)


@pytest.mark.asyncio
async def test_cancel_before_task_starts_unlocks_panel(tmp_path):
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.query_one(KnowledgePanel)
        app.query_one("#km-read").value = "READ KNOWLEDGE"
        await panel.on_button_pressed(Button.Pressed(app.query_one("#km-list", Button)))
        panel._operation_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await panel._operation_task
        assert not app.query_one("#km-database").disabled
        assert "may have completed" in str(app.query_one("#km-result").content)
