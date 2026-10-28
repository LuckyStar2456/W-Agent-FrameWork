"""Named Runtime observation with real local ledgers and deterministic providers."""

import asyncio
from dataclasses import replace

import pytest

from w_agent import (
    BlockEnd, BlockStart, FinishEvent, FinishReason, KnowledgeDocument,
    LocalKnowledgeBinding, LocalRuntimeConfigError, LocalSharedBudgetBinding,
    ModelRequest, ModelMessage, MessageRole, ModelError, ModelFailure, ModelFailureKind,
    NativeCursorRecovery, TokenUsage, UsageEvent, TextContent, assemble_local_provider,
    assemble_local_runtime, collect_stream, local_runtime_config_from_mapping,
    ProviderTemplate, ProviderTemplateRegistry,
)
from w_agent.service_usage import InMemoryServiceUsageLedger, ServiceUsageError, ServiceUsageRecord, ServiceUsageUnit
from w_agent.service_usage_runtime import LocalServiceUsageBinding, LocalServiceUsageConfig, ObservedModelProvider
from w_agent.service_usage_adapters import ObservedSharedBudgetController, ServiceUsageMeasurement
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger
from w_agent._service_usage_ui import service_usage_summary
from tests.test_runtime_shared_budget import Ledger, Meter, Provider, mapping, templates


def configuration(*, budget=False, knowledge=False):
    value = mapping()
    value["service_usage"] = {"binding": "observations"}
    if not budget:
        value.pop("shared_budget")
    if knowledge:
        value["knowledge"] = {"binding": "docs"}
    return local_runtime_config_from_mapping(value)


def request():
    return ModelRequest((ModelMessage.text(MessageRole.USER, "PRIVATE_PROMPT"),), model="model", max_output_tokens=5)


@pytest.mark.parametrize("value", [{}, {"binding": True}, {"binding": "../bad"},
                                    {"binding": "observations", "database": "usage.db"},
                                    {"binding": "observations", "entry": "hidden:code"}])
def test_config_only_selects_opaque_host_binding(value):
    source = mapping()
    source["service_usage"] = value
    with pytest.raises(LocalRuntimeConfigError):
        local_runtime_config_from_mapping(source)
    assert configuration().service_usage == LocalServiceUsageConfig("observations")


def test_missing_binding_and_native_recovery_fail_before_provider_build(tmp_path):
    created = []
    for catalog in (None, {}, {"observations": object()}):
        with pytest.raises(LocalRuntimeConfigError):
            assemble_local_runtime(configuration(), tmp_path, templates=templates(created), service_usage_bindings=catalog)
    binding = LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "operation")
    with pytest.raises(LocalRuntimeConfigError, match="native cursor"):
        assemble_local_runtime(configuration(), tmp_path, templates=templates(created),
                               service_usage_bindings={"observations": binding}, stream_recovery=NativeCursorRecovery())
    assert created == []


@pytest.mark.asyncio
async def test_runtime_tracks_attempts_and_explicit_operation_without_repricing(tmp_path):
    ledger = SQLiteServiceUsageLedger(tmp_path / "usage.db")
    await ledger.initialize(confirm_create=True)
    binding = LocalServiceUsageBinding(ledger, "host-operation")
    created = []
    runtime = assemble_local_runtime(configuration(), tmp_path / "state", templates=templates(created),
                                     service_usage_bindings={"observations": binding})
    assert await ledger.records("host-operation") == ()
    async with runtime:
        first = await runtime.run("PRIVATE_FIRST")
        second = await runtime.run("PRIVATE_SECOND")
        summary = await runtime.service_usage_summary()
    assert first.service_usage_operation_id == second.service_usage_operation_id == "host-operation"
    assert first.result.usage.total_tokens == second.result.usage.total_tokens == 10
    assert summary["scope"] == "host-operation-not-this-run"
    assert summary["known_usage"]["total_tokens"] == 20 and summary["records"] == 2
    assert summary["usage_complete"] is True and summary["cost_complete"] is False
    assert summary["cost_totals"] == []
    records = await SQLiteServiceUsageLedger(tmp_path / "usage.db").records("host-operation")
    assert all(item.granularity == "attempt" for item in records)
    assert "PRIVATE" not in str([item.to_dict() for item in records])
    assert created[0].close_calls == 1


