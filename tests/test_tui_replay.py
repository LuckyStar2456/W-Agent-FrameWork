"""Draft replay-panel coverage."""

import asyncio
from dataclasses import replace
from threading import Event

import pytest

pytest.importorskip("textual")
from textual.app import App
from textual.widgets import Checkbox, Input, Static

import w_agent.tui_replay as replay_ui
from w_agent import (
    JsonlRunStore, JsonSessionStore, MessageRole, RunEvent, RunEventType,
    SessionMessage, SessionRecord, SessionRunRecord, TokenUsage,
    ImageContent, ModelMessage, StandardSessionInputRecorder,
)
from w_agent.tui_replay import ReplayPanel, ReplayReadError, ReplaySelection, read_replay_view


async def _seed(tmp_path):
    root = tmp_path / ".wagent"
    store = JsonlRunStore(root)
    for key in ("first", "second"):
        for index, (kind, data) in enumerate([
            (RunEventType.MODEL_TEXT_DELTA, {"step": 1, "block_index": 0, "text": "PRIVATE_MODEL\x1b[2J\u202e[red]"}),
            (RunEventType.TOOL_COMPLETED, {"step": 1, "outcome": "succeeded", "name": "PRIVATE_TOOL",
                                          "result_recording": "recorded", "result": {"text": "PRIVATE_RESULT"}}),
            (RunEventType.TOKEN_USAGE, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
        ], 1):
            await store.append(RunEvent(index, kind, key, data, session_id="session"))
    await JsonSessionStore(root / "sessions").save(SessionRecord(
        "session", "PRIVATE_TITLE",
        messages=tuple(SessionMessage(MessageRole.USER, "PRIVATE_INPUT", key) for key in ("first", "second")),
        runs=tuple(SessionRunRecord(key, "agent", "completed", "PRIVATE_OUTPUT", TokenUsage(3, 2), True, 1, 1)
                   for key in ("first", "second")),
    ))
    return ReplaySelection("run", "first", root, root / "sessions")


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.panel = ReplayPanel(workspace)

    def compose(self):
        yield self.panel


@pytest.mark.asyncio
async def test_run_pages_and_independent_disclosures(tmp_path):
    selection = await _seed(tmp_path)
    first = await read_replay_view(selection, event_limit=1)
    final = await read_replay_view(selection, first)
    whole = await read_replay_view(selection)
    assert final.snapshot == whole.snapshot
    assert "PRIVATE" not in final.body
    assert final.snapshot.state["usage"]["total_tokens"] == 5
    results = await read_replay_view(replace(selection, results=True), confirmed=True)
    assert "PRIVATE_RESULT" in results.body and "PRIVATE_TOOL" not in results.body
    assert "PRIVATE_MODEL" not in results.body
    text = await read_replay_view(replace(selection, text=True), confirmed=True)
    assert "PRIVATE_MODEL" in text.body and "PRIVATE_RESULT" not in text.body
    assert "\x1b" not in text.body and "\u202e" not in text.body
    assert r"\u001b" in text.body and r"\u202e" in text.body


@pytest.mark.asyncio
async def test_confirmation_and_bound_selection_prevent_reuse(tmp_path, monkeypatch):
    selection = await _seed(tmp_path)
    prior = await read_replay_view(selection)
    with pytest.raises(ReplayReadError, match="Selection changed"):
        await read_replay_view(replace(selection, results=True), prior, confirmed=True)
    def forbidden(*args):
        pytest.fail("store opened before confirmation")
    monkeypatch.setattr(replay_ui, "JsonlRunStore", forbidden)
    for changes in ({"text": True}, {"tools": True}, {"results": True},
                    {"session_text": True}, {"media": "references"}, {"media": "content"}):
        with pytest.raises(ReplayReadError, match="VIEW CONTENT"):
            await read_replay_view(replace(selection, **changes))


@pytest.mark.asyncio
async def test_session_sweeps_and_input_text(tmp_path):
    selection = replace(await _seed(tmp_path), kind="session", identifier="session")
    first = await read_replay_view(selection, run_limit=1, event_limit=1)
    assert first.next_run_offset == 1
    second = await read_replay_view(selection, first, run_offset=1, run_limit=1)
    assert second.next_run_offset == 0
    final = await read_replay_view(selection, second)
    assert final.snapshot == (await read_replay_view(selection)).snapshot
    assert "PRIVATE" not in final.body
    text = await read_replay_view(replace(selection, session_text=True), confirmed=True)
    assert "PRIVATE_INPUT" in text.body and "PRIVATE_MODEL" not in text.body
    assert "PRIVATE_TITLE" not in text.body


@pytest.mark.asyncio
async def test_failed_page_retains_prior_and_missing_sources_are_not_created(tmp_path):
    selection = await _seed(tmp_path)
    prior = await read_replay_view(selection, event_limit=1)
    path = selection.state_root / "runs" / "first" / "events.jsonl"
    path.write_text("PRIVATE_BROKEN", encoding="utf-8")
    with pytest.raises(ReplayReadError) as error:
        await read_replay_view(selection, prior)
    assert "PRIVATE" not in str(error.value)
    assert prior.snapshot.cursor.sequence == 1
    missing = tmp_path / "missing"
    with pytest.raises(ReplayReadError):
        await read_replay_view(replace(selection, state_root=missing))
    assert not missing.exists()


@pytest.mark.asyncio
async def test_panel_sensitive_confirmation_consumed_and_changes_clear(tmp_path):
    await _seed(tmp_path)
    app = PanelApp(tmp_path)
    async with app.run_test(size=(90, 40)) as pilot:
        panel = app.panel
        panel.query_one("#replay-id", Input).value = "first"
        panel.query_one("#replay-text", Checkbox).value = True
        await pilot.pause()
        panel.start_read()
        await panel._worker.wait()
        assert panel._view is None
        assert "VIEW CONTENT" in str(panel.query_one("#replay-status", Static).content)
        panel.query_one("#replay-confirm", Input).value = "VIEW CONTENT"
        panel.start_read()
        assert panel.query_one("#replay-confirm", Input).value == ""
        await panel._worker.wait()
        assert "PRIVATE_MODEL" in panel._view.body
        assert not panel._busy
        panel.query_one("#replay-text", Checkbox).value = False
        await pilot.pause()
        assert panel._view is None
        assert "PRIVATE" not in str(panel.query_one("#replay-body", Static).content)


@pytest.mark.asyncio
async def test_clear_during_read_discards_delivery_and_duplicate_reads(tmp_path, monkeypatch):
    await _seed(tmp_path)
    original = replay_ui.read_replay_view
    entered, release = Event(), Event()
    calls = []
    async def delayed(*args, **kwargs):
        calls.append(args[0])
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(*args, **kwargs)
    monkeypatch.setattr(replay_ui, "read_replay_view", delayed)
    app = PanelApp(tmp_path)
    async with app.run_test(size=(90, 40)) as pilot:
        panel = app.panel
        panel.query_one("#replay-id", Input).value = "first"
        await pilot.pause()
        panel.start_read()
        worker = panel._worker
        assert await asyncio.to_thread(entered.wait, 3)
        assert panel.query_one("#replay-read").disabled
        assert panel.query_one("#replay-id").disabled
        panel.start_read()
        assert panel._worker is worker
        panel.clear_view()
        release.set()
        await worker.wait()
        assert panel._view is None and len(calls) == 1
        assert not panel._busy and not panel.query_one("#replay-read").disabled
        assert "No snapshot" in str(panel.query_one("#replay-body", Static).content)


@pytest.mark.asyncio
async def test_display_slices_do_not_advance_event_cursor(tmp_path, monkeypatch):
    await _seed(tmp_path)
    monkeypatch.setattr(replay_ui, "DISPLAY_CHARS", 80)
    app = PanelApp(tmp_path)
    async with app.run_test(size=(45, 30)) as pilot:
        panel = app.panel
        panel.query_one("#replay-id", Input).value = "first"
        await pilot.pause()
        panel.start_read()
        await panel._worker.wait()
        prior = panel._view
        first = str(panel.query_one("#replay-body", Static).content)
        panel._display_offset = 80
        panel._show_slice()
        assert panel._view is prior
        assert first != str(panel.query_one("#replay-body", Static).content)
        assert len(str(panel.query_one("#replay-body", Static).content)) <= 80
        panel.clear_view()
        assert panel._view is None and panel._display_offset == 0


@pytest.mark.asyncio
async def test_session_input_display_is_independent_of_output_media(tmp_path):
    selection = replace(await _seed(tmp_path), kind="session", identifier="session")
    store = JsonSessionStore(selection.session_root)
    record = await store.get("session")
    payload = StandardSessionInputRecorder().record(ModelMessage(MessageRole.USER, (
        ImageContent(url="https://example.test/PRIVATE_INPUT_IMAGE"),)))
    await store.save(replace(record, schema_version=2, messages=(
        replace(record.messages[0], recorded_input=payload), *record.messages[1:],
    )))
    original = await read_replay_view(selection)
    assert "input_blocks" not in original.body
    safe = await read_replay_view(replace(selection, input_media="metadata"))
    assert "input_blocks" in safe.body and "PRIVATE_INPUT_IMAGE" not in safe.body
    with pytest.raises(ReplayReadError, match="VIEW CONTENT"):
        await read_replay_view(replace(selection, input_media="references"))
    rich = await read_replay_view(replace(selection, input_media="references"), confirmed=True)
    assert "PRIVATE_INPUT_IMAGE" in rich.body and "PRIVATE_MODEL" not in rich.body
    with pytest.raises(ReplayReadError, match="Selection changed"):
        await read_replay_view(replace(selection, input_media="metadata"), original)
