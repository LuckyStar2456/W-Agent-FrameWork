"""End-to-end assembly regressions for budgeted evaluation/probing."""

import json
import sys
import types
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent import (
    BlockEnd, BlockStart, EvaluationCase, EvaluationDataset, FinishEvent, FinishReason,
    InMemorySharedBudget, LocalSharedBudgetBinding, ModelCapability, ModelDescriptor,
    ProviderTemplate, ProviderTemplateRegistry, SharedBudgetAmount, SharedBudgetLimits,
    TextContent, TokenUsage, UsageEvent, assemble_local_provider, assemble_local_runtime,
    local_runtime_config_from_mapping,
)


class Meter:
    def __init__(self):
        self.caps = []

    async def bound(self, request):
        self.caps.append(request.max_output_tokens)
        return SharedBudgetAmount(TokenUsage(10, request.max_output_tokens))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)


class Provider:
    def __init__(self, *, report_usage=True):
        self.calls = self.close_calls = self.catalog_calls = 0
        self.report_usage = report_usage

    async def list_models(self):
        self.catalog_calls += 1
        return (ModelDescriptor("provider", "model", frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT,
        })),)

    async def resolve(self, model):
        return (await self.list_models())[0]

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent("PRIVATE_RESPONSE"))
        if self.report_usage:
            yield UsageEvent(TokenUsage(8, 2))
        yield FinishEvent(FinishReason.STOP)

    async def aclose(self):
        self.close_calls += 1


def prepare(monkeypatch, *, total=25, report_usage=True, cases=3, unavailable=False):
    events, created = [], []
    class Ledger(InMemorySharedBudget):
        async def snapshot(self):
            if unavailable:
                raise RuntimeError("PRIVATE_SNAPSHOT")
            return await super().snapshot()
    ledger, meter = Ledger(SharedBudgetLimits(max_total_tokens=total)), Meter()
    binding = LocalSharedBudgetBinding(ledger, meter)
    @asynccontextmanager
    async def factory():
        events.append("open")
        try:
            yield {"pool": binding}
        finally:
            events.append("close")
    module = types.ModuleType("budget_eval_probe_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    config = local_runtime_config_from_mapping({
        "provider": {"template": "fake", "model": "model", "name": "provider"},
        "agent": {"max_steps": 1, "max_tool_calls": 0, "max_output_tokens": 5},
        "shared_budget": {"binding": "pool"},
    })
    def build(**kwargs):
        provider = Provider(report_usage=report_usage)
        created.append(provider)
        return provider
    templates = ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "test", None, build),))
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: config)
    monkeypatch.setattr(cli, "assemble_local_provider", lambda config, **kwargs: assemble_local_provider(config, templates=templates, **kwargs))
    monkeypatch.setattr(cli, "open_local_runtime", lambda config, root, **kwargs: assemble_local_runtime(config, root, templates=templates, **kwargs))
    dataset = EvaluationDataset(tuple(EvaluationCase(f"case-{i}", "PRIVATE_INPUT", expected_output="PRIVATE_RESPONSE") for i in range(cases)))
    monkeypatch.setattr(cli, "load_evaluation_dataset", lambda path: dataset)
    return events, created, meter, binding


FLAGS = ["--budget-entry", "budget_eval_probe_host:factory", "--confirm-budget-code", "--json"]


def test_evaluation_opens_one_pool_for_all_cases_and_keeps_report_scope(tmp_path, monkeypatch):
    events, created, meter, _ = prepare(monkeypatch)
    path = tmp_path / "report.json"
    result = CliRunner().invoke(cli.app, ["evaluate", "unused.json", "--confirm-model-call", "--report", str(path), *FLAGS])
    assert result.exit_code == 1, result.output  # Third case has no shared allowance.
    data = json.loads(result.output)
    assert data["total"] == 3 and data["passed"] == 2
    assert data["shared_budget"]["known_usage"]["total_tokens"] == 20
    assert data["cases"][2]["stop_reason"] == "model-error"
    assert events == ["open", "close"] and len(created) == 1
    assert created[0].calls == 2 and created[0].close_calls == 1 and meter.caps == [5, 5, 5]
    report = json.loads(path.read_text(encoding="utf-8"))
    assert "shared_budget" not in report and report["total"] == 3
    assert "PRIVATE" not in result.output and "PRIVATE" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode,active,calls,tickets", [("safe", False, 0, 0), ("active", True, 1, 1), ("capability", True, 1, 1)])
def test_probe_safe_catalog_and_active_generation_budget_boundaries(monkeypatch, mode, active, calls, tickets):
    events, created, meter, _ = prepare(monkeypatch)
    args = ["provider-probe", "--mode", mode, *FLAGS]
    if active:
        args.append("--confirm-active-probe")
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["successful"] and sum(data["shared_budget"]["tickets"].values()) == tickets
    assert events == ["open", "close"] and created[0].calls == calls and created[0].close_calls == 1
    assert meter.caps == ([8] if active else [])
    assert "PRIVATE" not in result.output


