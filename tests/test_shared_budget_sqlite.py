"""Durable shared-budget regression source; execution needs user authorization."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from decimal import Decimal

import pytest

from w_agent import (
    BlockEnd, BlockStart, FinishEvent, FinishReason, MessageRole, ModelCost,
    ModelMessage, ModelRequest, SharedBudgetAmount, SharedBudgetError, SharedBudgetLimits,
    SharedBudgetModelProvider, SQLiteSessionSummaryObserver, SQLiteSharedBudget,
    TextContent, TokenUsage, UsageEvent,
)
from w_agent.models import collect_stream


def amount(input_tokens=10, output_tokens=5, cost=None):
    return SharedBudgetAmount(TokenUsage(input_tokens, output_tokens), cost)


def ledger(tmp_path, budget_id="development", **kwargs):
    limits = kwargs.pop("limits", SharedBudgetLimits(max_total_tokens=100))
    return SQLiteSharedBudget(tmp_path / "budget.db", budget_id, limits, **kwargs)


@pytest.mark.asyncio
async def test_explicit_initialization_no_parent_creation_or_read_fallback(tmp_path):
    controller = ledger(tmp_path)
    assert not controller.database_path.exists()
    for operation in (controller.snapshot, lambda: controller.reserve(amount())):
        with pytest.raises(SharedBudgetError):
            await operation()
    assert not controller.database_path.exists()
    with pytest.raises(SharedBudgetError):
        await ledger(tmp_path / "missing").initialize()
    assert not (tmp_path / "missing").exists()
    await controller.initialize()
    await controller.initialize()
    assert (await controller.snapshot()).entries == ()
    other = ledger(tmp_path, "not-initialized")
    with pytest.raises(SharedBudgetError):
        await other.snapshot()


@pytest.mark.asyncio
async def test_reopening_preserves_all_statuses_and_idempotency(tmp_path):
    controller = ledger(tmp_path)
    await controller.initialize()
    settled, released, pending, unknown = [await controller.reserve(amount()) for _ in range(4)]
    await controller.settle(settled, amount(8, 2))
    await controller.release(released)
    await controller.settle(unknown, None)
    reopened = ledger(tmp_path)
    await reopened.initialize()
    assert await reopened.snapshot() == await controller.snapshot()
    view = await reopened.snapshot()
    assert [entry.status for entry in view.entries] == ["settled", "released", "pending", "unknown"]
    assert view.known_usage.total_tokens == 10 and view.held_usage.total_tokens == 30
    assert view.blocked and not view.breached
    await reopened.settle(settled, amount(8, 2))
    await reopened.release(released)
    await reopened.settle(unknown, None)
    for operation in (
        lambda: reopened.reserve(amount(0, 0)),
        lambda: reopened.settle(settled, amount(8, 3)),
        lambda: reopened.settle(unknown, amount(0, 0)),
        lambda: reopened.release(unknown),
    ):
        with pytest.raises(SharedBudgetError):
            await operation()
    assert await reopened.snapshot() == view
    # Already admitted calls can finish even when another call is unknown.
    await reopened.settle(pending, amount(8, 2))
    assert (await controller.snapshot()).known_usage.total_tokens == 20


@pytest.mark.asyncio
async def test_same_file_instances_serialize_admission_and_keep_tombstones(tmp_path):
    controllers = [ledger(tmp_path, limits=SharedBudgetLimits(max_total_tokens=20),
                          max_reservations=1, timeout=5) for _ in range(8)]
    await asyncio.gather(*(controller.initialize() for controller in controllers))
    results = await asyncio.gather(*(controller.reserve(amount()) for controller in controllers),
                                   return_exceptions=True)
    tickets = [result for result in results if not isinstance(result, Exception)]
    assert len(tickets) == 1
    assert all(isinstance(result, SharedBudgetError) for result in results if isinstance(result, Exception))
    await controllers[-1].release(tickets[0])
    assert (await controllers[0].snapshot()).held_usage.total_tokens == 0
    with pytest.raises(SharedBudgetError):
        await controllers[0].reserve(amount())


@pytest.mark.asyncio
async def test_reopened_costs_and_overbound_actuals_are_not_reset(tmp_path):
    limits = SharedBudgetLimits(max_cost="1.00", currency="USD", price_table_version="rates-v1")
    controller = ledger(tmp_path, limits=limits)
    await controller.initialize()
    ticket = await controller.reserve(amount(cost=ModelCost("USD", "rates-v1", ".80")))
    actual = amount(8, 2, ModelCost("USD", "rates-v1", "1.20"))
    await controller.settle(ticket, actual)
    reopened = ledger(tmp_path, limits=limits)
    await reopened.initialize()
    await reopened.settle(ticket, actual)
    view = await reopened.snapshot()
    assert view.known_cost == Decimal("1.20") and view.held_cost == 0
    assert view.breached and view.blocked
    with pytest.raises(SharedBudgetError):
        await reopened.reserve(amount(0, 0, ModelCost("USD", "rates-v1", 0)))


@pytest.mark.asyncio
async def test_unknown_cost_and_cached_subset_remain_held_after_reopen(tmp_path):
    limits = SharedBudgetLimits(max_cost="1", currency="USD", price_table_version="v1")
    controller = ledger(tmp_path, limits=limits)
    await controller.initialize()
    for cost in (None, ModelCost("CNY", "v1", ".1"), ModelCost("USD", "v2", ".1")):
        with pytest.raises(SharedBudgetError):
            await controller.reserve(amount(cost=cost))
    ticket = await controller.reserve(
        SharedBudgetAmount(TokenUsage(10, 5, 3), ModelCost("USD", "v1", ".80")),
    )
    await controller.settle(ticket, None)
    view = await ledger(tmp_path, limits=limits).snapshot()
    assert view.held_cost == Decimal(".80") and view.known_cost == 0
    assert view.held_usage.total_tokens == 15 and view.held_usage.cached_input_tokens == 3
    assert view.blocked and not view.breached


@pytest.mark.asyncio
async def test_budget_keys_and_bound_configuration(tmp_path):
    first, second = ledger(tmp_path, "first"), ledger(tmp_path, "second")
    await first.initialize()
    await second.initialize()
    ticket = await first.reserve(amount())
    assert (await second.snapshot()).entries == ()
    with pytest.raises(SharedBudgetError):
        await second.release(ticket)
    for changed in (
        ledger(tmp_path, "first", max_reservations=2),
        ledger(tmp_path, "first", limits=SharedBudgetLimits(max_total_tokens=101)),
    ):
        with pytest.raises(SharedBudgetError):
            await changed.initialize()
        with pytest.raises(SharedBudgetError):
            await changed.reserve(amount())
    assert (await first.snapshot()).held_usage.total_tokens == 15


@pytest.mark.asyncio
async def test_summary_store_is_not_silently_reused(tmp_path):
    observer = SQLiteSessionSummaryObserver(tmp_path / "budget.db", "operation")
    await observer.initialize()
    with pytest.raises(SharedBudgetError):
        await ledger(tmp_path).initialize()
    assert await observer.reports() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "schema", "boolean", "negative", "identity", "status", "missing_actual",
    "unexpected_actual", "price", "oversize", "extra", "duplicate", "nan", "overcap",
])
async def test_corrupt_ticket_rejected_without_leaking_payload(tmp_path, mutation):
    controller = ledger(tmp_path)
    await controller.initialize()
    await controller.reserve(amount())
    with closing(sqlite3.connect(controller.database_path)) as db, db:
        data = json.loads(db.execute("SELECT payload FROM shared_tickets").fetchone()[0])
        if mutation == "schema":
            data["schema_version"] = 2
        elif mutation == "boolean":
            data["reserved"]["input_tokens"] = True
        elif mutation == "negative":
            data["reserved"]["input_tokens"] = -1
        elif mutation == "identity":
            data["reservation_id"] = "PRIVATE_CONTENT"
        elif mutation == "status":
            data["status"] = "PRIVATE_CONTENT"
        elif mutation == "missing_actual":
            data["status"] = "settled"
        elif mutation == "unexpected_actual":
            data["actual"] = data["reserved"]
        elif mutation == "price":
            data["reserved"]["cost"] = {
                "currency": "USD", "price_table_version": "v1", "input_cost": "1",
                "output_cost": "0", "cached_input_cost": "0",
            }
        elif mutation == "oversize":
            data["extra"] = "PRIVATE_CONTENT" * 2000
        elif mutation == "extra":
            data["extra"] = "PRIVATE_CONTENT"
        elif mutation == "overcap":
            data["reserved"]["input_tokens"] = 101
        payload = json.dumps(data)
        if mutation == "duplicate":
            payload = payload[:-1] + ', "status": "pending"}'
        elif mutation == "nan":
            payload = payload.replace('"input_tokens": 10', '"input_tokens": NaN')
        db.execute("UPDATE shared_tickets SET payload = ?", (payload,))
    for operation in (controller.snapshot, controller.initialize, lambda: controller.reserve(amount())):
        with pytest.raises(SharedBudgetError) as caught:
            await operation()
        assert "PRIVATE_CONTENT" not in str(caught.value)
        assert not caught.value.failure.retryable


@pytest.mark.asyncio
async def test_schema_version_lock_and_changed_config_fail_closed(tmp_path):
    controller = ledger(tmp_path, timeout=.01)
    await controller.initialize()
    with closing(sqlite3.connect(controller.database_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(SharedBudgetError):
            await controller.reserve(amount())
        db.rollback()
    assert (await controller.snapshot()).entries == ()
    with closing(sqlite3.connect(controller.database_path)) as db, db:
        db.execute("UPDATE shared_budgets SET config = ?", ('{"PRIVATE_CONTENT": true}',))
    with pytest.raises(SharedBudgetError):
        await controller.snapshot()
    with closing(sqlite3.connect(controller.database_path)) as db, db:
        db.execute("PRAGMA user_version = 999")
    with pytest.raises(SharedBudgetError):
        await controller.initialize()


@pytest.mark.asyncio
async def test_cancelled_wait_does_not_refund_worker_committed_ticket(tmp_path, monkeypatch):
    controller = ledger(tmp_path)
    await controller.initialize()
    committed, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = SQLiteSharedBudget._operate

    def paused(self, operation, reservation=None, amount=None):
        result = original(self, operation, reservation, amount)
        if operation == "reserve":
            committed.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("test worker barrier timed out")
            finally:
                finished.set()
        return result

    monkeypatch.setattr(SQLiteSharedBudget, "_operate", paused)
    task = asyncio.create_task(controller.reserve(amount()))
    try:
        assert await asyncio.to_thread(committed.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    view = await ledger(tmp_path).snapshot()
    assert len(view.entries) == 1 and view.entries[0].status == "pending"
    assert view.held_usage.total_tokens == 15


@pytest.mark.asyncio
async def test_provider_assembly_reopened_ledger_enforces_shared_pool(tmp_path):
    controller = ledger(tmp_path, limits=SharedBudgetLimits(max_total_tokens=25))
    await controller.initialize()

    class Meter:
        async def bound(self, request):
            return amount()

        async def actual(self, request, usage):
            return SharedBudgetAmount(usage)

    class Provider:
        calls = 0

        async def stream(self, request, *, cancellation=None):
            self.calls += 1
            yield BlockStart(0, "text")
            yield BlockEnd(0, TextContent("PRIVATE_RESPONSE"))
            yield UsageEvent(TokenUsage(8, 2))
            yield FinishEvent(FinishReason.STOP)

    provider = Provider()
    request = ModelRequest((ModelMessage.text(MessageRole.USER, "PRIVATE_INPUT"),), max_output_tokens=5)
    for _ in range(2):
        reopened = ledger(tmp_path, limits=SharedBudgetLimits(max_total_tokens=25))
        wrapper = SharedBudgetModelProvider(provider, reopened, Meter())
        assert (await collect_stream(wrapper.stream(request))).usage.total_tokens == 10
    with pytest.raises(SharedBudgetError):
        await collect_stream(wrapper.stream(request))
    assert provider.calls == 2
    with closing(sqlite3.connect(controller.database_path)) as db:
        payloads = str(db.execute("SELECT payload FROM shared_tickets").fetchall())
    assert "PRIVATE_INPUT" not in payloads and "PRIVATE_RESPONSE" not in payloads


@pytest.mark.parametrize("options", [
    {"budget_id": ""}, {"budget_id": "../escape"}, {"max_reservations": True},
    {"max_reservations": 0}, {"timeout": True}, {"timeout": 0}, {"timeout": float("nan")},
])
def test_invalid_constructor_options(tmp_path, options):
    with pytest.raises(ValueError):
        ledger(tmp_path, **options)


def test_memory_path_is_not_persistent():
    with pytest.raises(ValueError):
        SQLiteSharedBudget(":memory:", "local", SharedBudgetLimits(max_total_tokens=10))
