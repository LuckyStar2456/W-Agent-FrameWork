"""Draft snapshot-vector regressions; no execution without user authorization."""

import asyncio
import json
from uuid import UUID

import pytest

from w_agent import (
    HttpToolResponse, KnowledgeDocument, KnowledgeRetrievalError, KnowledgeSnapshot,
    KnowledgeVectorIndex, QdrantVectorSearch, QdrantVectorWriter,
    SnapshotVectorKnowledgeRetriever, SQLiteKnowledgeSnapshotStore,
    VectorRetrievalError, VectorSearchMatch, knowledge_document_embedding_text,
    prepare_knowledge_vectors,
)


def snapshot(version="v1", text="PRIVATE_BODY"):
    return KnowledgeSnapshot("PRIVATE_NAMESPACE", version, (
        KnowledgeDocument("PRIVATE_ID", text, "PRIVATE_SOURCE", "Document title"),
        KnowledgeDocument(7, "second document", "manual:second", "Second"),
    ))


class Embedder:
    def __init__(self, vector=(0.1, 0.2)):
        self.vector = vector
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        return self.vector


class Backend:
    def __init__(self, matches=()):
        self.matches = matches
        self.calls = []

    async def search(self, vector, *, limit, point_ids=None):
        self.calls.append((vector, limit, point_ids))
        return self.matches


def test_vector_ids_bind_exact_snapshot_embedding_key_and_dimensions():
    index = KnowledgeVectorIndex(snapshot(), "PRIVATE_MODEL-v1", 2)
    assert index.point_ids == KnowledgeVectorIndex(snapshot(), "PRIVATE_MODEL-v1", 2).point_ids
    assert index.snapshot_digest == snapshot().digest
    assert all(str(UUID(identity)) == identity for identity in index.point_ids)
    assert "PRIVATE" not in repr(index)
    for changed in (
        KnowledgeVectorIndex(snapshot("v2"), "PRIVATE_MODEL-v1", 2),
        KnowledgeVectorIndex(snapshot(text="changed"), "PRIVATE_MODEL-v1", 2),
        KnowledgeVectorIndex(snapshot(), "another-model", 2),
        KnowledgeVectorIndex(snapshot(), "PRIVATE_MODEL-v1", 3),
        KnowledgeVectorIndex(KnowledgeSnapshot("PRIVATE_NAMESPACE", "v1", tuple(reversed(snapshot().documents))), "PRIVATE_MODEL-v1", 2),
    ):
        assert set(index.point_ids).isdisjoint(changed.point_ids)
    assert index.point_id("PRIVATE_ID") == index.point_ids[0]
    with pytest.raises(ValueError):
        index.point_id("missing")


def test_numeric_and_string_original_ids_remain_distinct():
    value = KnowledgeSnapshot("n", "v", (KnowledgeDocument(1, "same"), KnowledgeDocument("1", "same")))
    index = KnowledgeVectorIndex(value, "model", 2)
    assert index.point_id(1) != index.point_id("1")
    with pytest.raises(ValueError):
        index.point_id(True)


def test_embedding_text_discloses_title_body_without_identity_or_source_fields():
    rendered = knowledge_document_embedding_text(snapshot().documents[0])
    assert json.loads(rendered) == {
        "format": "wagent-knowledge-embedding-v1", "title": "Document title", "text": "PRIVATE_BODY",
    }
    assert "PRIVATE_SOURCE" not in rendered and "PRIVATE_ID" not in rendered
    assert "PRIVATE_NAMESPACE" not in rendered


@pytest.mark.asyncio
async def test_separate_embedding_consent_and_explicit_ordered_subset():
    index, embedder = KnowledgeVectorIndex(snapshot(), "model", 2), Embedder()
    for consent in (False, 1):
        with pytest.raises(VectorRetrievalError):
            await prepare_knowledge_vectors(index, embedder, confirm_embedding=consent)
    assert not embedder.calls
    points = await prepare_knowledge_vectors(index, embedder, document_ids=(7, "PRIVATE_ID"), confirm_embedding=True)
    assert tuple(point.point_id for point in points) == tuple(reversed(index.point_ids))
    assert all(point.vector == (0.1, 0.2) for point in points)
    assert embedder.calls == [knowledge_document_embedding_text(item) for item in reversed(snapshot().documents)]


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"document_ids": (7, "missing")}, {"document_ids": (7, 7)},
    {"document_ids": [7]}, {"document_ids": (True,)},
    {"max_input_bytes": 1}, {"max_vector_values": 3}, {"timeout": True},
])
async def test_whole_batch_is_validated_before_any_embedding(options):
    embedder = Embedder()
    with pytest.raises(VectorRetrievalError):
        await prepare_knowledge_vectors(KnowledgeVectorIndex(snapshot(), "model", 2), embedder,
                                        confirm_embedding=True, **options)
    assert not embedder.calls


@pytest.mark.asyncio
async def test_snapshots_over_one_batch_require_explicit_selection_and_empty_skips_callbacks():
    value = KnowledgeSnapshot("n", "v", tuple(KnowledgeDocument(index, "body") for index in range(129)))
    index, embedder = KnowledgeVectorIndex(value, "model", 2), Embedder()
    with pytest.raises(VectorRetrievalError):
        await prepare_knowledge_vectors(index, embedder, confirm_embedding=True)
    assert not embedder.calls
    points = await prepare_knowledge_vectors(index, embedder, document_ids=(128,), confirm_embedding=True)
    assert points[0].point_id == index.point_id(128)
    embedder.calls.clear()
    assert await prepare_knowledge_vectors(index, embedder, document_ids=(), confirm_embedding=True) == ()
    empty = KnowledgeVectorIndex(KnowledgeSnapshot("n", "empty", ()), "model", 2)
    assert await prepare_knowledge_vectors(empty, embedder, confirm_embedding=True) == ()
    backend = Backend()
    assert await SnapshotVectorKnowledgeRetriever(empty, embedder, backend).retrieve("q", limit=1) == ()
    assert not embedder.calls and not backend.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [(1,), (True, 1), (float("nan"), 0), [1, 2]])
