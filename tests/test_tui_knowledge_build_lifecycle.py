"""Catalog navigation and explicit predecessor capture in live Textual panels."""

import asyncio

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button

import w_agent.tui_knowledge_builds as builds
import w_agent.tui_knowledge_index as journals


@pytest.mark.asyncio
@pytest.mark.parametrize("module,panel_type,prefix,word,function", [
    (builds, builds.KnowledgeBuildsPanel, "kb", "READ BUILD INPUTS", "list_local_knowledge_builds"),
    (journals, journals.KnowledgeIndexPanel, "ki", "READ INDEX", "list_local_knowledge_journals"),
])
async def test_catalog_button_without_known_identity(tmp_path, monkeypatch, module, panel_type, prefix, word, function):
    called = asyncio.Event()

    async def listing(database, **options):
        assert options["confirm_read"] is True
        called.set()
        return {"entries": []}

    monkeypatch.setattr(module, function, listing)

    class CatalogApp(App):
        def compose(self):
            yield panel_type(tmp_path)

    app = CatalogApp()
    async with app.run_test():
        panel = app.query_one(panel_type)
        app.query_one(f"#{prefix}-read").value = word
        await panel.on_button_pressed(Button.Pressed(app.query_one(f"#{prefix}-list", Button)))
        await asyncio.wait_for(called.wait(), 5)
        await panel._operation_task
        assert app.query_one(f"#{prefix}-read").value == ""


@pytest.mark.asyncio
async def test_retry_predecessor_is_captured_with_other_approvals(tmp_path):
    from test_tui_knowledge_builds import PanelApp, fields, consent

    app = PanelApp(tmp_path)
    async with app.run_test():
        fields(app)
        app.query_one("#kb-previous-attempt").value = "prior-attempt"
        consent(app, "read", "code", "write", "record")
        request = app.query_one(builds.KnowledgeBuildsPanel)._capture("execute")
        app.query_one("#kb-previous-attempt").value = "later-edit"
        assert request.previous_attempt_id == "prior-attempt"
