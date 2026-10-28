"""TUI budget consent and display regressions."""

import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")
from rich.text import Text

import w_agent.tui as tui
from w_agent import InMemorySharedBudget, LocalSharedBudgetBinding, SharedBudgetAmount, SharedBudgetLimits, TokenUsage


class App(tui.WAgentTui):
    async def on_mount(self):
        pass


class Meter:
    async def bound(self, request):
        return SharedBudgetAmount(TokenUsage(10, 5))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_budget_confirmation_precedes_loading_and_is_one_shot(tmp_path, monkeypatch, resume):
    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized UI loaded configuration")
    monkeypatch.setattr(tui, "load_local_runtime_config", forbidden)
    app = App(tmp_path)
    async with app.run_test(size=(100, 45)):
        prefix = "checkpoint" if resume else "run"
        app.query_one(f"#{prefix}-budget-entry").value = "never_load:factory"
        app.query_one(f"#{prefix}-budget-confirm").value = "wrong"
        app.query_one(f"#{prefix}-confirm").value = "RESUME" if resume else "RUN"
        if resume:
            await app._resume_configured_agent()
        else:
            app.query_one("#run-prompt").value = "hello"
            await app._run_configured_agent()
        target = "checkpoint-resume-result" if resume else "run-result"
        assert "LOAD BUDGET" in str(app.query_one(f"#{target}").content)
        assert app.query_one(f"#{prefix}-budget-confirm").value == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_tui_budget_catalog_lifecycle_and_separate_pool_display(tmp_path, monkeypatch, resume):
    events = []
    budget = LocalSharedBudgetBinding(InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100)), Meter())
    @asynccontextmanager
    async def factory():
        events.append("host-open")
        try:
            yield {"pool": budget}
        finally:
            events.append("host-close")
    module = types.ModuleType("tui_budget_test_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    result = SimpleNamespace(session=SimpleNamespace(session_id="session"))
    class Runtime:
        shared_budget = budget

        async def __aenter__(self):
            events.append("runtime-open")
            return self

        async def __aexit__(self, *args):
            events.append("runtime-close")

        async def run(self, prompt, **kwargs):
            events.append("run")
            return result

        async def resume(self, session_id, run_id, **kwargs):
            assert kwargs["approved_call_ids"] == frozenset({"exact-call"})
            events.append("resume")
            return result

    def assemble(*args, **kwargs):
        assert kwargs["shared_budget_bindings"]["pool"] is budget
        return Runtime()
    monkeypatch.setattr(tui, "open_local_runtime", assemble)
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda path: SimpleNamespace(shared_budget=SimpleNamespace(binding="pool")))
    app = App(tmp_path)
    async def no_refresh():
        pass
    monkeypatch.setattr(app, "_refresh_sessions", no_refresh)
    monkeypatch.setattr(app, "_refresh_checkpoints", no_refresh)
    monkeypatch.setattr(app, "_select_pending_checkpoint", lambda run: None)
    monkeypatch.setattr(app, "_show_run_result", lambda target, run: target.update(Text("completed")))
    async with app.run_test(size=(100, 45)):
        prefix = "checkpoint" if resume else "run"
        app.query_one(f"#{prefix}-budget-entry").value = "tui_budget_test_host:factory"
        app.query_one(f"#{prefix}-budget-confirm").value = "LOAD BUDGET"
        app.query_one(f"#{prefix}-confirm").value = "RESUME" if resume else "RUN"
        if resume:
            app.query_one("#checkpoint-session").value = "session"
            app.query_one("#checkpoint-run").value = "run"
            app.query_one("#checkpoint-call").value = "exact-call"
            await app._resume_configured_agent()
        else:
            app.query_one("#run-prompt").value = "hello"
            await app._run_configured_agent()
            assert not app.query_one("#run-budget-entry").disabled
        assert app.query_one(f"#{prefix}-budget-confirm").value == ""
        text = str(app.query_one(f"#{prefix}-budget-result").content)
        assert "shared-pool-not-this-run" in text and "known_usage" in text and "held_usage" in text
        assert "reconciliation" not in text and "reservation_id" not in text
    assert events == ["host-open", "runtime-open", "resume" if resume else "run", "runtime-close", "host-close"]
