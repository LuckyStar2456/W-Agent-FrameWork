"""Media widgets exercise real decoding, independent consent and Replay wiring."""

import asyncio
from threading import Event

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Button, Input, Static

from w_agent.agents import JsonlRunStore, RunEvent, RunEventCursor, RunEventType, RunReplaySnapshot
from w_agent.media_display import MediaDisplayError, MediaPreview
from w_agent.tui_media import ReplayMediaPanel, replay_media_blocks
from w_agent.tui_replay import ReplayPanel
from w_agent.session_replay import SessionReplaySnapshot, SessionRunView
from tests.test_media_display import block, png, wav


def snapshot(*blocks):
    return RunReplaySnapshot(RunEventCursor("run"), "test/1", {
        "blocks": [{"kind": "media", "media": value} for value in blocks]})


class MediaApp(App):
    def __init__(self, tmp_path, renderer=None):
        super().__init__()
        self.panel = ReplayMediaPanel(tmp_path, renderer=renderer)

    def compose(self):
        yield self.panel


async def press(panel, action):
    panel.on_button_pressed(Button.Pressed(panel.query_one(f"#media-{action}", Button)))
    if panel._operation_task:
        await asyncio.wait_for(panel._operation_task, 5)


@pytest.mark.asyncio
async def test_real_image_audio_preview_and_explicit_export(tmp_path):
    app = MediaApp(tmp_path)
    async with app.run_test(size=(120, 60)):
        app.panel.set_snapshot(snapshot(block(png()), block(wav(), "audio", "audio/wav")))
        assert "Contents hidden" in str(app.query_one("#media-catalog", Static).render())
        await press(app.panel, "view")
        assert "type VIEW MEDIA" in str(app.query_one("#media-preview", Static).render())
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        await press(app.panel, "view")
        assert "@@@@@@@@" in str(app.query_one("#media-preview", Static).render())
        assert not app.query_one("#media-confirm", Input).value
        await press(app.panel, "next")
        assert "@@@@@@@@" not in str(app.query_one("#media-preview", Static).render())
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        await press(app.panel, "view")
        assert "8000 Hz" in str(app.query_one("#media-preview", Static).render())
        app.query_one("#media-directory", Input).value = str(tmp_path)
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        await press(app.panel, "export")
        assert not list(tmp_path.iterdir())
        app.query_one("#media-confirm", Input).value = "EXPORT MEDIA"
        await press(app.panel, "export")
        assert len(list(tmp_path.glob("*.wav"))) == 1
        app.panel.set_snapshot(None)
        assert not app.panel._blocks


@pytest.mark.asyncio
async def test_custom_renderer_sanitized_and_metadata_not_upgraded(tmp_path):
    class Custom:
        def render(self, item, *, confirmed=False):
            assert confirmed is True
            assert "data_base64" not in item
            return MediaPreview("CUSTOM\x1b\u202e", "X\x1b[2J\n" + "A" * 200)
    app = MediaApp(tmp_path, Custom())
    async with app.run_test():
        metadata = block(png())
        del metadata["data_base64"]
        app.panel.set_snapshot(snapshot(metadata))
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        await press(app.panel, "view")
        text = str(app.query_one("#media-preview", Static).render())
        assert "CUSTOM??" in text and "\x1b" not in text
        assert "A" * 129 not in text


def test_catalog_not_recursive_and_is_bounded():
    value = snapshot(block(png()), block(png()))
    with pytest.raises(MediaDisplayError, match="limit"):
        replay_media_blocks(value, limit=1)
    unrelated = RunReplaySnapshot(RunEventCursor("run"), "test/1", {"tool_results": [block(png())]})
    assert replay_media_blocks(unrelated) == ()


def test_session_input_and_run_output_catalog():
    output, recorded_input = block(png()), block(wav(), "audio", "audio/wav")
    view = SessionRunView(snapshot(output), ({"input_blocks": [recorded_input]},))
    session = SessionReplaySnapshot("session", "test/1", ("run",), (view,))
    catalog = replay_media_blocks(session)
    assert [item["kind"] for item in catalog] == ["image", "audio"]


@pytest.mark.asyncio
async def test_clear_discards_inflight_preview(tmp_path):
    entered, release = Event(), Event()
    class Slow:
        def render(self, item, *, confirmed=False):
            entered.set()
            assert release.wait(5)
            return MediaPreview("PRIVATE stale preview")
    app = MediaApp(tmp_path, Slow())
    async with app.run_test():
        app.panel.set_snapshot(snapshot(block(png())))
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        app.panel.on_button_pressed(Button.Pressed(app.query_one("#media-view", Button)))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            app.panel.set_snapshot(None)
        finally:
            release.set()
        await asyncio.wait_for(app.panel._operation_task, 5)
        assert "PRIVATE" not in str(app.query_one("#media-preview", Static).render())


@pytest.mark.asyncio
async def test_replay_read_wires_media_and_clear_removes_it(tmp_path):
    await JsonlRunStore(tmp_path / ".wagent").append(RunEvent(
        1, RunEventType.MODEL_OUTPUT_BLOCK, "run", {"step": 1, "block_index": 0, "block": block(png())}))
    class ReplayApp(App):
        def compose(self):
            yield ReplayPanel(tmp_path)
    app = ReplayApp()
    async with app.run_test(size=(120, 100)) as pilot:
        panel = app.query_one(ReplayPanel)
        app.query_one("#replay-id", Input).value = "run"
        app.query_one("#replay-media", Input).value = "content"
        await pilot.pause()
        app.query_one("#replay-confirm", Input).value = "VIEW CONTENT"
        panel.start_read()
        await panel._worker.wait()
        assert len(panel.media_panel._blocks) == 1
        assert "hidden" in str(app.query_one("#media-preview", Static).render())
        app.query_one("#media-confirm", Input).value = "VIEW MEDIA"
        await press(panel.media_panel, "view")
        assert "@@@@@@@@" in str(app.query_one("#media-preview", Static).render())
        panel.clear_view()
        assert not panel.media_panel._blocks
