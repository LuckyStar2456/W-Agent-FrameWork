import pytest

from w_agent import (
    FinishReason,
    HttpxOpenAICompatibleTransport,
    ImageContent,
    MessageRole,
    ModelCapability,
    ModelError,
    ModelFailureKind,
    ModelMessage,
    ModelRequest,
    OpenAICompatibleModelProfile,
    OpenAICompatibleProvider,
    TextContent,
    ToolCallContent,
    ToolDefinition,
    collect_stream,
)


class FakeTransport:
    def __init__(self, *, catalog=None, chunks=()):
        self.catalog = catalog or {"data": []}
        self.chunks = chunks
        self.get_calls = []
        self.stream_calls = []
        self.closed = False

    async def get_json(self, url, *, headers, timeout):
        self.get_calls.append((url, dict(headers), timeout))
        return self.catalog

    async def stream_json(self, url, *, headers, body, timeout):
        self.stream_calls.append((url, dict(headers), dict(body), timeout))
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def _text_capabilities(*extra):
    return frozenset(
        {
            ModelCapability.TEXT_INPUT,
            ModelCapability.TEXT_OUTPUT,
            ModelCapability.STREAMING,
            *extra,
        }
    )


@pytest.mark.asyncio
async def test_provider_discovers_models_and_preserves_explicit_profiles():
    transport = FakeTransport(
        catalog={"data": [{"id": "remote-b"}, {"id": "remote-a"}]}
    )
    provider = OpenAICompatibleProvider(
        name="local",
        base_url="http://127.0.0.1:11434/v1",
        profiles=(
            OpenAICompatibleModelProfile(
                "remote-a",
                _text_capabilities(ModelCapability.IMAGE_INPUT),
                context_window=8192,
            ),
        ),
        transport=transport,
    )

    models = await provider.list_models()

    assert [item.model for item in models] == ["remote-a", "remote-b"]
    resolved = await provider.resolve("remote-a")
    assert resolved.provider == "local"
    assert resolved.context_window == 8192
    assert ModelCapability.IMAGE_INPUT in resolved.capabilities
    assert transport.get_calls[0][0] == "http://127.0.0.1:11434/v1/models"


@pytest.mark.asyncio
async def test_provider_translates_request_and_normalizes_text_tool_stream():
    transport = FakeTransport(
        chunks=(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Hi ",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "lookup",
                                        "arguments": '{"q":',
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "content": "there",
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"x"}'}}
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "prompt_tokens_details": {"cached_tokens": 3},
                },
            },
        )
    )
    profile = OpenAICompatibleModelProfile(
        "chat",
        _text_capabilities(ModelCapability.TOOL_CALLING),
    )
    provider = OpenAICompatibleProvider(
        name="compatible",
        base_url="https://models.example.test/v1",
        api_key="secret",
        default_model="chat",
        profiles=(profile,),
        discover_models=False,
        transport=transport,
    )
    request = ModelRequest(
        messages=(ModelMessage.text(MessageRole.USER, "hello"),),
        tools=(ToolDefinition("lookup", "Lookup", {"type": "object"}),),
        max_output_tokens=20,
        stop=("END",),
        extensions={"openai_compatible.body": {"top_p": 0.8}},
    )

    response = await collect_stream(provider.stream(request))

    assert response.text == "Hi there"
    assert response.finish_reason == FinishReason.TOOL_CALLS
    assert response.usage.cached_input_tokens == 3
    tool = next(
        block for block in response.blocks if isinstance(block, ToolCallContent)
    )
    assert (tool.id, tool.name, tool.arguments) == (
        "call_1",
        "lookup",
        '{"q":"x"}',
    )
    url, headers, body, timeout = transport.stream_calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer secret"
    assert body["model"] == "chat"
    assert body["n"] == 1
    assert body["max_completion_tokens"] == 20
    assert body["top_p"] == 0.8
    assert body["tools"][0]["function"]["name"] == "lookup"
    assert timeout == 60.0


