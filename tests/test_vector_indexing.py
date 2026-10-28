"""Draft vector-index preparation/write regressions; not executed this increment."""

import asyncio
import json

import pytest

from w_agent import (
    DenseVectorPoint, HttpToolResponse, MessageRole, ModelMessage,
    QdrantSessionHistoryRetriever, QdrantVectorSearch, QdrantVectorWriter,
    SessionHistoryLimits, SessionHistoryTurn, VectorIndexWriteError,
    VectorRetrievalError, prepare_qdrant_history_points,
    qdrant_history_embedding_text, qdrant_history_point_id,
)


def history():
    return tuple(SessionHistoryTurn(f"PRIVATE_RUN_{index}", (ModelMessage(
        MessageRole.USER, ModelMessage.text(MessageRole.USER, f"PRIVATE_TEXT_{index}").content,
        name="PRIVATE_NAME", metadata={"secret": "PRIVATE_METADATA"},
    ),)) for index in range(2))


class Embedder:
    def __init__(self, vectors=((0.1, 0.2), (0.3, 0.4))):
        self.vectors = vectors
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        return self.vectors[len(self.calls) - 1]


class Transport:
    def __init__(self, *, status="completed", http=200, raw=None):
        self.requests = []
        self.http = http
        self.raw = raw if raw is not None else json.dumps({
            "status": "ok", "result": {"status": status, "operation_id": 7},
        }).encode()

    async def send(self, request):
        self.requests.append(request)
        return HttpToolResponse(self.http, {}, self.raw)


def writer(transport, **kwargs):
    return QdrantVectorWriter(QdrantVectorSearch(
        "http://localhost:6333", "history", api_key="PRIVATE_KEY", transport=transport, **kwargs,
    ))


@pytest.mark.asyncio
async def test_embedding_authorization_separate_from_write_and_no_metadata_disclosure():
    embedder = Embedder()
    with pytest.raises(VectorRetrievalError):
        await prepare_qdrant_history_points("project-v1", history(), embedder)
    assert not embedder.calls
    points = await prepare_qdrant_history_points("project-v1", history(), embedder, confirm_embedding=True)
    assert len(points) == 2
    assert points[0].point_id == qdrant_history_point_id("project-v1", history()[0])
    assert embedder.calls == [qdrant_history_embedding_text(turn) for turn in history()]
    assert "PRIVATE_TEXT" in embedder.calls[0]
    assert all("PRIVATE_RUN" not in text and "PRIVATE_NAME" not in text and "PRIVATE_METADATA" not in text
               for text in embedder.calls)
    assert "PRIVATE_TEXT" not in repr(points) and "vector=" not in repr(points)


@pytest.mark.asyncio
@pytest.mark.parametrize("candidates,limits", [
    ((history()[0], history()[0]), SessionHistoryLimits()),
    (history(), SessionHistoryLimits(max_input_bytes=5)),
    (history(), SessionHistoryLimits(max_messages=1)),
    (history() * 65, SessionHistoryLimits()),
])
async def test_preparation_validates_entire_batch_before_embedding(candidates, limits):
    embedder = Embedder()
    with pytest.raises(VectorRetrievalError):
        await prepare_qdrant_history_points("project-v1", candidates, embedder,
                                           confirm_embedding=True, limits=limits)
    assert not embedder.calls


@pytest.mark.asyncio
async def test_inconsistent_dimensions_fail_after_embedding_without_implicit_write():
    embedder = Embedder(((1.0,), (1.0, 2.0)))
    with pytest.raises(VectorRetrievalError, match="prior embedding calls may be billed"):
        await prepare_qdrant_history_points("project-v1", history(), embedder, confirm_embedding=True)
    assert len(embedder.calls) == 2


