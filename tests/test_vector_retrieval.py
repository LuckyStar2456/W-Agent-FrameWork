"""Draft vector retrieval regressions; execution requires user authorization."""

import asyncio
import json
from uuid import UUID

import pytest

from w_agent import (
    AsyncRetrievedSessionHistoryPolicy, HttpToolResponse, MessageRole, ModelMessage,
    QdrantSessionHistoryRetriever, QdrantVectorSearch, SessionHistoryLimits,
    SessionHistoryTurn, SessionMessage, SessionRecord, VectorRetrievalError,
    VectorSearchMatch, qdrant_history_point_id,
)


class Transport:
    def __init__(self, points=(), *, raw=None, status=200):
        self.requests = []
        self.raw = raw if raw is not None else json.dumps({"status": "ok", "result": {"points": list(points)}}).encode()
        self.status = status

    async def send(self, request, **kwargs):
        self.requests.append(request)
        return HttpToolResponse(self.status, {}, self.raw)


class Embedder:
    def __init__(self, result=(0.1, 0.2)):
        self.queries = []
        self.result = result

    async def embed(self, text):
        self.queries.append(text)
        return self.result


def turns():
    return tuple(SessionHistoryTurn(f"run-{index}", (
        ModelMessage.text(MessageRole.USER, f"PRIVATE_HISTORY_{index}"),
    )) for index in range(3))


@pytest.mark.asyncio
async def test_query_shape_candidate_filter_and_no_payload_disclosure():
    transport = Transport([{"id": 42, "score": 0.9, "payload": {"text": "REMOTE_INSTRUCTION"}}])
    search = QdrantVectorSearch("https://qdrant.example/api/", "notes", api_key="SECRET_KEY",
                                vector_name="dense", score_threshold=0.5, transport=transport)
    assert await search.search((0.1, 0.2), limit=2, point_ids=(42, 43)) == (VectorSearchMatch(42, 0.9),)
    request = transport.requests[0]
    assert request.url == "https://qdrant.example/api/collections/notes/points/query"
    assert request.method == "POST" and request.headers["api-key"] == "SECRET_KEY"
    assert request.json_body == {"query": [0.1, 0.2], "limit": 2, "with_payload": False,
                                 "with_vector": False, "using": "dense", "score_threshold": 0.5,
                                 "filter": {"must": [{"has_id": [42, 43]}]}}
    assert "SECRET_KEY" not in repr(search) and "qdrant.example" not in repr(search)


@pytest.mark.asyncio
async def test_uuid_normalization_and_unfiltered_explicit_vector_lookup():
    identity = "00000000-0000-0000-0000-000000000001"
    transport = Transport([{"id": identity.replace("-", ""), "score": 1}])
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport)
    assert (await search.search((1,), limit=1))[0].point_id == identity
    assert "filter" not in transport.requests[0].json_body
    transport.requests.clear()
    assert await search.search((1,), limit=1, point_ids=()) == ()
    assert not transport.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("vector,limit,ids", [
    ((), 1, None), ([1], 1, None), ((True,), 1, None), ((float("nan"),), 1, None),
    ((float("inf"),), 1, None), ((1,), True, None), ((1,), 129, None),
    ((1,), 1, (True,)), ((1,), 1, (1, 1)), ((1,), 1, ("not-uuid",)),
    ((1,), 1, tuple(range(1025))),
])
async def test_invalid_requests_fail_before_transport(vector, limit, ids):
    transport = Transport()
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport)
    with pytest.raises(VectorRetrievalError, match="^vector search failed$"):
        await search.search(vector, limit=limit, point_ids=ids)
    assert not transport.requests