@pytest.mark.asyncio
async def test_shared_budget_observes_one_reservation_and_keeps_snapshot_binding(tmp_path):
    budget, meter, usage, created = Ledger(), Meter(), InMemoryServiceUsageLedger(), []
    budget_binding = LocalSharedBudgetBinding(budget, meter)
    observation = LocalServiceUsageBinding(usage, "operation")
    runtime = assemble_local_runtime(configuration(budget=True), tmp_path, templates=templates(created),
        shared_budget_bindings={"development": budget_binding}, service_usage_bindings={"observations": observation})
    assert runtime.shared_budget is budget_binding
    async with runtime:
        outcome = await runtime.run("question")
        snapshot = await runtime.shared_budget_snapshot()
    records = await usage.records("operation")
    assert len(records) == len(snapshot.entries) == 1
    assert records[0].record_id == snapshot.entries[0].reservation.reservation_id
    assert records[0].usage == snapshot.known_usage == outcome.result.usage
    assert meter.bound_calls == meter.actual_calls == created[0].calls == 1
    assert created[0].close_calls == 1
    assert meter.close_calls == budget.close_calls == 0


def test_preobserved_shared_controller_rejected_without_second_wrap():
    created, ledger = [], InMemoryServiceUsageLedger()
    observed = ObservedSharedBudgetController(Ledger(), ledger, operation_id="operation", service="model", source_ref="s", meter_version="v1")
    with pytest.raises(LocalRuntimeConfigError, match="already observed"):
        assemble_local_provider(configuration(budget=True), templates=templates(created),
            shared_budget_bindings={"development": LocalSharedBudgetBinding(observed, Meter())},
            service_usage_bindings={"observations": LocalServiceUsageBinding(ledger, "operation")})
    assert created == []


@pytest.mark.asyncio
async def test_runtime_retrieval_is_explicit_and_separate_from_model_totals(tmp_path):
    class Retriever:
        async def retrieve(self, query, *, limit):
            return (KnowledgeDocument("id", "PRIVATE_EVIDENCE"),)
    ledger = InMemoryServiceUsageLedger()
    binding = LocalServiceUsageBinding(ledger, "operation", retrieval_source_ref="local-retrieval",
        retrieval_token_scope="not-applicable",
        retrieval_measurement=lambda docs: ServiceUsageMeasurement(units=(ServiceUsageUnit("documents", len(docs)),), units_complete=True))
    runtime = assemble_local_runtime(configuration(knowledge=True), tmp_path, templates=templates([]),
        knowledge_bindings={"docs": LocalKnowledgeBinding(Retriever())}, service_usage_bindings={"observations": binding})
    async with runtime:
        result = await runtime.run("question", knowledge_query="PRIVATE_QUERY", confirm_knowledge_query=True)
    records = await ledger.records("operation")
    assert [item.service for item in records] == ["retrieval", "model"]
    assert records[0].units == (ServiceUsageUnit("documents", 1),)
    assert result.result.usage.total_tokens == 10
    assert "PRIVATE" not in str([item.to_dict() for item in records])
    summary = await service_usage_summary(binding)
    assert summary["runtime_observers"] == ["model", "retrieval"]


@pytest.mark.asyncio
async def test_valid_no_usage_stream_remains_unknown_not_zero():
    class NoUsage(Provider):
        async def stream(self, request, *, cancellation=None):
            yield BlockStart(0, "text")
            yield BlockEnd(0, TextContent("answer"))
            yield FinishEvent(FinishReason.STOP)
    ledger = InMemoryServiceUsageLedger()
    response = await collect_stream(ObservedModelProvider(NoUsage("provider", "model"), LocalServiceUsageBinding(ledger, "op")).stream(request()))
    record = (await ledger.records("op"))[0]
    assert not response.usage_reported and record.status == "completed"
    assert record.usage is None and not record.usage_complete


@pytest.mark.asyncio
async def test_multiple_usage_events_count_only_final_cumulative_report():
    class Updates(Provider):
        async def stream(self, request, *, cancellation=None):
            yield UsageEvent(TokenUsage(2, 1))
            yield UsageEvent(TokenUsage(4, 3))
            yield FinishEvent(FinishReason.STOP)
    ledger = InMemoryServiceUsageLedger()
    await collect_stream(ObservedModelProvider(Updates("p", "m"), LocalServiceUsageBinding(ledger, "op")).stream(request()))
    assert (await ledger.records("op"))[0].usage == TokenUsage(4, 3)


@pytest.mark.asyncio
async def test_provider_errors_remain_retryable_and_attempt_ids_are_distinct():
    ledger = InMemoryServiceUsageLedger()
    provider = Provider("provider", "model", failure=True)
    observer = ObservedModelProvider(provider, LocalServiceUsageBinding(ledger, "op"))
    for _ in range(2):
        with pytest.raises(ModelError):
            await collect_stream(observer.stream(request()))
    records = await ledger.records("op")
    assert len(records) == 2 and records[0].record_id != records[1].record_id
    assert all(item.status == "unknown" for item in records)


