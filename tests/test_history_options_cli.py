"""Shared history options and CLI regression source."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    BuiltinSessionHistoryOptions, RecordedSessionHistoryPolicy,
    RetrievedSessionHistoryPolicy, RunResult, StopReason, SummarizedSessionHistoryPolicy,
)


def test_existing_defaults_remain_unchanged():
    assert BuiltinSessionHistoryOptions().runtime_options() == {}
    assert BuiltinSessionHistoryOptions("none").runtime_options() == {"include_history": False}
    assert isinstance(BuiltinSessionHistoryOptions("recorded").runtime_options()["history_policy"], RecordedSessionHistoryPolicy)


def test_template_options_build_fresh_policies_and_preserve_zero():
    selection = BuiltinSessionHistoryOptions("retrieved", "PRIVATE_QUERY", 0, 3, max_output_bytes=1234)
    first = selection.runtime_options()["history_policy"]
    second = selection.runtime_options()["history_policy"]
    assert isinstance(first, RetrievedSessionHistoryPolicy) and first is not second
    assert first.query == "PRIVATE_QUERY" and first.recent_turns == 0
    assert first.max_retrieved_turns == 3 and first.limits.max_output_bytes == 1234
    with pytest.raises(FrozenInstanceError):
        selection.query = "changed"
    summary = BuiltinSessionHistoryOptions("summarized", recent_turns=0, summary_chars=20).runtime_options()["history_policy"]
    assert isinstance(summary, SummarizedSessionHistoryPolicy)
    assert summary.recent_turns == 0 and summary.summarizer.max_chars == 20


@pytest.mark.parametrize("kwargs", [
    {"mode": "bad"}, {"mode": []}, {"mode": "retrieved"},
    {"mode": "retrieved", "query": " "},
    {"mode": "retrieved", "query": "q", "summary_chars": 3},
    {"mode": "summarized", "query": "PRIVATE_QUERY"},
    {"mode": "summarized", "retrieved_turns": 2},
    {"mode": "text", "recent_turns": 0},
    {"mode": "recorded", "max_output_bytes": 123},
    {"mode": "none", "query": "PRIVATE_QUERY"},
    {"mode": "retrieved", "query": "q", "recent_turns": True},
    {"mode": "retrieved", "query": "q", "retrieved_turns": 0},
    {"mode": "summarized", "summary_chars": -1},
    {"mode": "summarized", "max_output_bytes": 0},
    {"mode": "retrieved", "query": "PRIVATE_QUERY" * 500},
])
def test_invalid_and_irrelevant_settings_fail_without_echoing_query(kwargs):
    with pytest.raises(ValueError) as error:
        BuiltinSessionHistoryOptions(**kwargs)
    assert "PRIVATE_QUERY" not in str(error.value)


@pytest.mark.parametrize("args,expected", [
    (["--history", "retrieved", "--history-query", "q"], "--confirm-history-transform"),
    (["--history", "summarized", "--confirm-history-media"], "--confirm-history-transform"),
    (["--history", "recorded", "--confirm-history-transform"], "--confirm-history-media"),
    (["--history", "retrieved", "--confirm-history-transform"], "explicit nonempty query"),
    (["--history", "summarized", "--history-query", "PRIVATE_QUERY", "--confirm-history-transform"], "require retrieved"),
    (["--history", "text", "--history-recent-turns", "2"], "require retrieved or summarized"),
    (["--history", "summarized", "--history-summary-chars", "0", "--confirm-history-transform"], "limits or query are invalid"),
])
def test_cli_rejects_before_all_input_and_code_loading(monkeypatch, args, expected):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid history selection reached loader")
    for name in ("load_input_manifest", "load_tool_entries", "load_local_runtime_config", "open_local_runtime"):
        monkeypatch.setattr(cli, name, forbidden)
    result = CliRunner().invoke(cli.app, ["run", "--input-file", "unread.json", "--confirm-model-call",
                                        "--tool-entry", "host:tools", "--confirm-tool-code", *args])
    # Rich wraps diagnostics to terminal width; assert their text, not wrapping.
    assert result.exit_code == 2 and expected in " ".join(result.output.split())
    assert "PRIVATE_QUERY" not in result.output


@pytest.mark.parametrize("mode", ["retrieved", "summarized"])
def test_cli_passes_selected_policy_and_closes_runtime(monkeypatch, mode):
    captured = {}
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            captured["closed"] = True

        async def run(self, prompt, **kwargs):
            captured.update(kwargs)
            captured["prompt"] = prompt
            return SimpleNamespace(session=SimpleNamespace(session_id="session"),
                                   result=RunResult("run", StopReason.COMPLETED, "answer", (), (), 1, 0))
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(cli, "open_local_runtime", lambda *args, **kwargs: Runtime())
    args = ["run", "question", "--session", "session", "--confirm-model-call", "--history", mode,
            "--confirm-history-transform", "--history-recent-turns", "0", "--history-max-bytes", "1000", "--json"]
    args += (["--history-query", "PRIVATE_QUERY", "--history-retrieved-turns", "3"] if mode == "retrieved"
             else ["--history-summary-chars", "90"])
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    policy = captured["history_policy"]
    assert policy.recent_turns == 0 and policy.limits.max_output_bytes == 1000
    if mode == "retrieved":
        assert isinstance(policy, RetrievedSessionHistoryPolicy) and policy.query == "PRIVATE_QUERY"
    else:
        assert isinstance(policy, SummarizedSessionHistoryPolicy) and policy.summarizer.max_chars == 90
    assert captured["closed"] and captured["prompt"] == "question"
    assert "record_inputs" not in captured and "PRIVATE_QUERY" not in result.output