@pytest.mark.parametrize("options", [
    {"base_url": "https://user:SECRET@example.test"}, {"base_url": "http://host/?secret=1"},
    {"base_url": "file:///tmp/index"}, {"base_url": "http://host/\nsecret"},
    {"collection": "../other"}, {"api_key": "SECRET\r\nInjected: yes"},
    {"timeout": True}, {"timeout": float("nan")}, {"max_response_bytes": 0},
    {"score_threshold": float("inf")}, {"vector_name": ""}, {"transport": object()},
])
def test_bad_configuration_is_rejected_without_secret_echo(options):
    configuration = {"base_url": "http://localhost:6333", "collection": "history", **options}
    with pytest.raises(ValueError) as error:
        QdrantVectorSearch(**configuration)
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,status", [
    (b"PRIVATE_BODY", 401), (b"PRIVATE_BODY", 302), (b"not JSON PRIVATE_BODY", 200),
    (b'{"status":"ok","status":"error","result":{"points":[]}}', 200),
    (b'{"status":"ok","result":{"points":[{"id":1,"score":NaN}]}}', 200),
    (b'{"status":"ok","result":{"points":[{"id":1,"score":true}]}}', 200),
    (b'{"status":"ok","result":{"points":[{"id":2,"score":1}]}}', 200),
    (b'{"status":"ok","result":{"points":[{"id":1,"score":1},{"id":1,"score":2}]}}', 200),
    (b'{"status":"ok","result":[]}', 200), (b'{"status":"failed","result":{"points":[]}}', 200),
])
async def test_bad_response_no_retry_no_private_error(raw, status):
    transport = Transport(raw=raw, status=status)
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport)
    with pytest.raises(VectorRetrievalError) as error:
        await search.search((1,), limit=2, point_ids=(1,))
    assert str(error.value) == "vector search failed" and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_request_and_response_byte_limits_apply_to_injected_transport():
    transport = Transport(raw=b"x" * 101)
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport, max_response_bytes=100)
    with pytest.raises(VectorRetrievalError):
        await search.search((1,), limit=1)
    assert len(transport.requests) == 1 and transport.requests[0].max_response_bytes == 100
    transport.requests.clear()
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport, max_request_bytes=10)
    with pytest.raises(VectorRetrievalError):
        await search.search((1,), limit=1)
    assert not transport.requests


def test_point_identity_binds_namespace_run_and_text_not_fields():
    turn = turns()[0]
    first = qdrant_history_point_id("project-v1", turn)
    assert str(UUID(first)) == first
    assert first == qdrant_history_point_id("project-v1", turn)
    assert first != qdrant_history_point_id("project-v2", turn)
    assert first != qdrant_history_point_id("project-v1", SessionHistoryTurn("other-run", turn.messages))
    changed = SessionHistoryTurn(turn.run_id, (ModelMessage.text(MessageRole.USER, "new text"),))
    assert first != qdrant_history_point_id("project-v1", changed)
    with_fields = SessionHistoryTurn(turn.run_id, (ModelMessage(
        MessageRole.USER, turn.messages[0].content, name="PRIVATE_NAME", metadata={"private": "PRIVATE_METADATA"},
    ),))
    assert first == qdrant_history_point_id("project-v1", with_fields)


@pytest.mark.asyncio
async def test_history_selects_local_segments_and_restores_chronology():
    candidates = turns()
    ids = tuple(qdrant_history_point_id("project-v1", turn) for turn in candidates)
    transport = Transport([{"id": ids[1], "score": 1, "payload": {"text": "REMOTE_INSTRUCTION"}},
                           {"id": ids[0], "score": 0.8}])
    embedder = Embedder()
    selector = QdrantSessionHistoryRetriever("project-v1", embedder,
        QdrantVectorSearch("http://localhost:6333", "history", transport=transport))
    session = SessionRecord("session", "private", messages=tuple(
        SessionMessage(MessageRole.USER, turn.messages[0].content[0].text, turn.run_id) for turn in candidates
    ))
    output = await AsyncRetrievedSessionHistoryPolicy("EXPLICIT_QUERY", selector, recent_turns=1).project(session)
    assert [message.content[0].text for message in output] == [f"PRIVATE_HISTORY_{i}" for i in range(3)]
    assert embedder.queries == ["EXPLICIT_QUERY"] and len(transport.requests) == 1
    request = transport.requests[0]
    assert request.json_body["filter"] == {"must": [{"has_id": list(ids[:2])}]}
    assert "PRIVATE_HISTORY" not in repr(request) and "EXPLICIT_QUERY" not in repr(request)
    assert "REMOTE_INSTRUCTION" not in repr(output)


