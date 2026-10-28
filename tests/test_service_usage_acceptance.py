"""Real local ledgers, real wrappers, offline services: one composed usage path."""

import json

import pytest

from w_agent import (
    BM25KnowledgeReranker, BlockEnd, BlockStart, EmbeddingResult, FinishEvent,
    FinishReason, InMemoryKnowledgeDocumentStore, KeywordKnowledgeRetriever,
    KnowledgeDocument, MessageRole, ModelCost, ModelMessage, ModelRequest,
    RerankedKnowledgeRetriever, SharedBudgetAmount, SharedBudgetError,
    SharedBudgetLimits, SharedBudgetModelProvider, SharedBudgetTextEmbedder,
    SQLiteSharedBudget, TextContent, TokenUsage, UsageEvent,
)
from w_agent.models import collect_stream
from w_agent.service_usage import ServiceUsageUnit, aggregate_service_usage
from w_agent.service_usage_adapters import (
    ObservedKnowledgeReranker, ObservedKnowledgeRetriever,
    ObservedSharedBudgetController, ServiceUsageMeasurement,
)
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger


class OfflineModel:
    calls = 0

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent("PRIVATE_MODEL_OUTPUT"))
        yield UsageEvent(TokenUsage(4, 2))
        yield FinishEvent(FinishReason.STOP)


class ModelMeter:
    async def bound(self, request):
        return SharedBudgetAmount(TokenUsage(10, 5), ModelCost("USD", "host-v1", "0.10"))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage, ModelCost("USD", "host-v1", "0.02"))


class OfflineEmbedding:
    async def embed_result(self, text):
        return EmbeddingResult((1.0, 2.0), "offline", TokenUsage(3, 0))


class EmbeddingMeter:
    async def bound(self, text):
        return SharedBudgetAmount(TokenUsage(5, 0), ModelCost("USD", "host-v1", "0.05"))

    async def actual(self, text, result):
        return SharedBudgetAmount(result.usage, ModelCost("USD", "host-v1", "0.01"))


def local_measurement(documents):
    # Explicit host knowledge: these in-process templates are not billed and do
    # not consume model tokens. Absence of a report would NOT imply free service.
    return ServiceUsageMeasurement(
        cost=ModelCost("USD", "host-v1", 0), cost_complete=True,
        units=(ServiceUsageUnit("documents", len(documents)),), units_complete=True,
    )


@pytest.mark.asyncio
async def test_four_service_kinds_share_observation_without_bypassing_model_budget(tmp_path):
    budget_path, usage_path = tmp_path / "budget.sqlite", tmp_path / "usage.sqlite"
    limits = SharedBudgetLimits(max_total_tokens=20, max_cost="1", currency="USD", price_table_version="host-v1")
    budget = SQLiteSharedBudget(budget_path, "pool", limits)
    await budget.initialize()
    usage = SQLiteServiceUsageLedger(usage_path)
    await usage.initialize(confirm_create=True)
    labels = dict(operation_id="local-support", meter_version="host-v1")
    model_controller = ObservedSharedBudgetController(
        budget, usage, service="model", source_ref="offline-model", **labels
    )
    embedding_controller = ObservedSharedBudgetController(
        budget, usage, service="embedding", source_ref="offline-embedding", **labels
    )
    inner = OfflineModel()
    provider = SharedBudgetModelProvider(inner, model_controller, ModelMeter())
    request = ModelRequest(
        (ModelMessage.text(MessageRole.USER, "PRIVATE_PROMPT"),),
        model="offline", max_output_tokens=5,
    )
    assert (await collect_stream(provider.stream(request))).usage == TokenUsage(4, 2)
    embedder = SharedBudgetTextEmbedder(OfflineEmbedding(), embedding_controller, EmbeddingMeter())
    assert await embedder.embed("PRIVATE_EMBEDDING_INPUT") == (1.0, 2.0)

    documents = InMemoryKnowledgeDocumentStore((KnowledgeDocument("policy", "PRIVATE_POLICY refund"),))
    retrieval = ObservedKnowledgeRetriever(
        KeywordKnowledgeRetriever(documents), usage, source_ref="local-keywords",
        measurement=local_measurement, token_scope="not-applicable", **labels
    )
    reranker = ObservedKnowledgeReranker(
        BM25KnowledgeReranker(), usage, source_ref="local-bm25",
        measurement=local_measurement, token_scope="not-applicable", **labels
    )
    result = await RerankedKnowledgeRetriever(retrieval, reranker).retrieve("refund", limit=1)
    assert result[0].document_id == "policy"

    reopened = SQLiteServiceUsageLedger(usage_path)
    records = await reopened.records("local-support")
    assert {record.service for record in records} == {"model", "embedding", "retrieval", "rerank"}
    report = aggregate_service_usage(records)
    assert report["known_usage"] == {
        "input_tokens": 7, "output_tokens": 2, "cached_input_tokens": 0, "total_tokens": 9,
    }
    assert report["usage_complete"] and report["cost_complete"] and report["units_complete"]
    assert report["cost_totals"] == [{"currency": "USD", "price_table_version": "host-v1", "total": "0.03"}]
    assert "PRIVATE_" not in json.dumps([record.to_dict() for record in records])
    # The same real SQLite budget still owns admission. Observation never grants
    # a second balance or erases actual usage to let another model call through.
    with pytest.raises(SharedBudgetError):
        await collect_stream(provider.stream(request))
    assert inner.calls == 1
    state = await SQLiteSharedBudget(budget_path, "pool", limits).snapshot()
    assert state.known_usage.total_tokens == 9 and state.held_usage.total_tokens == 0
    assert len(await reopened.records("local-support")) == 4
