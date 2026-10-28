import json

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button, Input

from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.tui_knowledge_sync import KnowledgeSyncPanel


@pytest.mark.asyncio
async def test_structural_tui_preview_locked_save_and_default_legacy(tmp_path):
    (tmp_path / "a.md").write_text("First sentence. 中文🙂重复。Repeat. Repeat.", encoding="utf-8")
    class TestApp(App):
        def compose(self):
            yield KnowledgeSyncPanel(tmp_path)
    app = TestApp()
    async with app.run_test():
        panel = app.query_one(KnowledgeSyncPanel)
        assert panel.query_one("#ks-splitter", Input).value == "utf8"
        assert panel.query_one("#ks-overlap", Input).value == "0"
        def fields(**values):
            for key, value in values.items():
                panel.query_one("#ks-" + key.replace("_", "-"), Input).value = value
        fields(trace=str(tmp_path / "trace.db"), root=str(tmp_path), namespace="n", version="v", paths='["a.md"]',
               chunk="24", splitter="structure", overlap="2", read="READ SYNC")
        await panel.on_button_pressed(Button.Pressed(panel.query_one("#ks-preview", Button)))
        await panel._operation_task
        preview = json.loads(panel._display)
        fields(preview_digest=preview["preview_digest"], read="READ SYNC", record="RECORD SYNC", create="CREATE SYNC")
        await panel.on_button_pressed(Button.Pressed(panel.query_one("#ks-import", Button)))
        await panel._operation_task
        assert json.loads(panel._display)["recorded"]
        trace = await SQLiteKnowledgeImportStore(tmp_path / "trace.db").load("n", "v")
        assert trace.splitter == "structure" and trace.overlap_chars == 2
        fields(overlap="9999", read="READ SYNC")
        with pytest.raises(ValueError):
            panel._capture("preview")
