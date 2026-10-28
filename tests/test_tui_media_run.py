"""Draft media-run UI tests; no execution without separate user authorization."""

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")
from textual.worker import WorkerCancelled

import w_agent.tui as tui
from w_agent import ImageContent, RecordedSessionHistoryPolicy, RunResult, StopReason


class App(tui.WAgentTui):
    async def on_mount(self):
        # Isolate the Run form from unrelated startup probes in these tests.
        pass


def _authorize(app):
    app.query_one("#run-confirm").value = "RUN"
    app.query_one("#run-record-confirm").value = "RECORD INPUTS"
    app.query_one("#run-history-confirm").value = "SEND HISTORY"
    app.query_one("#run-tool-confirm").value = "LOAD TOOLS"


def _input_file(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"schema_version": 1, "messages": [{"role": "user", "content": [
        {"type": "image", "url": "https://example.test/PRIVATE_IMAGE"}]}]}), encoding="utf-8")
    return path


def _result(messages=()):
    return SimpleNamespace(session=SimpleNamespace(session_id="selected-session"),
                           result=RunResult("run", StopReason.COMPLETED, "answer", tuple(messages), (), 1, 0))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing,expected", [("confirm", "type RUN"), ("tool-confirm", "LOAD TOOLS"),
                                             ("record-confirm", "RECORD INPUTS"), ("history-confirm", "SEND HISTORY")])
async def test_confirmations_are_independent_and_precede_all_loading(tmp_path, monkeypatch, missing, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("load before required confirmations")
    for name in ("load_input_manifest", "load_tool_entries", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(tui, name, forbidden)
    app = App(tmp_path)
    async with app.run_test(size=(100, 45)):
        app.query_one("#run-input-file").value = "input.json"
        app.query_one("#run-tool-entries").value = "example:tools"
        app.query_one("#run-record-inputs").value = True
        app.query_one("#run-history").value = "recorded"
        _authorize(app)
        app.query_one(f"#run-{missing}").value = "wrong"
        await app._run_configured_agent()
        assert expected in str(app.query_one("#run-result").content)
        assert not app._agent_busy
        assert all(app.query_one(f"#run-{name}").value == "" for name in tui._RUN_CONFIRMATIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt,path,history", [("", "", "text"), ("text", "input.json", "text"), ("text", "", "bad")])
async def test_invalid_input_combinations_do_not_load(tmp_path, monkeypatch, prompt, path, history):
    monkeypatch.setattr(tui, "load_input_manifest", lambda *args: pytest.fail("invalid form loaded input"))
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda *args: pytest.fail("invalid form loaded config"))
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-prompt").value = prompt
        app.query_one("#run-input-file").value = path
        app.query_one("#run-history").value = history
        _authorize(app)
        await app._run_configured_agent()
        assert "Rejected" in str(app.query_one("#run-result").content)
        assert not app._agent_busy


@pytest.mark.asyncio
async def test_media_request_is_captured_and_duplicate_click_does_not_dispatch(tmp_path, monkeypatch):
    _input_file(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    captured = {"count": 0}
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run_messages(self, messages, **kwargs):
            captured.update(kwargs)
            captured["messages"] = messages
            captured["count"] += 1
            entered.set()
            await release.wait()
            return _result(messages)
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda path: captured.update(config=path) or object())
    monkeypatch.setattr(tui, "open_local_runtime", lambda *args, **kwargs: Runtime())
    app = App(tmp_path)
    async with app.run_test(size=(45, 30)):
        app.query_one("#run-input-file").value = "input.json"
        app.query_one("#run-record-inputs").value = True
        app.query_one("#run-history").value = "recorded"
        app.query_one("#run-permissions").value = "notes.read"
        _authorize(app)
        app._start_configured_agent()
        worker = app._agent_worker
        assert app.query_one("#run-input-file").disabled
        assert app.query_one("#run-record-inputs").disabled
        assert not app.query_one("#run-cancel").disabled
        # Even programmatic edits to disabled widgets cannot alter the captured request.
        app.query_one("#run-input-file").value = "missing.json"
        app.query_one("#run-history").value = "none"
        app.query_one("#run-config").value = "other.json"
        app._start_configured_agent()
        assert app._agent_worker is worker
        await asyncio.wait_for(entered.wait(), 3)
        assert isinstance(captured["messages"][0].content[0], ImageContent)
        assert captured["record_inputs"] is True
        assert isinstance(captured["history_policy"], RecordedSessionHistoryPolicy)
        assert captured["config"] == tmp_path / ".wagent" / "config.json"
        assert captured["permissions"] == frozenset({"notes.read"})
        release.set()
        await worker.wait()
        assert captured["count"] == 1 and captured["closed"]
        assert not app._agent_busy and not app.query_one("#run-button").disabled
        assert app.query_one("#run-cancel").disabled
        assert "PRIVATE_IMAGE" not in str(app.query_one("#run-events").content)


@pytest.mark.asyncio
async def test_invalid_manifest_stops_before_tool_import_and_resets_controls(tmp_path, monkeypatch):
    (tmp_path / "bad.json").write_text("PRIVATE_BROKEN", encoding="utf-8")
    monkeypatch.setattr(tui, "load_tool_entries", lambda *args: pytest.fail("invalid input loaded tools"))
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-input-file").value = "bad.json"
        app.query_one("#run-tool-entries").value = "example:tools"
        _authorize(app)
        await app._run_configured_agent()
        assert "input file" in str(app.query_one("#run-result").content)
        assert "PRIVATE" not in str(app.query_one("#run-result").content)
        assert not app._agent_busy and not app.query_one("#run-button").disabled


@pytest.mark.asyncio
async def test_cancellation_cleans_runtime_without_replay(tmp_path, monkeypatch):
    entered = asyncio.Event()
    captured = {"calls": 0}
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run(self, prompt, **kwargs):
            assert kwargs["include_history"] is False
            captured["calls"] += 1
            entered.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(tui, "open_local_runtime", lambda *args, **kwargs: Runtime())
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-prompt").value = "question"
        app.query_one("#run-history").value = "none"
        _authorize(app)
        app._start_configured_agent()
        await asyncio.wait_for(entered.wait(), 3)
        app._cancel_configured_agent()
        with pytest.raises(WorkerCancelled):
            await app._agent_worker.wait()
        assert captured == {"calls": 1, "closed": True}
        assert not app._agent_busy
        assert "No automatic replay" in str(app.query_one("#run-result").content)


@pytest.mark.asyncio
async def test_cancellation_before_worker_entry_still_unlocks(tmp_path, monkeypatch):
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda *args: pytest.fail("cancelled before entry"))
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-prompt").value = "question"
        _authorize(app)
        app._start_configured_agent()
        app._cancel_configured_agent()
        with pytest.raises(WorkerCancelled):
            await app._agent_worker.wait()
        assert not app._agent_busy and not app.query_one("#run-button").disabled
