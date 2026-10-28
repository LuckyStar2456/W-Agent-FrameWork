"""Scoped cross-service ledger/adapter evidence; no remote calls."""

import asyncio
import sqlite3
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext

import pytest

from w_agent.models import ModelCost, TokenUsage
from w_agent.service_usage import (
    InMemoryServiceUsageLedger, ServiceUsageError, ServiceUsageRecord, ServiceUsageUnit,
    aggregate_service_usage, service_usage_from_budget_entry,
)
from w_agent.service_usage_adapters import (
    ObservedSharedBudgetController, ServiceUsageMeasurement, observe_service_call,
    ObservedKnowledgeRetriever, ObservedKnowledgeReranker,
)
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger
from w_agent.shared_budget import InMemorySharedBudget, SharedBudgetAmount, SharedBudgetLimits


def record(identity="one", **kwargs):
    return ServiceUsageRecord("operation", identity, "model", "provider", "meter-v1", **kwargs)


@pytest.fixture(params=["memory", "sqlite"])
async def ledger(request, tmp_path):
    if request.param == "memory":
        return InMemoryServiceUsageLedger()
    result = SQLiteServiceUsageLedger(tmp_path / "service.db")
    await result.initialize(confirm_create=True)
    return result


@pytest.mark.asyncio
async def test_idempotent_transitions_and_unknown_reconciliation(ledger):
    started = record()
    await ledger.record(started)
    await ledger.record(started)
    unknown = replace(started, status="unknown")
    await ledger.record(unknown)
    complete = replace(started, status="completed", usage=TokenUsage(5, 2), usage_complete=True)
    with pytest.raises(ServiceUsageError):
        await ledger.record(complete)
    complete = replace(complete, reconciliation_ref="review-1")
    await ledger.record(complete)
    await ledger.record(complete)
    with pytest.raises(ServiceUsageError):
        await ledger.record(replace(complete, usage=TokenUsage(6, 2)))
    assert await ledger.records("operation") == (complete,)


@pytest.mark.asyncio
async def test_identity_conflicts_and_model_run_double_count_guard(ledger):
    await ledger.record(record())
    with pytest.raises(ServiceUsageError):
        await ledger.record(replace(record(), source_ref="different"))
    with pytest.raises(ServiceUsageError):
        await ledger.record(record("run", granularity="run"))
    assert len(await ledger.records("operation")) == 1


def test_unknown_not_zero_and_non_token_applicability():
    retrieval = ServiceUsageRecord("operation", "retrieval", "retrieval", "local", "v1", status="completed", token_scope="not-applicable", units=(ServiceUsageUnit("documents", 3),), units_complete=True)
    view = aggregate_service_usage((retrieval,))
    assert view["usage_complete"] is True
    assert view["cost_complete"] is False
    assert view["cost_totals"] == []
    assert view["incomplete_token_records"] == []
    assert view["incomplete_cost_records"] == ["retrieval"]
    assert view["unit_totals"][0]["count"] == 3
    pending = replace(retrieval, status="started", units=(), units_complete=False)
    assert aggregate_service_usage((pending,))["usage_complete"] is False
    assert aggregate_service_usage(())["cost_complete"] is False


def test_currency_table_isolation_and_exact_decimal_aggregation():
    a = record("a", status="completed", cost=ModelCost("USD", "v1", "1000000000000000000000000000"))
    b = record("b", status="completed", cost=ModelCost("USD", "v1", "0.0000000000000000000000000001"))
    c = record("c", status="completed", cost=ModelCost("USD", "v2", "2"))
    d = record("d", status="completed", cost=ModelCost("CNY", "v1", "3"))
    groups = aggregate_service_usage((a, b, c, d))["cost_totals"]
    assert len(groups) == 3
    usd = next(item for item in groups if item["currency"] == "USD" and item["price_table_version"] == "v1")
    assert usd["total"] == "1000000000000000000000000000.0000000000000000000000000001"


def test_aggregation_precision_and_exponent_range_ignore_host_context():
    large = record("large", status="completed", cost=ModelCost("USD", "v1", "1E28"))
    tiny = record("tiny", status="completed", cost=ModelCost("USD", "v1", "1E-28"))
    with localcontext() as hostile:
        hostile.prec = 2
        hostile.Emin = -9
        hostile.Emax = 9
        hostile.traps[Inexact] = True
        total = aggregate_service_usage((large, tiny))["cost_totals"][0]["total"]
        assert hostile.prec == 2
    assert total == "10000000000000000000000000000.0000000000000000000000000001"


@pytest.mark.parametrize("amount", ["1E+999999", "1E-999999", "12345678901234567890123456789"])
def test_cost_magnitude_and_precision_bounds(amount):
    with pytest.raises(ValueError):
        record(status="completed", cost=ModelCost("USD", "v1", amount))


def test_run_import_requires_explicit_final_and_rejects_approval_checkpoint():
    from w_agent.agents import RunResult, StopReason
    from w_agent.service_usage import service_usage_from_run
    result = RunResult("run", StopReason.COMPLETED, "SECRET", (), (), 1, 0,
                       usage=TokenUsage(2, 3), model_calls=1, reported_usage_calls=1)
    options = dict(operation_id="operation", source_ref="run-source", meter_version="v1")
    with pytest.raises(ValueError):
        service_usage_from_run(result, **options)
    with pytest.raises(ValueError):
        service_usage_from_run(replace(result, stop_reason=StopReason.NEEDS_APPROVAL), confirm_final=True, **options)
    converted = service_usage_from_run(result, confirm_final=True, **options)
    assert converted.granularity == "run"
    assert "SECRET" not in str(converted.to_dict())
    with pytest.raises(ValueError):
        service_usage_from_run(replace(result, reported_usage_calls=2), confirm_final=True, **options)


