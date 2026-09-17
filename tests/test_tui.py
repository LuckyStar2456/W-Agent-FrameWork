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
        assert len(app.query("TabPane")) == 10

        app.query_one(TabbedContent).active = "composition"
        await pilot.pause()
        app.query_one("#composition-code").value = code
        await pilot.click("#composition-button")
        await pilot.pause()

        rendered = str(app.query_one("#composition-result").content)
        assert '"name": "demo"' in rendered


@pytest.mark.asyncio
async def test_tui_creates_archives_and_unarchives_local_session(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 55)) as pilot:
        app.query_one(TabbedContent).active = "sessions"
        await pilot.pause()
        app.query_one("#session-title").value = "Coding task"
        await pilot.click("#session-create")
        await pilot.pause()

        created = str(app.query_one("#session-result").content)
        session_id = app.query_one("#session-id").value
        assert "Coding task" in created
        assert session_id.startswith("session-")

        await pilot.click("#session-archive")
        await pilot.pause()
        assert "| archived | Coding task" in str(
            app.query_one("#session-result").content
        )

        await pilot.click("#session-unarchive")
        await pilot.pause()
        assert "| active | Coding task" in str(
            app.query_one("#session-result").content
        )


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


@pytest.mark.asyncio
async def test_tui_run_requires_explicit_confirmation_before_config_or_network(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 55)) as pilot:
        app.query_one(TabbedContent).active = "run"
        await pilot.pause()
        app.query_one("#run-prompt").value = "hello"
        await pilot.click("#run-button")
        await pilot.pause()

        rendered = str(app.query_one("#run-result").content)
        assert "type RUN to authorize" in rendered

        app.query_one("#run-confirm").value = "RUN"
        await pilot.pause()
        await app._run_configured_agent()
        await pilot.pause()
        assert app.query_one("#run-confirm").value == ""
        assert "config" in str(app.query_one("#run-result").content).lower()
