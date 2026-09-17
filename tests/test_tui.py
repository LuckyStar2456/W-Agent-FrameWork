import pytest

pytest.importorskip("textual")

from w_agent import CompositionManifest, encode_composition
from w_agent.tui import WAgentTui
from textual.widgets import TabbedContent


@pytest.mark.asyncio
async def test_tui_mounts_all_first_release_sections_and_inspects_code(tmp_path):
    app = WAgentTui(tmp_path)
    code = encode_composition(CompositionManifest("demo", "1.0.0"))

    async with app.run_test(size=(140, 50)) as pilot:
        assert "Workspace:" in str(app.query_one("#home-summary").content)
        assert len(app.query("TabPane")) == 9

        app.query_one(TabbedContent).active = "composition"
        await pilot.pause()
        app.query_one("#composition-code").value = code
        await pilot.click("#composition-button")
        await pilot.pause()

        rendered = str(app.query_one("#composition-result").content)
        assert '"name": "demo"' in rendered


@pytest.mark.asyncio
async def test_tui_rejects_invalid_composition_without_loading(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(TabbedContent).active = "composition"
        await pilot.pause()
        app.query_one("#composition-code").value = "invalid"
        await pilot.click("#composition-button")
        await pilot.pause()

        rendered = str(app.query_one("#composition-result").content)
        assert "Rejected: unsupported composition-code prefix" in rendered
