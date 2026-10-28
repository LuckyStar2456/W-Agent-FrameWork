"""TUI context-template regression source; execution requires authorization."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

import w_agent.tui as tui
from w_agent import RetrievedSessionHistoryPolicy, RunResult, StopReason, SummarizedSessionHistoryPolicy


class App(tui.WAgentTui):
    async def on_mount(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["retrieved", "summarized"])
async def test_transform_confirmation_precedes_file_and_code_loads(tmp_path, monkeypatch, mode):
    def forbidden(*args, **kwargs):
        pytest.fail("missing consent reached loader")
    for name in ("load_input_manifest", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(tui, name, forbidden)
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-input-file").value = "unread.json"
        app.query_one("#run-history").value = mode
        app.query_one("#run-history-query").value = "PRIVATE_QUERY" if mode == "retrieved" else ""
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-history-confirm").value = "SEND HISTORY"
        await app._run_configured_agent()
        assert "TRANSFORM HISTORY" in str(app.query_one("#run-result").content)
        assert all(not app.query_one(f"#run-{field}").value for field in tui._RUN_CONFIRMATIONS)
        assert not app._agent_busy


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("recent-turns", "PRIVATE"), ("recent-turns", "-1"),
                                        ("max-bytes", "0"), ("summary-chars", "42")])
async def test_invalid_template_settings_do_not_load(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda *args: pytest.fail("invalid settings loaded config"))
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-prompt").value = "question"
        app.query_one("#run-history").value = "retrieved"
        app.query_one("#run-history-query").value = "query"
        app.query_one(f"#run-history-{field}").value = value
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-history-transform-confirm").value = "TRANSFORM HISTORY"
        await app._run_configured_agent()
        output = str(app.query_one("#run-result").content)
        assert "Rejected" in output and "PRIVATE" not in output and not app._agent_busy


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["retrieved", "summarized"])
async def test_selected_template_is_captured_locked_and_forwarded(tmp_path, monkeypatch, mode):
    entered, release = asyncio.Event(), asyncio.Event()
    captured = {"calls": 0}
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run(self, prompt, **kwargs):
            captured.update(kwargs)
            captured["calls"] += 1
            entered.set()
            await release.wait()
            return SimpleNamespace(session=SimpleNamespace(session_id="session"),
                                   result=RunResult("run", StopReason.COMPLETED, "answer", (), (), 1, 0))
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(tui, "open_local_runtime", lambda *args, **kwargs: Runtime())
    app = App(tmp_path)
    async with app.run_test(size=(45, 30)):
        app.query_one("#run-prompt").value = "question"
        app.query_one("#run-history").value = mode
        app.query_one("#run-history-query").value = "original" if mode == "retrieved" else ""
        app.query_one("#run-history-recent-turns").value = "0"
        app.query_one("#run-history-max-bytes").value = "1234"
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-history-transform-confirm").value = "TRANSFORM HISTORY"
        app._start_configured_agent()
        worker = app._agent_worker
        assert all(app.query_one(f"#run-{field}").disabled for field in tui._RUN_FIELDS)
        app.query_one("#run-history-query").value = "changed"
        app.query_one("#run-history-recent-turns").value = "9"
        app._start_configured_agent()
        assert app._agent_worker is worker
        await asyncio.wait_for(entered.wait(), 3)
        policy = captured["history_policy"]
        assert policy.recent_turns == 0 and policy.limits.max_output_bytes == 1234
        if mode == "retrieved":
            assert isinstance(policy, RetrievedSessionHistoryPolicy) and policy.query == "original"
        else:
            assert isinstance(policy, SummarizedSessionHistoryPolicy)
        release.set()
        await worker.wait()
        assert captured["calls"] == 1 and captured["closed"]
        assert not app._agent_busy and not app.query_one("#run-history-query").disabled
        assert not app.query_one("#run-history-transform-confirm").value