@pytest.mark.asyncio
async def test_empty_history_has_no_embedding_and_cannot_be_an_upsert_plan():
    embedder = Embedder()
    assert await prepare_qdrant_history_points("project-v1", (), embedder, confirm_embedding=True) == ()
    assert not embedder.calls
    with pytest.raises(VectorIndexWriteError) as error:
        writer(Transport()).plan(())
    assert not error.value.may_have_written


@pytest.mark.asyncio
@pytest.mark.parametrize("vector_name", [None, "dense"])
async def test_plan_is_pure_and_write_requires_exact_digest(vector_name):
    transport = Transport()
    service = writer(transport, vector_name=vector_name)
    points = (DenseVectorPoint(1, (0.1, 0.2)),)
    plan = service.plan(points)
    assert not transport.requests
    assert "PRIVATE_KEY" not in repr(plan) and "points=" not in repr(plan)
    assert plan.digest == service.plan(points).digest
    with pytest.raises(VectorIndexWriteError) as error:
        await service.upsert(plan, confirm_digest="not-confirmed")
    assert not error.value.may_have_written and not transport.requests
    result = await service.upsert(plan, confirm_digest=plan.digest)
    assert result.applied and result.point_count == 1 and result.operation_id == 7
    request = transport.requests[0]
    assert request.method == "PUT" and request.url.endswith("/collections/history/points")
    assert request.query == {"wait": "true"} and request.headers["api-key"] == "PRIVATE_KEY"
    vector = {"dense": [0.1, 0.2]} if vector_name else [0.1, 0.2]
    assert request.json_body == {"points": [{"id": 1, "vector": vector, "payload": {}}]}


@pytest.mark.asyncio
async def test_changed_contents_target_or_vector_name_require_new_review():
    transport = Transport()
    service = writer(transport)
    original = service.plan((DenseVectorPoint(1, (1, 2)),))
    changed = service.plan((DenseVectorPoint(1, (2, 3)),))
    assert original.digest != changed.digest
    other = QdrantVectorWriter(QdrantVectorSearch("http://other:6333", "history", transport=transport))
    other_plan = other.plan(original.points)
    assert original.digest != other_plan.digest
    named_plan = writer(transport, vector_name="dense").plan(original.points)
    assert original.digest != named_plan.digest
    for plan, digest in ((changed, original.digest), (other_plan, other_plan.digest),
                         (named_plan, named_plan.digest)):
        with pytest.raises(VectorIndexWriteError) as error:
            await service.upsert(plan, confirm_digest=digest)
        assert not error.value.may_have_written
    assert not transport.requests


@pytest.mark.parametrize("points", [
    (DenseVectorPoint(1, (1,)), DenseVectorPoint(1, (2,))),
    (DenseVectorPoint(1, (1,)), DenseVectorPoint(2, (1, 2))),
    (DenseVectorPoint("non-qdrant-id", (1,)),),
    tuple(DenseVectorPoint(i, (1,)) for i in range(129)),
])
def test_plan_rejects_invalid_points_before_transport(points):
    transport = Transport()
    with pytest.raises(VectorIndexWriteError) as error:
        writer(transport).plan(points)
    assert not error.value.may_have_written and not transport.requests


def test_request_size_refusal_is_local():
    with pytest.raises(VectorIndexWriteError) as error:
        writer(Transport(), max_request_bytes=10).plan((DenseVectorPoint(1, (1,)),))
    assert not error.value.may_have_written


