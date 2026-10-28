"""Session Replay field-disclosure UI test source."""

from dataclasses import replace

import pytest

pytest.importorskip("textual")
from textual.app import App

import w_agent.tui_replay as replay_ui
from w_agent import (
    JsonlRunStore, JsonSessionStore, MessageFieldsSessionInputRecorder, MessageRole,
    ModelMessage, RunEvent, RunEventType, SessionMessage, SessionRecord, SessionRunRecord, TokenUsage,
)


async def _seed(tmp_path):
    root = tmp_path / ".wagent"
    await JsonlRunStore(root).append(RunEvent(1, RunEventType.TOKEN_USAGE, "run", session_id="session",
                                           data={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}))
    message = replace(ModelMessage.text(MessageRole.USER, "PRIVATE_TEXT"),
                      name="PRIVATE_NAME", metadata={"tag": "PRIVATE_METADATA"})
    record = MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True).record(message)
    await JsonSessionStore(root / "sessions").save(SessionRecord(
        "session", "title", schema_version=2,
        messages=(SessionMessage(MessageRole.USER, "PRIVATE_TEXT", "run", recorded_input=record),),
        runs=(SessionRunRecord("run", "agent", "completed", "answer", TokenUsage(1, 1), True, 1, 0),),
    ))
    return replay_ui.ReplaySelection("session", "session", root, root / "sessions")


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.panel = replay_ui.ReplayPanel(workspace)

    def compose(self):
        yield self.panel


@pytest.mark.asyncio
async def test_read_service_enforces_field_consent_and_keeps_disclosures_separate(tmp_path, monkeypatch):
    selection = await _seed(tmp_path)
    hidden = await replay_ui.read_replay_view(replace(selection, input_media="metadata"))
    assert "PRIVATE" not in hidden.body
    for key, expected, hidden_value in (("input_name", "PRIVATE_NAME", "PRIVATE_METADATA"),
                                        ("input_metadata", "PRIVATE_METADATA", "PRIVATE_NAME")):
        selected = replace(selection, **{key: True})
        with pytest.raises(replay_ui.ReplayReadError, match="VIEW CONTENT"):
            await replay_ui.read_replay_view(selected)
        disclosed = await replay_ui.read_replay_view(selected, confirmed=True)
        assert expected in disclosed.body and hidden_value not in disclosed.body
        assert "PRIVATE_TEXT" not in disclosed.body
        with pytest.raises(replay_ui.ReplayReadError, match="Selection changed"):
            await replay_ui.read_replay_view(selection, disclosed)
    monkeypatch.setattr(replay_ui, "JsonlRunStore", lambda *args: pytest.fail("wrong-mode source read"))
    with pytest.raises(replay_ui.ReplayReadError, match="Session mode"):
        await replay_ui.read_replay_view(replace(selection, kind="run", input_name=True), confirmed=True)


@pytest.mark.asyncio
async def test_panel_consumes_confirmation_locks_fields_and_clears_on_change(tmp_path):
    await _seed(tmp_path)
    app = PanelApp(tmp_path)
    async with app.run_test(size=(45, 30)) as pilot:
        panel = app.panel
        panel.query_one("#replay-kind").value = "session"
        panel.query_one("#replay-id").value = "session"
        panel.query_one("#replay-input-name").value = True
        await pilot.pause()
        panel.start_read()
        await panel._worker.wait()
        assert panel._view is None
        assert "VIEW CONTENT" in str(panel.query_one("#replay-status").content)
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.start_read()
        assert panel.query_one("#replay-input-name").disabled
        assert panel.query_one("#replay-input-metadata").disabled
        assert not panel.query_one("#replay-confirm").value
        await panel._worker.wait()
        assert "PRIVATE_NAME" in panel._view.body and "PRIVATE_METADATA" not in panel._view.body
        panel.query_one("#replay-input-name").value = False
        await pilot.pause()
        assert panel._view is None and "PRIVATE" not in str(panel.query_one("#replay-body").content)
        panel.query_one("#replay-input-metadata").value = True
        await pilot.pause()
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.start_read()
        await panel._worker.wait()
        assert "PRIVATE_METADATA" in panel._view.body and "PRIVATE_NAME" not in panel._view.body