async def test_preparation_and_query_reject_wrong_embeddings_before_search(vector):
    index = KnowledgeVectorIndex(snapshot(), "model", 2)
    embedder, backend = Embedder(vector), Backend()
    with pytest.raises(VectorRetrievalError):
        await prepare_knowledge_vectors(index, embedder, confirm_embedding=True)
    assert len(embedder.calls) == 1
    with pytest.raises(KnowledgeRetrievalError):
        await SnapshotVectorKnowledgeRetriever(index, embedder, backend).retrieve("q", limit=1)
    assert not backend.calls


@pytest.mark.asyncio
async def test_snapshot_retriever_filters_points_restores_original_ids_sources_and_rank():
    index = KnowledgeVectorIndex(snapshot(), "model", 2)
    backend = Backend(tuple(VectorSearchMatch(identity, 1) for identity in reversed(index.point_ids)))
    embedder = Embedder()
    retriever = SnapshotVectorKnowledgeRetriever(index, embedder, backend)
    assert not backend.calls and not embedder.calls
    assert await retriever.retrieve("explicit query", limit=2) == tuple(reversed(snapshot().documents))
    assert embedder.calls == ["explicit query"]
    assert backend.calls == [((0.1, 0.2), 2, index.point_ids)]


@pytest.mark.asyncio
async def test_foreign_snapshot_or_model_matches_fail_even_with_custom_backend():
    index = KnowledgeVectorIndex(snapshot(), "model", 2)
    other = KnowledgeVectorIndex(snapshot(), "other-model", 2)
    retriever = SnapshotVectorKnowledgeRetriever(index, Embedder(), Backend((VectorSearchMatch(other.point_ids[0], 1),)))
    with pytest.raises(KnowledgeRetrievalError):
        await retriever.retrieve("q", limit=1)


@pytest.mark.asyncio
async def test_original_ids_are_included_in_final_document_byte_limit():
    index = KnowledgeVectorIndex(KnowledgeSnapshot("n", "v", (KnowledgeDocument("x" * 512, "body"),)), "model", 2)
    backend = Backend((VectorSearchMatch(index.point_ids[0], 1),))
    retriever = SnapshotVectorKnowledgeRetriever(index, Embedder(), backend, max_document_bytes=100)
    with pytest.raises(KnowledgeRetrievalError):
        await retriever.retrieve("q", limit=1)


class VectorTransport:
    def __init__(self):
        self.points = {}
        self.requests = []

    async def send(self, request, **kwargs):
        self.requests.append(request)
        if request.method == "PUT":
            for point in request.json_body["points"]:
                self.points[point["id"]] = point
            result = {"status": "completed", "operation_id": 1}
        else:
            ids = request.json_body["filter"]["must"][0]["has_id"]
            result = {"points": [{"id": identity, "score": 1} for identity in ids if identity in self.points][:request.json_body["limit"]]}
        return HttpToolResponse(200, {}, json.dumps({"status": "ok", "result": result}).encode())


@pytest.mark.asyncio
async def test_fake_prepare_write_reopen_and_retrieve_keeps_snapshot_identity(tmp_path):
    versions = SQLiteKnowledgeSnapshotStore(tmp_path / "snapshots.sqlite")
    await versions.initialize(confirm_create=True)
    await versions.save(snapshot(), confirm_write=True)
    index = KnowledgeVectorIndex(snapshot(), "embedding-v1", 2)
    embedder, transport = Embedder(), VectorTransport()
    points = await prepare_knowledge_vectors(index, embedder, confirm_embedding=True)
    assert not transport.requests  # Embedding consent never triggers writes.
    backend = QdrantVectorSearch("http://localhost:6333", "knowledge", transport=transport)
    writer = QdrantVectorWriter(backend)
    plan = writer.plan(points)
    assert not transport.requests
    receipt = await writer.upsert(plan, confirm_digest=plan.digest)
    assert receipt.applied and receipt.point_count == 2
    assert all(point["payload"] == {} for point in transport.points.values())
    reopened = SQLiteKnowledgeSnapshotStore(versions.database_path)
    restored_index = KnowledgeVectorIndex(await reopened.load("PRIVATE_NAMESPACE", "v1"), "embedding-v1", 2)
    assert restored_index.point_ids == index.point_ids
    result = await SnapshotVectorKnowledgeRetriever(restored_index, embedder, backend).retrieve("q", limit=2)
    assert result == snapshot().documents
    assert all(document.document_id not in index.point_ids for document in result)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_preparation_cancellation_and_timeout_stop_remaining_documents(cancel):
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow:
        calls = 0

        async def embed(self, text):
            self.calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    embedder = Slow()
    task = asyncio.create_task(prepare_knowledge_vectors(
        KnowledgeVectorIndex(snapshot(), "model", 2), embedder,
        confirm_embedding=True, timeout=30 if cancel else 0.01,
    ))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else VectorRetrievalError):
        await task
    assert closed.is_set() and embedder.calls == 1
