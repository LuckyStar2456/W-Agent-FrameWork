"""Draft HTTP embedding regressions; no live models or validation run yet."""

import asyncio
import json
from dataclasses import replace

import pytest

from w_agent import (
    EmbeddingError, EmbeddingResult, HttpTextEmbedder, HttpToolResponse,
    JsonEmbeddingMapping, KnowledgeDocument, KnowledgeSnapshot, KnowledgeVectorIndex,
    TokenUsage, ollama_text_embedder, openai_compatible_text_embedder, prepare_knowledge_vectors,
)


def payload():
    return {"model": "example-model", "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 3, "total_tokens": 3}}


class Transport:
    def __init__(self, value=None, *, raw=None, status=200):
        self.body = raw if raw is not None else json.dumps(payload() if value is None else value).encode()
        self.status = status
        self.requests = []

    async def send(self, request, **kwargs):
        self.requests.append(request)
        return HttpToolResponse(self.status, {}, self.body)


def provider(transport, **options):
    return openai_compatible_text_embedder("https://embedding.example/v1", "example-model", 2,
                                           transport=transport, **options)


@pytest.mark.asyncio
async def test_openai_request_result_usage_and_borrowed_transport():
    transport = Transport()
    embedder = provider(transport, api_key="PRIVATE_KEY", request_dimensions=True)
    assert transport.requests == []
    result = await embedder.embed_result("PRIVATE_INPUT")
    assert result == EmbeddingResult((0.1, 0.2), "example-model", TokenUsage(3, 0))
    request = transport.requests[0]
    assert request.url == "https://embedding.example/v1/embeddings" and request.method == "POST"
    assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
    assert request.json_body == {"model": "example-model", "input": "PRIVATE_INPUT",
                                 "encoding_format": "float", "dimensions": 2}
    assert request.query == {} and request.max_response_bytes == embedder.max_response_bytes
    assert "PRIVATE" not in repr(embedder) and "example-model" not in repr(result)
    assert await embedder.embed("second") == result.vector
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_native_ollama_disables_truncation_and_reads_input_usage():
    transport = Transport({"model": "local-model:tag", "embeddings": [[1, 2]], "prompt_eval_count": 4})
    embedder = ollama_text_embedder("http://localhost:11434/", "local-model", 2, transport=transport)
    result = await embedder.embed_result("text")
    assert result.usage == TokenUsage(4, 0) and result.model == "local-model:tag"
    assert transport.requests[0].url == "http://localhost:11434/api/embed"
    assert transport.requests[0].json_body == {"input": "text", "model": "local-model", "truncate": False}
    assert "authorization" not in transport.requests[0].headers


@pytest.mark.asyncio
async def test_generic_mapping_can_replace_request_and_nested_response_fields():
    mapping = JsonEmbeddingMapping(("result", "vectors", 0), input_field="sentence", model_field="encoder",
                                   response_model_path=("encoder",), input_tokens_path=("meter", "tokens"),
                                   parameters_json='{"options":{"normalize":true}}')
    transport = Transport({"result": {"vectors": [[1, 2]]}, "encoder": "custom", "meter": {"tokens": 7}, "error": False})
    embedder = HttpTextEmbedder("https://example.test/encode", "custom", 2, mapping, transport=transport)
    result = await embedder.embed_result("body")
    assert result.usage == TokenUsage(7, 0)
    assert transport.requests[0].json_body == {"encoder": "custom", "sentence": "body", "options": {"normalize": True}}
    transport.requests[0].json_body["options"]["normalize"] = False
    assert mapping.build_body("again", model="custom")["options"]["normalize"] is True


@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_zero_and_model_pin_is_optional():
    value = payload()
    del value["usage"]
    value["model"] = "resolved-alias"
    result = await provider(Transport(value)).embed_result("text")
    assert result.usage is None
    with pytest.raises(EmbeddingError) as error:
        await provider(Transport(value), expected_response_model="example-model").embed_result("text")
    assert error.value.may_have_called


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", " ", 123, "x" * 17])
async def test_invalid_input_does_not_enter_transport(text):
    transport = Transport()
    with pytest.raises(EmbeddingError) as error:
        await provider(transport, max_input_bytes=16).embed(text)
    assert not error.value.may_have_called and transport.requests == []


@pytest.mark.asyncio
async def test_serialized_request_bound_checked_before_send():
    transport = Transport()
    with pytest.raises(EmbeddingError) as error:
        await provider(transport, max_request_bytes=8).embed("x")
    assert not error.value.may_have_called and not transport.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [
    b'{"data":[],"data":[]}', b'NaN', b'[]', b'not JSON',
    b'{"error":{"message":"PRIVATE_REMOTE_ERROR"}}',
    b'{"data":[{"index":0,"embedding":[NaN,1]}],"model":"x"}',
])
async def test_bad_json_or_remote_errors_are_sanitized(raw):
    transport = Transport(raw=raw)
    with pytest.raises(EmbeddingError) as error:
        await provider(transport).embed("PRIVATE_QUERY")
    assert str(error.value) == "embedding-call-failed" and error.value.may_have_called
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    {"model": "m", "data": []},
    {"model": "m", "data": [{"index": 1, "embedding": [1, 2]}]},
    {"model": "m", "data": [{"index": False, "embedding": [1, 2]}]},
    {"model": "m", "data": [{"index": 0, "embedding": [True, 2]}]},
    {"model": "m", "data": [{"index": 0, "embedding": [1]}]},
    {"model": "m", "data": [{"index": 0, "embedding": [1, 2]}] * 2},
    {**payload(), "usage": {"prompt_tokens": "3", "total_tokens": 3}},
    {**payload(), "usage": {"prompt_tokens": 3, "total_tokens": 4}},
    {**payload(), "usage": {"prompt_tokens": True, "total_tokens": 1}},
    {**payload(), "usage": None},
])
async def test_response_shape_dimension_and_counters_fail_closed(value):
    with pytest.raises(EmbeddingError):
        await provider(Transport(value)).embed("text")


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"status": 429}, {"status": 302}, {"raw": b"x" * 17}])
async def test_status_and_response_bounds_do_not_retry(options):
    transport = Transport(**options)
    with pytest.raises(EmbeddingError):
        await provider(transport, max_response_bytes=16).embed("text")
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_timeout_and_cancellation_close_transport_coroutine():
    closed, started = asyncio.Event(), asyncio.Event()

    class Slow:
        async def send(self, request, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    with pytest.raises(EmbeddingError) as error:
        await provider(Slow(), timeout=0.01).embed("text")
    assert error.value.may_have_called and closed.is_set()
    started.clear()
    closed.clear()
    task = asyncio.create_task(provider(Slow()).embed("text"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.parametrize("headers", [{"Authorization": "x\r\ny"}, {"Host": "other"},
                                      {"x-a": "1", "X-A": "2"}, {"content-type": "text/plain"}])
def test_bad_headers_rejected(headers):
    with pytest.raises(ValueError):
        provider(Transport(), headers=headers)


@pytest.mark.parametrize("endpoint", ["ftp://example.test", "https://user:key@example.test", "https://x/path?q=key", "https://x/#key"])
def test_endpoint_has_no_embedded_credentials_query_or_fragment(endpoint):
    with pytest.raises(ValueError):
        replace(provider(Transport()), endpoint=endpoint)


@pytest.mark.asyncio
async def test_snapshot_preparation_reuses_http_embedder_without_uploading_sources():
    snapshot = KnowledgeSnapshot("n", "v", (KnowledgeDocument("original", "body", "PRIVATE_SOURCE", "title"),))
    index = KnowledgeVectorIndex(snapshot, "host-model-label", 2)
    transport = Transport()
    points = await prepare_knowledge_vectors(index, provider(transport), confirm_embedding=True)
    assert points[0].point_id == index.point_ids[0] and points[0].vector == (0.1, 0.2)
    assert "PRIVATE_SOURCE" not in json.dumps(transport.requests[0].json_body)


@pytest.mark.parametrize("parameters", ['{"input":"hidden"}', '{"model":"other"}', '[]',
                                         '{"x":1,"x":2}', '{"x":NaN}'])
def test_generic_parameters_cannot_override_request_identity_or_use_invalid_json(parameters):
    with pytest.raises(ValueError):
        JsonEmbeddingMapping(("vector",), parameters_json=parameters)


@pytest.mark.asyncio
async def test_generic_missing_usage_and_model_remain_unknown():
    mapping = JsonEmbeddingMapping(("vector",), response_model_path=("model",), input_tokens_path=("usage", "input"))
    embedder = HttpTextEmbedder("https://example.test/embed", "m", 2, mapping,
                               transport=Transport({"vector": [1, 2]}))
    result = await embedder.embed_result("text")
    assert result.model is None and result.usage is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [
    {"model": "m", "embeddings": [[1, 2], [3, 4]]},
    {"model": "m", "embeddings": [[1, 2]], "prompt_eval_count": False},
    {"model": "m", "embeddings": [[1, 2]], "prompt_eval_count": -1},
])
async def test_ollama_rejects_extra_vectors_and_invalid_token_counts(value):
    embedder = ollama_text_embedder("http://localhost:11434", "m", 2, transport=Transport(value))
    with pytest.raises(EmbeddingError):
        await embedder.embed_result("text")
