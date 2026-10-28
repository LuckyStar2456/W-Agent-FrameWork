"""Host-only reconciliation regressions."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from decimal import Decimal

import pytest

from w_agent import (
    InMemorySharedBudget, ModelCost, SharedBudgetAmount, SharedBudgetEntry,
    SharedBudgetError, SharedBudgetLimits, SharedBudgetReconciliation,
    SQLiteSharedBudget, TokenUsage,
)


def amount(input_tokens=10, output_tokens=5, cost=None):
    return SharedBudgetAmount(TokenUsage(input_tokens, output_tokens), cost)


def decision(ticket, **kwargs):
    fields = {
        "reconciliation_id": "reconcile-1", "reservation": ticket,
        "expected_status": "unknown", "outcome": "settled", "actual": amount(8, 2),
        "evidence_ref": "billing-record-1", "actor_ref": "local-developer",
    }
    fields.update(kwargs)
    return SharedBudgetReconciliation(**fields)


async def controller(tmp_path, backend, **kwargs):
    limits = kwargs.pop("limits", SharedBudgetLimits(max_total_tokens=100))
    if backend == "memory":
        return InMemorySharedBudget(limits, **kwargs)
    result = SQLiteSharedBudget(tmp_path / "budget.db", "local", limits, **kwargs)
    await result.initialize()
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_unknown_actual_releases_hold_preserves_decision_and_is_idempotent(tmp_path, backend):
    ledger = await controller(tmp_path, backend)
    ticket = await ledger.reserve(amount())
    await ledger.settle(ticket, None)
    resolution = decision(ticket)
    before = await ledger.snapshot()
    for confirmation in (False, None, 1, "yes"):
        with pytest.raises(SharedBudgetError):
            await ledger.reconcile(resolution, confirm_inactive=confirmation)
        assert await ledger.snapshot() == before
    entry = await ledger.reconcile(resolution, confirm_inactive=True)
    assert entry == SharedBudgetEntry(ticket, "settled", amount(8, 2), resolution)
    assert await ledger.reconcile(resolution, confirm_inactive=True) == entry
    view = await ledger.snapshot()
    assert view.entries == (entry,) and not view.blocked
    assert view.known_usage.total_tokens == 10 and view.held_usage.total_tokens == 0
    await ledger.reserve(amount())


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
@pytest.mark.parametrize("status", ["pending", "unknown"])
async def test_no_consumption_requires_explicit_outcome_and_retains_capacity_tombstone(tmp_path, backend, status):
    ledger = await controller(tmp_path, backend, max_reservations=1)
    ticket = await ledger.reserve(amount())
    if status == "unknown":
        await ledger.settle(ticket, None)
    resolution = decision(ticket, expected_status=status, outcome="not-incurred", actual=None)
    result = await ledger.reconcile(resolution, confirm_inactive=True)
    assert result.status == "released" and result.reconciliation == resolution
    await ledger.release(ticket)  # Existing release never deletes the audit receipt.
    view = await ledger.snapshot()
    assert view.entries == (result,) and not view.blocked
    assert view.held_usage.total_tokens == view.known_usage.total_tokens == 0
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount())


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_stale_state_conflicting_decision_and_duplicate_identity_do_not_change_ledger(tmp_path, backend):
    ledger = await controller(tmp_path, backend)
    first, second = await ledger.reserve(amount()), await ledger.reserve(amount())
    await ledger.settle(first, None)
    before = await ledger.snapshot()
    with pytest.raises(SharedBudgetError):
        await ledger.reconcile(decision(first, expected_status="pending"), confirm_inactive=True)
    assert await ledger.snapshot() == before
    resolution = decision(first)
    await ledger.reconcile(resolution, confirm_inactive=True)
    after = await ledger.snapshot()
    for changed in (
        replace(resolution, reconciliation_id="another-id"),
        replace(resolution, evidence_ref="another-reference"),
        replace(resolution, actor_ref="another-actor"),
        replace(resolution, actual=amount(8, 3)),
        decision(second, expected_status="pending"),
    ):
        with pytest.raises(SharedBudgetError):
            await ledger.reconcile(changed, confirm_inactive=True)
        assert await ledger.snapshot() == after
    with pytest.raises(SharedBudgetError):
        await ledger.settle(first, amount(8, 2))  # Late writers cannot overwrite a host decision.
    with pytest.raises(SharedBudgetError):
        await ledger.settle(first, None)
    assert await ledger.snapshot() == after


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_reconciliation_never_rewrites_known_usage_or_another_unknown(tmp_path, backend):
    ledger = await controller(tmp_path, backend)
    first, second, third = [await ledger.reserve(amount()) for _ in range(3)]
    await ledger.settle(first, amount(8, 2))
    await ledger.settle(second, None)
    await ledger.settle(third, None)
    with pytest.raises(SharedBudgetError):
        await ledger.reconcile(decision(first), confirm_inactive=True)
    await ledger.reconcile(decision(second), confirm_inactive=True)
    view = await ledger.snapshot()
    assert view.blocked and view.known_usage.total_tokens == 20 and view.held_usage.total_tokens == 15
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount())
    await ledger.reconcile(decision(third, reconciliation_id="reconcile-2", outcome="not-incurred", actual=None),
                           confirm_inactive=True)
    assert not (await ledger.snapshot()).blocked


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_reconciled_overbound_actual_keeps_breach_latched(tmp_path, backend):
    ledger = await controller(tmp_path, backend)
    first, second = await ledger.reserve(amount()), await ledger.reserve(amount())
    await ledger.settle(first, None)
    await ledger.reconcile(decision(first, actual=amount(101, 1)), confirm_inactive=True)
    await ledger.reconcile(decision(second, reconciliation_id="reconcile-2", expected_status="pending",
                                    outcome="not-incurred", actual=None), confirm_inactive=True)
    view = await ledger.snapshot()
    assert view.breached and view.blocked and view.known_usage.total_tokens == 102
    with pytest.raises(SharedBudgetError):
        await ledger.reserve(amount(0, 0))
    if backend == "sqlite":
        assert await (await controller(tmp_path, backend)).snapshot() == view


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_prices_must_match_and_inactive_confirmation_is_not_a_refund(tmp_path, backend):
    limits = SharedBudgetLimits(max_cost="1.00", currency="USD", price_table_version="v1")
    ledger = await controller(tmp_path, backend, limits=limits)
    ticket = await ledger.reserve(amount(cost=ModelCost("USD", "v1", ".80")))
    await ledger.settle(ticket, None)
    before = await ledger.snapshot()
    for cost in (None, ModelCost("CNY", "v1", ".5"), ModelCost("USD", "v2", ".5")):
        with pytest.raises(SharedBudgetError):
            await ledger.reconcile(decision(ticket, actual=amount(8, 2, cost)), confirm_inactive=True)
        assert await ledger.snapshot() == before
    actual = amount(8, 2, ModelCost("USD", "v1", ".60"))
    await ledger.reconcile(decision(ticket, actual=actual), confirm_inactive=True)
    view = await ledger.snapshot()
    assert view.known_cost == Decimal(".60") and view.held_cost == 0
    assert not view.blocked


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "sqlite"])
async def test_normal_settlement_and_reconciliation_cannot_both_win(tmp_path, backend):
    ledger = await controller(tmp_path, backend)
    ticket = await ledger.reserve(amount())
    other = await controller(tmp_path, backend) if backend == "sqlite" else ledger
    results = await asyncio.gather(
        ledger.settle(ticket, amount(8, 2)),
        other.reconcile(decision(ticket, expected_status="pending"), confirm_inactive=True),
        return_exceptions=True,
    )
    assert sum(isinstance(result, SharedBudgetError) for result in results) == 1
    assert (await ledger.snapshot()).known_usage.total_tokens == 10


@pytest.mark.asyncio
async def test_sqlite_concurrent_conflicts_and_retry_after_reopening(tmp_path):
    first, second = await controller(tmp_path, "sqlite"), await controller(tmp_path, "sqlite")
    ticket = await first.reserve(amount())
    await first.settle(ticket, None)
    decisions = [decision(ticket), decision(ticket, reconciliation_id="reconcile-2", actual=amount(9, 2))]
    results = await asyncio.gather(
        first.reconcile(decisions[0], confirm_inactive=True),
        second.reconcile(decisions[1], confirm_inactive=True), return_exceptions=True,
    )
    winners = [result for result in results if isinstance(result, SharedBudgetEntry)]
    assert len(winners) == 1
    assert sum(isinstance(result, SharedBudgetError) for result in results) == 1
    reopened = await controller(tmp_path, "sqlite")
    assert await reopened.reconcile(winners[0].reconciliation, confirm_inactive=True) == winners[0]
    assert (await reopened.snapshot()).entries == tuple(winners)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["extra", "missing", "identity", "outcome", "state", "null", "version"])
async def test_corrupt_persisted_decisions_fail_closed(tmp_path, mutation):
    ledger = await controller(tmp_path, "sqlite")
    ticket = await ledger.reserve(amount())
    await ledger.reconcile(decision(ticket, expected_status="pending"), confirm_inactive=True)
    with closing(sqlite3.connect(ledger.database_path)) as db, db:
        data = json.loads(db.execute("SELECT payload FROM shared_tickets").fetchone()[0])
        if mutation == "extra":
            data["reconciliation"]["body"] = "PRIVATE_CONTENT"
        elif mutation == "missing":
            del data["reconciliation"]["actor_ref"]
        elif mutation == "identity":
            data["reconciliation"]["reconciliation_id"] = "PRIVATE CONTENT"
        elif mutation == "outcome":
            data["reconciliation"]["outcome"] = "not-incurred"
        elif mutation == "state":
            data["reconciliation"]["expected_status"] = "settled"
        elif mutation == "null":
            data["reconciliation"] = None
        elif mutation == "version":
            data["schema_version"] = 1
        db.execute("UPDATE shared_tickets SET payload = ?", (json.dumps(data),))
    with pytest.raises(SharedBudgetError) as caught:
        await ledger.snapshot()
    assert "PRIVATE" not in str(caught.value) and not caught.value.failure.retryable


@pytest.mark.asyncio
async def test_duplicate_reconciliation_id_in_storage_is_not_accepted(tmp_path):
    ledger = await controller(tmp_path, "sqlite")
    tickets = [await ledger.reserve(amount()) for _ in range(2)]
    for index, ticket in enumerate(tickets):
        await ledger.reconcile(decision(ticket, expected_status="pending", reconciliation_id=f"fix-{index}"),
                               confirm_inactive=True)
    with closing(sqlite3.connect(ledger.database_path)) as db, db:
        data = json.loads(db.execute("SELECT payload FROM shared_tickets WHERE reservation_id = ?",
                                     (tickets[1].reservation_id,)).fetchone()[0])
        data["reconciliation"]["reconciliation_id"] = "fix-0"
        db.execute("UPDATE shared_tickets SET payload = ? WHERE reservation_id = ?",
                   (json.dumps(data), tickets[1].reservation_id))
    with pytest.raises(SharedBudgetError):
        await ledger.snapshot()


@pytest.mark.asyncio
async def test_cancel_after_commit_retry_same_decision_does_not_double_count(tmp_path, monkeypatch):
    ledger = await controller(tmp_path, "sqlite")
    ticket = await ledger.reserve(amount())
    resolution = decision(ticket, expected_status="pending")
    committed, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = SQLiteSharedBudget._operate

    def paused(self, operation, reservation=None, amount=None, **kwargs):
        result = original(self, operation, reservation, amount, **kwargs)
        if operation == "reconcile":
            committed.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("test worker barrier timed out")
            finally:
                finished.set()
        return result

    monkeypatch.setattr(SQLiteSharedBudget, "_operate", paused)
    task = asyncio.create_task(ledger.reconcile(resolution, confirm_inactive=True))
    try:
        assert await asyncio.to_thread(committed.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    reopened = await controller(tmp_path, "sqlite")
    await reopened.reconcile(resolution, confirm_inactive=True)
    view = await reopened.snapshot()
    assert len(view.entries) == 1 and view.known_usage.total_tokens == 10


@pytest.mark.asyncio
async def test_storage_limit_rollback_preserves_original_unresolved_ticket(tmp_path, monkeypatch):
    import w_agent.shared_budget_sqlite as storage

    # Bind a deliberately small test-only byte cap before initializing config.
    monkeypatch.setattr(storage, "_MAX_LEDGER_BYTES", 400)
    ledger = await controller(tmp_path, "sqlite")
    ticket = await ledger.reserve(amount())
    await ledger.settle(ticket, None)
    before = await ledger.snapshot()
    resolution = decision(ticket, evidence_ref="e" * 128, actor_ref="a" * 128)
    with pytest.raises(SharedBudgetError):
        await ledger.reconcile(resolution, confirm_inactive=True)
    assert await ledger.snapshot() == before


@pytest.mark.parametrize("changes", [
    {"expected_status": "settled"}, {"expected_status": "released"}, {"outcome": "refund"},
    {"evidence_ref": ""}, {"evidence_ref": "a" * 129}, {"actor_ref": "contains spaces"},
    {"reconciliation_id": "https://billing.example/id"}, {"actual": None},
    {"outcome": "not-incurred"}, {"reservation": None},
])
def test_decision_validation_rejects_ambiguous_or_body_like_inputs(changes):
    from w_agent import SharedBudgetReservation

    ticket = SharedBudgetReservation("ticket", amount())
    with pytest.raises(ValueError):
        decision(ticket, **changes)