@pytest.mark.asyncio
async def test_provider_serializes_multimodal_content_and_structured_output():
    transport = FakeTransport(
        chunks=(
            {
                "choices": [
                    {
                        "delta": {"content": "{}"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    profile = OpenAICompatibleModelProfile(
        "vision",
        _text_capabilities(
            ModelCapability.IMAGE_INPUT,
            ModelCapability.STRUCTURED_OUTPUT,
        ),
    )
    provider = OpenAICompatibleProvider(
        name="compatible",
        base_url="https://models.example.test/v1",
        profiles=(profile,),
        discover_models=False,
        transport=transport,
    )
    request = ModelRequest(
        model="vision",
        messages=(
            ModelMessage(
                MessageRole.USER,
                (
                    TextContent("inspect"),
                    ImageContent(data=b"png", media_type="image/png"),
                ),
            ),
        ),
        response_schema={"type": "object", "properties": {}},
    )

    response = await collect_stream(provider.stream(request))

    assert response.text == "{}"
    body = transport.stream_calls[0][2]
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert body["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_provider_rejects_undeclared_capability_and_reserved_overrides():
    transport = FakeTransport()
    provider = OpenAICompatibleProvider(
        name="compatible",
        base_url="https://models.example.test/v1",
        default_model="text",
        profiles=(OpenAICompatibleModelProfile("text"),),
        discover_models=False,
        transport=transport,
    )
    image_request = ModelRequest(
        messages=(
            ModelMessage(
                MessageRole.USER,
                (ImageContent(url="https://example.test/image.png"),),
            ),
        )
    )
    with pytest.raises(ModelError, match="image-input"):
        await collect_stream(provider.stream(image_request))

    override_request = ModelRequest(
        messages=(ModelMessage.text(MessageRole.USER, "hello"),),
        extensions={"openai_compatible.body": {"model": "other"}},
    )
    with pytest.raises(ModelError, match="reserved request fields"):
        await collect_stream(provider.stream(override_request))
    assert transport.stream_calls == []


@pytest.mark.asyncio
async def test_provider_normalizes_stream_error_and_closes_transport():
    transport = FakeTransport(
        chunks=({"error": {"code": "overloaded", "message": "try later"}},)
    )
    provider = OpenAICompatibleProvider(
        name="compatible",
        base_url="https://models.example.test/v1",
        default_model="text",
        profiles=(OpenAICompatibleModelProfile("text"),),
        discover_models=False,
        transport=transport,
    )

    with pytest.raises(ModelError) as error:
        await collect_stream(
            provider.stream(
                ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hello"),))
            )
        )
    assert error.value.failure.code == "overloaded"

    await provider.aclose()
    assert transport.closed is True


@pytest.mark.parametrize(
    "base_url",
    [
        "models.example.test/v1",
        "https://user:secret@models.example.test/v1",
        "https://models.example.test/v1?token=secret",
        "https://models.example.test:not-a-port/v1",
    ],
)
def test_provider_rejects_unsafe_or_ambiguous_base_urls(base_url):
    with pytest.raises(ValueError, match="absolute HTTP"):
        OpenAICompatibleProvider(name="bad", base_url=base_url)


@pytest.mark.asyncio
async def test_httpx_transport_parses_sse_and_normalizes_http_errors():
    httpx = pytest.importorskip("httpx")

    def handler(request):
        if request.url.path == "/models":
            return httpx.Response(200, json={"data": [{"id": "chat"}]})
        if request.url.path == "/limited":
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"ok"},'
                b'"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxOpenAICompatibleTransport(client)
    catalog = await transport.get_json(
        "https://example.test/models", headers={}, timeout=1
    )
    chunks = [
        item
        async for item in transport.stream_json(
            "https://example.test/chat/completions",
            headers={},
            body={"model": "chat"},
            timeout=1,
        )
    ]

    assert catalog["data"][0]["id"] == "chat"
    assert chunks[0]["choices"][0]["delta"]["content"] == "ok"

    with pytest.raises(ModelError) as error:
        await transport.get_json("https://example.test/limited", headers={}, timeout=1)
    assert error.value.failure.kind == ModelFailureKind.RATE_LIMIT
    assert error.value.failure.retryable is True

    await transport.aclose()
    assert client.is_closed is False
    await client.aclose()
