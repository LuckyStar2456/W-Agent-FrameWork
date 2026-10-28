"""CLI/TUI budget-host regressions."""

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import w_agent.cli as cli
from w_agent._shared_budget_ui import BudgetEntryError, budget_binding_scope, shared_budget_summary
from w_agent import InMemorySharedBudget, LocalSharedBudgetBinding, SharedBudgetAmount, SharedBudgetLimits, TokenUsage


class Meter:
    async def bound(self, request):
        return SharedBudgetAmount(TokenUsage(10, 5))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)


def binding():
    return LocalSharedBudgetBinding(InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100)), Meter())


def install(monkeypatch, factory):
    module = types.ModuleType("budget_test_host")
    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return "budget_test_host:factory"


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed,selected", [(False, "pool"), (1, "pool"), (True, None)])
async def test_permission_and_selection_checked_before_import(monkeypatch, confirmed, selected):
    called = []
    entry = install(monkeypatch, lambda: called.append(True))
    with pytest.raises(BudgetEntryError):
        async with budget_binding_scope(entry, selected=selected, confirmed=confirmed):
            pytest.fail("unauthorized host yielded")
    assert not called


@pytest.mark.asyncio
async def test_context_cleanup_cannot_suppress_runtime_error(monkeypatch):
    events = []
    class Context:
        async def __aenter__(self):
            events.append("enter")
            return {"pool": binding()}

        async def __aexit__(self, kind, error, traceback):
            events.append(kind)
            return True  # Must not conceal Runtime exceptions.

    entry = install(monkeypatch, Context)
    with pytest.raises(RuntimeError, match="runtime failed"):
        async with budget_binding_scope(entry, selected="pool", confirmed=True):
            raise RuntimeError("runtime failed")
    assert events == ["enter", RuntimeError]


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog", [{}, {"pool": object()}, {"other": None}, [], {"bad key": None}])
async def test_bad_catalog_closes_before_rejecting(monkeypatch, catalog):
    events = []
    @asynccontextmanager
    async def factory():
        try:
            yield catalog
        finally:
            events.append("closed")
    entry = install(monkeypatch, factory)
    with pytest.raises(BudgetEntryError):
        async with budget_binding_scope(entry, selected="pool", confirmed=True):
            pytest.fail("invalid catalog admitted")
    assert events == ["closed"]


@pytest.mark.asyncio
async def test_cancellation_propagates_and_runs_host_cleanup(monkeypatch):
    events, started = [], asyncio.Event()
    @asynccontextmanager
    async def factory():
        try:
            yield {"pool": binding()}
        finally:
            events.append("closed")
    entry = install(monkeypatch, factory)
    async def work():
        async with budget_binding_scope(entry, selected="pool", confirmed=True):
            started.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(work())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["closed"]


@pytest.mark.asyncio
async def test_host_exceptions_are_fixed_and_do_not_leak_bodies(monkeypatch):
    @asynccontextmanager
    async def factory():
        yield {"pool": binding()}
        raise RuntimeError("PRIVATE_CLEANUP")
    entry = install(monkeypatch, factory)
    with pytest.raises(BudgetEntryError) as caught:
        async with budget_binding_scope(entry, selected="pool", confirmed=True):
            pass
    assert "PRIVATE" not in str(caught.value) and "do not replay" in str(caught.value)


@pytest.mark.asyncio
async def test_pool_display_is_not_run_usage_or_ticket_disclosure():
    bound = binding()
    ticket = await bound.controller.reserve(SharedBudgetAmount(TokenUsage(10, 5, 3)))
    await bound.controller.settle(ticket, None)
    data = await shared_budget_summary(bound)
    assert data["held_usage"] == {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 3, "total_tokens": 15}
    assert data["known_usage"]["total_tokens"] == 0 and data["known_cost"] is None
    assert data["blocked"] and data["tickets"]["unknown"] == 1
    assert ticket.reservation_id not in json.dumps(data)
    assert "entries" not in data and "price_table_version" not in data


@pytest.mark.asyncio
async def test_post_call_display_failure_is_unavailable_not_zero():
    class Reader:
        async def snapshot(self):
            raise RuntimeError("PRIVATE_BILLING_BODY")
    data = await shared_budget_summary(Reader())
    assert data["status"] == "unavailable" and "known_usage" not in data
    assert "PRIVATE" not in json.dumps(data)
    assert await shared_budget_summary(None) is None


@pytest.mark.parametrize("command", [["run", "hello"], ["run-resume", "session", "run", "--approve-tool-call", "call"]])
def test_cli_budget_code_consent_is_separate(monkeypatch, command):
    called = []
    entry = install(monkeypatch, lambda: called.append(True))
    result = CliRunner().invoke(cli.app, [*command, "--budget-entry", entry, "--confirm-model-call"])
    assert result.exit_code != 0 and "confirm-budget-code" in " ".join(result.output.split())
    assert not called


@pytest.mark.parametrize("resume", [False, True])
def test_cli_lifecycle_budget_output_and_exact_resume_arguments(monkeypatch, resume):
    events, budget = [], binding()
    @asynccontextmanager
    async def factory():
        events.append("host-open")
        try:
            yield {"pool": budget}
        finally:
            events.append("host-close")
    entry = install(monkeypatch, factory)
    class Runtime:
        shared_budget = budget

        async def __aenter__(self):
            events.append("runtime-open")
            return self

        async def __aexit__(self, *args):
            events.append("runtime-close")

        async def run(self, prompt, **kwargs):
            events.append("run")
            return object()

        async def resume(self, session_id, run_id, **kwargs):
            assert (session_id, run_id) == ("session", "run")
            assert kwargs["approved_call_ids"] == frozenset({"call"})
            events.append("resume")
            return object()

    def assemble(*args, **kwargs):
        assert kwargs["shared_budget_bindings"]["pool"] is budget
        return Runtime()
    monkeypatch.setattr(cli, "load_local_runtime_config", lambda path: SimpleNamespace(shared_budget=SimpleNamespace(binding="pool")))
    monkeypatch.setattr(cli, "open_local_runtime", assemble)
    monkeypatch.setattr(cli, "_local_run_payload", lambda run: {"stop_reason": "completed"})
    command = (["run-resume", "session", "run", "--approve-tool-call", "call"] if resume else ["run", "hello"])
    result = CliRunner().invoke(cli.app, [*command, "--budget-entry", entry, "--confirm-budget-code", "--confirm-model-call", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["stop_reason"] == "completed" and data["shared_budget"]["status"] == "available"
    assert events == ["host-open", "runtime-open", "resume" if resume else "run", "runtime-close", "host-close"]