@pytest.mark.asyncio
async def test_runtime_retry_observes_physical_attempts_not_only_final_model_calls(tmp_path):
    class FailOnce(Provider):
        async def stream(self, request, *, cancellation=None):
            if self.calls == 0:
                self.calls += 1
                raise ModelError(ModelFailure(ModelFailureKind.NETWORK, "offline", "PRIVATE", True))
            async for event in super().stream(request, cancellation=cancellation):
                yield event
    provider, ledger = FailOnce("provider", "model"), InMemoryServiceUsageLedger()
    registry = ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "test", None, lambda **_: provider),))
    runtime = assemble_local_runtime(configuration(), tmp_path, templates=registry,
        service_usage_bindings={"observations": LocalServiceUsageBinding(ledger, "op")})
    async with runtime:
        outcome = await runtime.run("question")
    records = await ledger.records("op")
    assert provider.calls == 2
    assert [item.status for item in records] == ["unknown", "completed"]
    assert outcome.result.model_calls == 2 and outcome.result.reported_usage_calls == 1
    assert records[1].usage == outcome.result.usage


@pytest.mark.asyncio
async def test_early_close_records_unknown_and_closes_inner_stream():
    closed = []
    class Streaming(Provider):
        async def stream(self, request, *, cancellation=None):
            try:
                yield BlockStart(0, "text")
                await asyncio.Event().wait()
            finally:
                closed.append(True)
    ledger = InMemoryServiceUsageLedger()
    stream = ObservedModelProvider(Streaming("p", "m"), LocalServiceUsageBinding(ledger, "op")).stream(request())
    await anext(stream)
    await stream.aclose()
    assert closed == [True] and (await ledger.records("op"))[0].status == "unknown"


@pytest.mark.asyncio
async def test_task_cancel_records_unknown_and_closes_stream():
    entered, closed = asyncio.Event(), []
    class Waiting(Provider):
        async def stream(self, request, *, cancellation=None):
            try:
                entered.set()
                await asyncio.Event().wait()
                yield FinishEvent(FinishReason.STOP)
            finally:
                closed.append(True)
    ledger = InMemoryServiceUsageLedger()
    observer = ObservedModelProvider(Waiting("p", "m"), LocalServiceUsageBinding(ledger, "op"))
    task = asyncio.create_task(collect_stream(observer.stream(request())))
    await asyncio.wait_for(entered.wait(), 5)
    assert (await ledger.records("op"))[0].status == "started"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True] and (await ledger.records("op"))[0].status == "unknown"


@pytest.mark.asyncio
async def test_malformed_stream_after_finish_never_delivers_success():
    class Trailing(Provider):
        async def stream(self, request, *, cancellation=None):
            yield UsageEvent(TokenUsage(1, 1))
            yield FinishEvent(FinishReason.STOP)
            yield UsageEvent(TokenUsage(2, 2))
    ledger, delivered = InMemoryServiceUsageLedger(), []
    with pytest.raises(ValueError):
        async for event in ObservedModelProvider(Trailing("p", "m"), LocalServiceUsageBinding(ledger, "op")).stream(request()):
            delivered.append(event)
    assert not any(isinstance(event, FinishEvent) for event in delivered)
    assert (await ledger.records("op"))[0].status == "unknown"


@pytest.mark.asyncio
async def test_failed_start_prevents_provider_and_failed_finish_is_not_success():
    class Broken(InMemoryServiceUsageLedger):
        def __init__(self, status):
            super().__init__()
            self.status = status
        async def record(self, value):
            if value.status == self.status:
                raise RuntimeError("PRIVATE_LEDGER")
            await super().record(value)
    for failure, expected_calls in (("started", 0), ("completed", 1)):
        ledger, provider, delivered = Broken(failure), Provider("p", "m"), []
        with pytest.raises(ServiceUsageError):
            async for event in ObservedModelProvider(provider, LocalServiceUsageBinding(ledger, "op")).stream(request()):
                delivered.append(event)
        assert provider.calls == expected_calls
        assert not any(isinstance(event, FinishEvent) for event in delivered)
        if expected_calls:
            assert (await ledger.records("op"))[0].status == "unknown"


@pytest.mark.asyncio
async def test_summary_read_failure_is_warning_and_no_record_ids_are_exposed():
    ledger = InMemoryServiceUsageLedger()
    binding = LocalServiceUsageBinding(ledger, "op")
    await ledger.record(ServiceUsageRecord("op", "PRIVATE-ID", "model", "PRIVATE-SOURCE", "v1"))
    summary = await service_usage_summary(binding)
    assert "PRIVATE" not in str(summary)
    assert summary["unresolved_records"] == 1
    async def broken(_):
        raise RuntimeError("PRIVATE")
    ledger.records = broken
    summary = await service_usage_summary(binding)
    assert summary["status"] == "unavailable" and "PRIVATE" not in str(summary)