@pytest.mark.asyncio
async def test_acknowledged_is_not_applied_and_no_followup_poll_occurs():
    transport = Transport(status="acknowledged")
    service = writer(transport)
    plan = service.plan((DenseVectorPoint(1, (1,)),))
    result = await service.upsert(plan, confirm_digest=plan.digest)
    assert not result.applied and result.status == "acknowledged" and len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,http", [
    (b"PRIVATE_ERROR", 503), (b"PRIVATE_REDIRECT", 307), (b"PRIVATE_ERROR", 200),
    (b'{"status":"ok","result":{"status":"failed"}}', 200),
    (b'{"status":"ok","result":{"status":"completed","operation_id":true}}', 200),
    (b'{"status":"ok","status":"ok","result":{"status":"completed"}}', 200),
])
async def test_post_send_failures_are_unknown_and_never_retried(raw, http):
    transport = Transport(raw=raw, http=http)
    service = writer(transport)
    plan = service.plan((DenseVectorPoint(1, (1,)),))
    with pytest.raises(VectorIndexWriteError) as error:
        await service.upsert(plan, confirm_digest=plan.digest)
    assert error.value.may_have_written and "PRIVATE" not in str(error.value)
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_oversized_write_response_keeps_outcome_unknown():
    transport = Transport(raw=b"x" * 101)
    service = writer(transport, max_response_bytes=100)
    plan = service.plan((DenseVectorPoint(1, (1,)),))
    with pytest.raises(VectorIndexWriteError) as error:
        await service.upsert(plan, confirm_digest=plan.digest)
    assert error.value.may_have_written and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_credential_rotation_does_not_implicitly_grant_write_permission():
    transport = Transport()
    original = writer(transport)
    rotated = QdrantVectorWriter(QdrantVectorSearch(
        "http://localhost:6333", "history", api_key="ROTATED_KEY", transport=transport,
    ))
    plan = original.plan((DenseVectorPoint(1, (1,)),))
    assert plan.digest == rotated.plan(plan.points).digest
    with pytest.raises(VectorIndexWriteError) as error:
        await rotated.upsert(plan, confirm_digest="")
    assert not error.value.may_have_written and not transport.requests


@pytest.mark.asyncio
async def test_index_prepare_write_and_retrieve_use_same_ids():
    embedder = Embedder(((0.1, 0.2), (0.3, 0.4), (0.4, 0.5)))
    points = await prepare_qdrant_history_points("project-v1", history(), embedder, confirm_embedding=True)
    class RoundTripTransport(Transport):
        async def send(self, request):
            if request.method == "PUT":
                return await super().send(request)
            self.requests.append(request)
            return HttpToolResponse(200, {}, json.dumps({"status": "ok", "result": {
                "points": [{"id": points[1].point_id, "score": 1}],
            }}).encode())
    transport = RoundTripTransport()
    service = writer(transport)
    plan = service.plan(points)
    assert (await service.upsert(plan, confirm_digest=plan.digest)).applied
    selector = QdrantSessionHistoryRetriever("project-v1", embedder, service.backend)
    assert await selector.select("query", history(), limit=1) == (1,)
    assert transport.requests[1].json_body["filter"] == {"must": [{"has_id": [point.point_id for point in points]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_write_cancellation_and_timeout_do_not_retry(timeout):
    entered, finished = asyncio.Event(), asyncio.Event()
    class SlowTransport:
        calls = 0

        async def send(self, request):
            self.calls += 1
            entered.set()
            try:
                await asyncio.Future()
            finally:
                finished.set()
    transport = SlowTransport()
    service = writer(transport, timeout=0.01 if timeout else 30)
    plan = service.plan((DenseVectorPoint(1, (1,)),))
    task = asyncio.create_task(service.upsert(plan, confirm_digest=plan.digest))
    await entered.wait()
    if not timeout:
        task.cancel()
    with pytest.raises(VectorIndexWriteError if timeout else asyncio.CancelledError) as error:
        await task
    if timeout:
        assert error.value.may_have_written
    assert finished.is_set() and transport.calls == 1


@pytest.mark.asyncio
async def test_preparation_cancellation_stops_remaining_embeddings():
    entered, finished = asyncio.Event(), asyncio.Event()
    class SlowEmbedder:
        calls = 0

        async def embed(self, text):
            self.calls += 1
            entered.set()
            try:
                await asyncio.Future()
            finally:
                finished.set()
    embedder = SlowEmbedder()
    task = asyncio.create_task(prepare_qdrant_history_points("project-v1", history(), embedder, confirm_embedding=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set() and embedder.calls == 1