def test_exhausted_active_probe_never_reaches_inner_generation(monkeypatch):
    _, created, _, _ = prepare(monkeypatch, total=17)
    result = CliRunner().invoke(cli.app, ["provider-probe", "--mode", "active", "--confirm-active-probe", *FLAGS])
    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert not data["successful"] and created[0].calls == 0 and created[0].close_calls == 1
    assert sum(data["shared_budget"]["tickets"].values()) == 0


def test_missing_probe_usage_is_unknown_and_keeps_full_reservation(monkeypatch):
    _, created, _, _ = prepare(monkeypatch, report_usage=False)
    result = CliRunner().invoke(cli.app, ["provider-probe", "--mode", "active", "--confirm-active-probe", *FLAGS])
    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert created[0].calls == 1 and data["shared_budget"]["blocked"]
    assert data["shared_budget"]["tickets"]["unknown"] == 1
    assert data["shared_budget"]["held_usage"]["total_tokens"] == 18


@pytest.mark.parametrize("args", [
    ["evaluate", "unused.json", "--confirm-model-call", "--budget-entry", "budget_eval_probe_host:factory"],
    ["evaluate", "unused.json", *FLAGS],
    ["provider-probe", "--mode", "active", *FLAGS],
    ["provider-probe", "--budget-entry", "budget_eval_probe_host:factory"],
])
def test_authorizations_are_independent_and_precede_factory_and_provider(monkeypatch, args):
    events, created, _, _ = prepare(monkeypatch)
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code != 0 and not events and not created


@pytest.mark.parametrize("probe", [False, True])
def test_display_failure_does_not_change_evaluation_or_probe_outcome(monkeypatch, probe):
    _, created, _, _ = prepare(monkeypatch, unavailable=True, cases=1)
    args = (["provider-probe", "--mode", "active", "--confirm-active-probe"] if probe else
            ["evaluate", "unused.json", "--confirm-model-call"])
    result = CliRunner().invoke(cli.app, [*args, *FLAGS])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["shared_budget"]["status"] == "unavailable"
    assert "known_usage" not in data["shared_budget"] and "PRIVATE" not in result.output
    assert created[0].calls == 1


def test_text_evaluation_also_displays_shared_pool(monkeypatch):
    prepare(monkeypatch, cases=1)
    result = CliRunner().invoke(cli.app, ["evaluate", "unused.json", "--confirm-model-call", *FLAGS[:-1]])
    assert result.exit_code == 0, result.output
    assert "Shared pool" in result.output and "known_usage" in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["evaluation", "safe", "active"])
@pytest.mark.parametrize("authorized", [False, True])
async def test_tui_budget_consent_pool_lifecycle_and_display(tmp_path, monkeypatch, operation, authorized):
    pytest.importorskip("textual")
    import w_agent.tui as tui

    events, created, meter, _ = prepare(monkeypatch)
    for name in ("load_local_runtime_config", "open_local_runtime",
                 "assemble_local_provider", "load_evaluation_dataset"):
        monkeypatch.setattr(tui, name, getattr(cli, name))

    class App(tui.WAgentTui):
        async def on_mount(self):
            pass

    app = App(tmp_path)
    prefix = "evaluation" if operation == "evaluation" else "provider-probe"
    async with app.run_test(size=(100, 45)):
        app.query_one(f"#{prefix}-budget-entry").value = "budget_eval_probe_host:factory"
        app.query_one(f"#{prefix}-budget-confirm").value = "LOAD BUDGET" if authorized else "wrong"
        app.query_one(f"#{prefix}-confirm").value = "EVALUATE" if operation == "evaluation" else "ACTIVE"
        if operation == "evaluation":
            app.query_one("#evaluation-report").value = ""
            await app._run_evaluation()
        else:
            await app._probe_configured_provider(active=operation == "active")
        assert app.query_one(f"#{prefix}-budget-confirm").value == ""
        result = str(app.query_one(f"#{prefix}-result").content)
        if not authorized:
            assert "LOAD BUDGET" in result and not events and not created
            return
        pool = str(app.query_one(f"#{prefix}-budget-result").content)
        assert "shared-pool-not-this-run" in pool and "known_usage" in pool
        assert "PRIVATE" not in result + pool and "reservation_id" not in pool
        assert events == ["open", "close"] and created[0].close_calls == 1
        if operation == "evaluation":
            assert "Passed: 2/3" in result and created[0].calls == 2
            assert meter.caps == [5, 5, 5]
        else:
            assert "Successful: True" in result
            assert created[0].calls == (1 if operation == "active" else 0)
            assert meter.caps == ([8] if operation == "active" else [])
