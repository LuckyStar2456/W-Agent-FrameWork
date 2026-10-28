"""Offline real Runtime assembly through authorized CLI and TUI host scopes."""

import json
import sys
import types
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import local_runtime_config_from_mapping
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from tests.test_budget_evaluation_probe import prepare as prepare_provider


ENTRY = "usage_frontend_host:factory"
FLAGS = ["--usage-entry", ENTRY, "--confirm-usage-code", "--confirm-usage-recording", "--json"]


def prepare(monkeypatch, *, unavailable=False):
    _, created, _, _ = prepare_provider(monkeypatch, cases=1)
    events = []

    class Ledger(InMemoryServiceUsageLedger):
        async def records(self, operation_id):
            if unavailable:
                raise RuntimeError("PRIVATE_LEDGER_FAILURE")
            return await super().records(operation_id)

    binding = LocalServiceUsageBinding(Ledger(), "host-operation")

    @asynccontextmanager
    async def factory():
        events.append("open")
        try:
            yield {"observations": binding}
        finally:
            events.append("close")

    module = types.ModuleType("usage_frontend_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    config = local_runtime_config_from_mapping({
        "provider": {"template": "fake", "model": "model", "name": "provider"},
        "agent": {"max_steps": 1, "max_tool_calls": 0, "max_output_tokens": 5},
        "service_usage": {"binding": "observations"},
    })
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: config)
    return events, created, binding


@pytest.mark.parametrize("operation", ["run", "evaluate", "safe", "active"])
@pytest.mark.parametrize("unavailable", [False, True])
def test_cli_observes_actual_calls_and_display_failure_never_retries(tmp_path, monkeypatch, operation, unavailable):
    events, created, _ = prepare(monkeypatch, unavailable=unavailable)
    if operation == "run":
        args = ["run", "question", "--confirm-model-call", "--state-root", str(tmp_path)]
    elif operation == "evaluate":
        args = ["evaluate", "unused.json", "--confirm-model-call"]
    else:
        args = ["provider-probe", "--mode", operation]
        if operation == "active":
            args.append("--confirm-active-probe")
    result = CliRunner().invoke(cli.app, [*args, *FLAGS])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)["service_usage"]
    assert summary["scope"] == "host-operation-not-this-run"
    assert summary["coverage"] == "supplied-records-only"
    assert summary["status"] == ("unavailable" if unavailable else "available")
    if not unavailable:
        assert summary["known_usage"]["total_tokens"] == (0 if operation == "safe" else 10)
        assert summary["records"] == (0 if operation == "safe" else 1)
    assert "PRIVATE" not in json.dumps(summary) and "record_id" not in summary
    assert events == ["open", "close"]
    assert len(created) == 1 and created[0].calls == (0 if operation == "safe" else 1)
    assert created[0].close_calls == 1


@pytest.mark.parametrize("args", [
    ["run", "question", "--confirm-model-call"],
    ["evaluate", "unused.json", "--confirm-model-call"],
    ["provider-probe"],
    ["run-resume", "session", "run", "--approve-tool-call", "call", "--confirm-model-call"],
])
@pytest.mark.parametrize("consent", [[], ["--confirm-usage-code"], ["--confirm-usage-recording"]])
def test_cli_independent_consent_precedes_loading(monkeypatch, args, consent):
    events, created, _ = prepare(monkeypatch)
    result = CliRunner().invoke(cli.app, [*args, "--usage-entry", ENTRY, *consent])
    assert result.exit_code != 0 and not events and not created
    assert "LOAD USAGE" in result.output and "RECORD USAGE" in result.output


def test_text_evaluation_displays_operation_but_saved_report_remains_model_only(tmp_path, monkeypatch):
    prepare(monkeypatch)
    path = tmp_path / "report.json"
    result = CliRunner().invoke(cli.app, ["evaluate", "unused.json", "--confirm-model-call", "--report", str(path), *FLAGS[:-1]])
    assert result.exit_code == 0, result.output
    assert "Service usage" in result.output and "known_usage" in result.output
    assert "service_usage" not in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["run", "evaluation", "safe", "active"])
@pytest.mark.parametrize("authorized", [False, True])
async def test_tui_consumes_independent_consents_and_displays_usage(tmp_path, monkeypatch, operation, authorized):
    import w_agent.tui as tui

    events, created, _ = prepare(monkeypatch)
    for name in ("load_local_runtime_config", "open_local_runtime", "assemble_local_provider", "load_evaluation_dataset"):
        monkeypatch.setattr(tui, name, getattr(cli, name))

    class App(tui.WAgentTui):
        async def on_mount(self):
            pass

    app = App(tmp_path)
    prefix = operation if operation in {"run", "evaluation"} else "provider-probe"
    async with app.run_test(size=(100, 45)):
        app.query_one(f"#{prefix}-usage-entry").value = ENTRY
        app.query_one(f"#{prefix}-usage-code").value = "LOAD USAGE"
        app.query_one(f"#{prefix}-usage-record").value = "RECORD USAGE" if authorized else ""
        if operation == "run":
            app.query_one("#run-confirm").value = "RUN"
            app.query_one("#run-prompt").value = "question"
            request = app._capture_agent_run()
            if request is not None:
                await app._execute_agent_run(request)
        elif operation == "evaluation":
            app.query_one("#evaluation-confirm").value = "EVALUATE"
            app.query_one("#evaluation-report").value = ""
            await app._run_evaluation()
        else:
            app.query_one("#provider-probe-confirm").value = "ACTIVE"
            await app._probe_configured_provider(active=operation == "active")
        assert app.query_one(f"#{prefix}-usage-code").value == ""
        assert app.query_one(f"#{prefix}-usage-record").value == ""
        if not authorized:
            assert not events and not created
            return
        summary = str(app.query_one(f"#{prefix}-usage-result").content)
        assert "host-operation-not-this-run" in summary and "known_usage" in summary
        assert "PRIVATE" not in summary
        assert events == ["open", "close"] and created[0].close_calls == 1
        assert created[0].calls == (0 if operation == "safe" else 1)
