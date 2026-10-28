"""Draft embedding/shared-budget composition regressions; unexecuted."""

import asyncio
import json

import pytest

from w_agent import (
    EmbeddingError, EmbeddingResult, HttpToolResponse, InMemorySharedBudget, KnowledgeDocument,
    KnowledgeSnapshot, KnowledgeVectorIndex, SharedBudgetAmount, SharedBudgetError,
    SharedBudgetLimits, SharedBudgetTextEmbedder, SQLiteSharedBudget, TokenUsage,
    ollama_text_embedder, prepare_knowledge_vectors,
)


class Meter:
    async def bound(self, text):
        return SharedBudgetAmount(TokenUsage(10, 0))

    async def actual(self, text, result):
        return SharedBudgetAmount(result.usage)


class Provider:
    def __init__(self, usage=TokenUsage(4, 0), error=None):
        self.usage, self.error, self.calls = usage, error, 0

    async def embed_result(self, text):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return EmbeddingResult((1, 2), "test-model", self.usage)


@pytest.mark.asyncio
async def test_settlement_visible_in_shared_ledger_before_vector_return():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    provider = Provider()
    embedder = SharedBudgetTextEmbedder(provider, ledger, Meter())
    assert await embedder.embed("text") == (1, 2)
    state = await ledger.snapshot()
    assert state.known_usage == TokenUsage(4, 0) and state.held_usage.total_tokens == 0
    assert state.entries[0].status == "settled"
    assert (await embedder.embed_result("next")).usage == TokenUsage(4, 0)
    assert (await ledger.snapshot()).known_usage.input_tokens == 8


@pytest.mark.asyncio
async def test_reservation_refusal_never_calls_provider():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=9))
    provider = Provider()
    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(provider, ledger, Meter()).embed("text")
    assert provider.calls == 0 and not (await ledger.snapshot()).entries


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [Provider(usage=None), Provider(error=RuntimeError("PRIVATE")),
                                      Provider(error=EmbeddingError("failed", may_have_called=True))])
async def test_unknown_usage_or_transport_outcome_holds_budget(provider):
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(provider, ledger, Meter()).embed("text")
    state = await ledger.snapshot()
    assert state.blocked and state.entries[0].status == "unknown"
    assert state.held_usage.input_tokens == 10 and state.known_usage.input_tokens == 0


@pytest.mark.asyncio
async def test_explicit_pretransport_failure_releases_reservation():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    provider = Provider(error=EmbeddingError("request-invalid", may_have_called=False))
    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(provider, ledger, Meter()).embed("text")
    state = await ledger.snapshot()
    assert state.entries[0].status == "released" and state.held_usage.total_tokens == 0
    assert not state.blocked


@pytest.mark.asyncio
async def test_underestimated_usage_is_recorded_but_not_returned_as_success():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    with pytest.raises(SharedBudgetError) as error:
        await SharedBudgetTextEmbedder(Provider(usage=TokenUsage(11, 0)), ledger, Meter()).embed("text")
    assert error.value.failure.code == "embedding-bound-exceeded"
    state = await ledger.snapshot()
    assert state.known_usage.input_tokens == 11 and state.entries[0].status == "settled"


@pytest.mark.asyncio
async def test_meter_cannot_replace_service_reported_usage():
    class WrongMeter(Meter):
        async def actual(self, text, result):
            return SharedBudgetAmount(TokenUsage(1, 0))

    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(Provider(), ledger, WrongMeter()).embed("text")
    assert (await ledger.snapshot()).entries[0].status == "unknown"


@pytest.mark.asyncio
async def test_cancellation_preserves_unknown_reservation():
    started = asyncio.Event()

    class Slow:
        async def embed_result(self, text):
            started.set()
            await asyncio.Event().wait()

    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    task = asyncio.create_task(SharedBudgetTextEmbedder(Slow(), ledger, Meter()).embed("text"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await ledger.snapshot()).entries[0].status == "unknown"


@pytest.mark.asyncio
async def test_cleanup_failure_leaves_conservative_pending_ticket():
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))

    class FailingCleanup:
        async def reserve(self, amount):
            return await ledger.reserve(amount)

        async def settle(self, reservation, actual):
            raise RuntimeError("PRIVATE_STORAGE_FAILURE")

        async def release(self, reservation):
            raise RuntimeError("PRIVATE_STORAGE_FAILURE")

    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(Provider(), FailingCleanup(), Meter()).embed("text")
    state = await ledger.snapshot()
    assert state.entries[0].status == "pending" and state.held_usage.input_tokens == 10


@pytest.mark.asyncio
async def test_embedding_settlement_survives_sqlite_reopen(tmp_path):
    limits = SharedBudgetLimits(max_total_tokens=20)
    path = tmp_path / "shared.sqlite"
    ledger = SQLiteSharedBudget(path, "shared", limits)
    await ledger.initialize()
    await SharedBudgetTextEmbedder(Provider(), ledger, Meter()).embed("text")
    reopened = SQLiteSharedBudget(path, "shared", limits)
    state = await reopened.snapshot()
    assert state.known_usage.input_tokens == 4 and state.entries[0].status == "settled"
    # Other explicitly wrapped model calls can reserve from this same pool.
    ticket = await reopened.reserve(SharedBudgetAmount(TokenUsage(16, 0)))
    with pytest.raises(SharedBudgetError):
        await SharedBudgetTextEmbedder(Provider(), ledger, Meter()).embed("next")
    await reopened.release(ticket)


@pytest.mark.asyncio
async def test_knowledge_preparation_records_each_http_embedding_in_pool():
    class Transport:
        calls = 0

        async def send(self, request, **kwargs):
            self.calls += 1
            return HttpToolResponse(200, {}, json.dumps({
                "model": "local-model", "embeddings": [[1, 2]], "prompt_eval_count": 4,
            }).encode())

    transport = Transport()
    raw = ollama_text_embedder("http://localhost:11434", "local-model", 2, transport=transport)
    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20))
    metered = SharedBudgetTextEmbedder(raw, ledger, Meter())
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (
        KnowledgeDocument("a", "first"), KnowledgeDocument("b", "second"),
    )), "host-model-label", 2)
    points = await prepare_knowledge_vectors(index, metered, confirm_embedding=True)
    assert tuple(point.point_id for point in points) == index.point_ids
    assert transport.calls == 2
    state = await ledger.snapshot()
    assert state.known_usage.input_tokens == 8 and state.held_usage.total_tokens == 0
    assert all(entry.status == "settled" for entry in state.entries)


@pytest.mark.asyncio
async def test_concurrent_calls_cannot_bypass_held_reservation():
    started, release = asyncio.Event(), asyncio.Event()

    class Slow:
        async def embed_result(self, text):
            started.set()
            await release.wait()
            return EmbeddingResult((1, 2), "m", TokenUsage(4, 0))

    ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=10))
    metered = SharedBudgetTextEmbedder(Slow(), ledger, Meter())
    first = asyncio.create_task(metered.embed("first"))
    try:
        await started.wait()
        with pytest.raises(SharedBudgetError):
            await metered.embed("second")
    finally:
        release.set()
        await first
    assert len((await ledger.snapshot()).entries) == 1