@pytest.mark.asyncio
async def test_empty_and_invalid_history_never_embeds():
    embedder, transport = Embedder(), Transport()
    selector = QdrantSessionHistoryRetriever("project-v1", embedder,
        QdrantVectorSearch("http://localhost:6333", "history", transport=transport),
        limits=SessionHistoryLimits(max_messages=2, max_query_bytes=5))
    assert await selector.select("query", (), limit=1) == ()
    for query, candidates in (("query", turns()), ("PRIVATE_QUERY_TOO_LONG", turns()[:1]),
                              ("query", (turns()[0], turns()[0]))):
        with pytest.raises(VectorRetrievalError):
            await selector.select(query, candidates, limit=1)
    assert not embedder.queries and not transport.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_matches", [[], (VectorSearchMatch(99, 1),), None])
async def test_replacement_backend_cannot_inject_history(bad_matches):
    class Backend:
        async def search(self, *args, **kwargs):
            return bad_matches
    selector = QdrantSessionHistoryRetriever("project-v1", Embedder(), Backend())
    with pytest.raises(VectorRetrievalError, match="^vector history selection failed$"):
        await selector.select("query", turns(), limit=1)


@pytest.mark.asyncio
async def test_replacement_backend_duplicate_and_oversized_results_fail_closed():
    identity = qdrant_history_point_id("project-v1", turns()[0])
    class Backend:
        async def search(self, *args, **kwargs):
            return (VectorSearchMatch(identity, 1), VectorSearchMatch(identity, 0.5))
    selector = QdrantSessionHistoryRetriever("project-v1", Embedder(), Backend())
    for limit in (1, 2):
        with pytest.raises(VectorRetrievalError):
            await selector.select("query", turns(), limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", [[], (float("nan"),), (True,), ()])
async def test_invalid_embedding_never_reaches_backend(vector):
    transport = Transport()
    selector = QdrantSessionHistoryRetriever("project-v1", Embedder(vector),
        QdrantVectorSearch("http://localhost:6333", "history", transport=transport))
    with pytest.raises(VectorRetrievalError):
        await selector.select("query", turns(), limit=1)
    assert not transport.requests


@pytest.mark.asyncio
async def test_backend_exception_is_redacted_and_not_retried():
    class FailingTransport:
        calls = 0

        async def send(self, request):
            self.calls += 1
            raise RuntimeError("PRIVATE_QUERY SECRET_KEY REMOTE_BODY")
    transport = FailingTransport()
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=transport)
    with pytest.raises(VectorRetrievalError) as error:
        await search.search((1,), limit=1)
    assert str(error.value) == "vector search failed" and transport.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_timeout_and_task_cancellation_drain_borrowed_transport(timeout):
    entered, closed = asyncio.Event(), asyncio.Event()
    class SlowTransport:
        async def send(self, request):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                closed.set()
    search = QdrantVectorSearch("http://localhost:6333", "history", transport=SlowTransport(),
                                timeout=0.01 if timeout else 30)
    task = asyncio.create_task(search.search((1,), limit=1))
    await entered.wait()
    if not timeout:
        task.cancel()
    with pytest.raises(VectorRetrievalError if timeout else asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
async def test_embedding_cancellation_prevents_search():
    entered, closed = asyncio.Event(), asyncio.Event()
    class SlowEmbedder:
        async def embed(self, text):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                closed.set()
    transport = Transport()
    selector = QdrantSessionHistoryRetriever("project-v1", SlowEmbedder(),
        QdrantVectorSearch("http://localhost:6333", "history", transport=transport))
    task = asyncio.create_task(selector.select("query", turns(), limit=1))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not transport.requests