@pytest.mark.asyncio
async def test_started_precedes_call_and_mapper_never_persists_bodies(ledger):
    async def call():
        assert (await ledger.records("operation"))[0].status == "started"
        return "SECRET_RESULT"
    result = await observe_service_call(call, ledger, operation_id="operation", service="retrieval", source_ref="search", meter_version="v1", token_scope="not-applicable", measurement=lambda _: ServiceUsageMeasurement(units=(ServiceUsageUnit("requests", 1),), units_complete=True))
    assert result == "SECRET_RESULT"
    observed = await ledger.records("operation")
    assert "SECRET_RESULT" not in str(observed[0].to_dict())
    assert observed[0].cost is None


@pytest.mark.asyncio
async def test_cancel_records_unknown_and_propagates(ledger):
    entered = asyncio.Event()
    async def call():
        entered.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(observe_service_call(call, ledger, operation_id="operation", service="rerank", source_ref="reranker", meter_version="v1"))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ledger.records("operation"))[0].status == "unknown"


@pytest.mark.asyncio
async def test_start_write_failure_prevents_service_call():
    called = []
    class Broken:
        async def record(self, item):
            raise RuntimeError("SECRET")
    async def call():
        called.append(1)
    with pytest.raises(ServiceUsageError) as error:
        await observe_service_call(call, Broken(), operation_id="operation", service="retrieval", source_ref="search", meter_version="v1")
    assert not called
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_known_budget_settlement_not_downgraded_after_observer_failure():
    budget = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    ledger = InMemoryServiceUsageLedger()
    class FailOneCompletion:
        failed = False
        async def record(self, item):
            if item.status == "completed" and not self.failed:
                self.failed = True
                raise OSError("disk full")
            await ledger.record(item)
    observed = ObservedSharedBudgetController(budget, FailOneCompletion(), operation_id="operation", service="model", source_ref="provider", meter_version="v1")
    ticket = await observed.reserve(SharedBudgetAmount(TokenUsage(10, 10)))
    with pytest.raises(ServiceUsageError):
        await observed.settle(ticket, SharedBudgetAmount(TokenUsage(5, 2)))
    assert (await budget.snapshot()).entries[0].status == "settled"
    assert (await ledger.records("operation"))[0].status == "started"
    await observed.settle(ticket, None)  # Existing provider cleanup path.
    assert (await budget.snapshot()).entries[0].actual.usage.total_tokens == 7
    assert (await ledger.records("operation"))[0].usage.total_tokens == 7
    with pytest.raises(ServiceUsageError):
        await observed.release(ticket)


@pytest.mark.asyncio
async def test_start_observer_failure_releases_budget_before_provider_entry():
    budget = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=100))
    class Broken:
        async def record(self, item):
            raise OSError
    observed = ObservedSharedBudgetController(budget, Broken(), operation_id="operation", service="embedding", source_ref="embedder", meter_version="v1")
    with pytest.raises(ServiceUsageError):
        await observed.reserve(SharedBudgetAmount(TokenUsage(10, 0)))
    assert (await budget.snapshot()).entries[0].status == "released"


@pytest.mark.asyncio
async def test_retrieval_and_rerank_actual_local_adapters(ledger):
    from w_agent.knowledge_context import InMemoryKnowledgeDocumentStore, KnowledgeDocument
    from w_agent.knowledge_retrieval import BM25KnowledgeRetriever, BM25KnowledgeReranker
    docs = (KnowledgeDocument("doc", "refund seven days"),)
    retriever = ObservedKnowledgeRetriever(BM25KnowledgeRetriever(InMemoryKnowledgeDocumentStore(docs)), ledger, "operation", "bm25", "v1", token_scope="not-applicable")
    reranker = ObservedKnowledgeReranker(BM25KnowledgeReranker(), ledger, "operation", "rerank", "v1", token_scope="not-applicable")
    selected = await retriever.retrieve("refund", limit=1)
    assert await reranker.rerank("refund", selected, limit=1) == (0,)
    records = await ledger.records("operation")
    assert {item.service for item in records} == {"retrieval", "rerank"}
    assert all(item.cost is None for item in records)


@pytest.mark.asyncio
async def test_sqlite_explicit_initialization_reopen_capacity_and_foreign_db(tmp_path):
    path = tmp_path / "usage.db"
    store = SQLiteServiceUsageLedger(path, max_records=1)
    assert not path.exists()
    with pytest.raises(ServiceUsageError):
        await store.initialize()
    await store.initialize(confirm_create=True)
    await store.record(record())
    reopened = SQLiteServiceUsageLedger(path, max_records=1)
    assert await reopened.records("operation") == (record(),)
    with pytest.raises(ServiceUsageError):
        await reopened.record(record("second"))
    with pytest.raises(ServiceUsageError):
        await SQLiteServiceUsageLedger(path).initialize(confirm_create=True)
    foreign = tmp_path / "foreign.db"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE user_data (value TEXT)")
    with pytest.raises(ServiceUsageError):
        await SQLiteServiceUsageLedger(foreign).initialize(confirm_create=True)


@pytest.mark.asyncio
async def test_sqlite_concurrent_conflicting_terminal_writes(tmp_path):
    path = tmp_path / "usage.db"
    first, second = SQLiteServiceUsageLedger(path), SQLiteServiceUsageLedger(path)
    await first.initialize(confirm_create=True)
    await first.record(record())
    a = record(status="completed", usage=TokenUsage(1, 0), usage_complete=True)
    b = replace(a, usage=TokenUsage(2, 0))
    results = await asyncio.gather(first.record(a), second.record(b), return_exceptions=True)
    assert sum(isinstance(item, ServiceUsageError) for item in results) == 1
    assert (await first.records("operation"))[0] in (a, b)
