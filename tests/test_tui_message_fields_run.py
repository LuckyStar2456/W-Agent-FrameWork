"""Draft TUI field-selection regression source."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

import w_agent.tui as tui
from w_agent import ModelMessage, MessageRole, RunResult, StopReason


class App(tui.WAgentTui):
    async def on_mount(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["record-input-name", "record-input-metadata", "history-name", "history-metadata"])
async def test_invalid_field_options_consume_confirmation_before_loading(tmp_path, monkeypatch, field):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid field selection reached loader")
    for name in ("load_input_manifest", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(tui, name, forbidden)
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-input-file").value = "unread.json"
        app.query_one(f"#run-{field}").value = True
        app.query_one("#run-confirm").value = "RUN"
        await app._run_configured_agent()
        assert "Rejected" in str(app.query_one("#run-result").content)
        assert not app._agent_busy
        assert all(not app.query_one(f"#run-{item}").value for item in tui._RUN_CONFIRMATIONS)


@pytest.mark.asyncio
async def test_field_options_are_captured_locked_and_forwarded(tmp_path, monkeypatch):
    captured = {}
    entered, release = asyncio.Event(), asyncio.Event()

    def load(path, **kwargs):
        captured["parser"] = kwargs
        return (ModelMessage.text(MessageRole.USER, "question"),)

    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run_messages(self, messages, **kwargs):
            captured.update(kwargs)
            entered.set()
            await release.wait()
            return SimpleNamespace(session=SimpleNamespace(session_id="session"),
                result=RunResult("run", StopReason.COMPLETED, "answer", messages, (), 1, 0))

    monkeypatch.setattr(tui, "load_input_manifest", load)
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(tui, "open_local_runtime", lambda *args, **kwargs: Runtime())
    app = App(tmp_path)
    async with app.run_test(size=(45, 30)):
        app.query_one("#run-input-file").value = "input.json"
        for field in ("input-message-fields", "record-inputs", "record-input-name", "history-metadata"):
            app.query_one(f"#run-{field}").value = True
        app.query_one("#run-history").value = "recorded"
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-record-confirm").value = "RECORD INPUTS"
        app.query_one("#run-history-confirm").value = "SEND HISTORY"
        app._start_configured_agent()
        worker = app._agent_worker
        assert all(app.query_one(f"#run-{field}").disabled for field in tui._RUN_FIELDS)
        app.query_one("#run-record-input-name").value = False
        app.query_one("#run-history-metadata").value = False
        try:
            await asyncio.wait_for(entered.wait(), 3)
            assert captured["parser"] == {"allow_message_fields": True}
            assert captured["input_recorder"].include_name
            assert not captured["input_recorder"].include_metadata
            assert captured["history_policy"].fields_decoder.include_metadata
            assert not captured["history_policy"].fields_decoder.include_name
        finally:
            release.set()
            await worker.wait()
        assert captured["closed"] and not app._agent_busy
        assert all(not app.query_one(f"#run-{field}").disabled for field in tui._RUN_FIELDS)
