import pytest

from w_agent import (
    BUILTIN_PROVIDER_TEMPLATES,
    FinishReason,
    HttpModelProfile,
    HttpRequest,
    HttpStreamFormat,
    HttpStreamFrame,
    HttpxProviderTransport,
    ImageContent,
    MessageRole,
    ModelCapability,
    ModelMessage,
    ModelRequest,
    OpenAICompatibleProvider,
    ProviderTemplate,
    ProviderTemplateRegistry,
    TextContent,
    ToolDefinition,
    anthropic_provider,
    collect_stream,
    deepseek_provider,
    gemini_provider,
    glm_provider,
    ollama_provider,
    qwen_compatible_provider,
    qwen_native_provider,
    turbo_provider,
)


class FakeHttpTransport:
    def __init__(self, *, catalog=None, frames=()):
        self.catalog = catalog or {}
        self.frames = frames
        self.request_calls = []
        self.stream_calls = []
        self.closed = False

    async def request_json(self, url, *, request, timeout):
        self.request_calls.append((url, request, timeout))
        return self.catalog

    async def stream(self, url, *, request, timeout):
        self.stream_calls.append((url, request, timeout))
        for frame in self.frames:
            yield frame

    async def aclose(self):
        self.closed = True


class FakeCompatibleTransport:
    def __init__(self):
        self.stream_calls = []

    async def get_json(self, url, *, headers, timeout):
        return {"data": []}

    async def stream_json(self, url, *, headers, body, timeout):
        self.stream_calls.append((url, dict(headers), dict(body), timeout))
        yield {
            "choices": [
                {"delta": {"content": "ok"}, "finish_reason": "stop"}
            ]
        }

    async def aclose(self):
        return None


def _frame(data, event=None):
    return HttpStreamFrame(data, event)


@pytest.mark.asyncio
async def test_anthropic_native_mapping_serializes_and_decodes_tools():
    transport = FakeHttpTransport(
        frames=(
            _frame(
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 8}},
                },
                "message_start",
            ),
            _frame(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                }
            ),
            _frame(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "hello"},
                }
            ),
            _frame({"type": "content_block_stop", "index": 0}),
            _frame(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "lookup",
                        "input": {},
                    },
                }
            ),
            _frame(
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": '{"q":"x"}',
                    },
                }
            ),
            _frame({"type": "content_block_stop", "index": 1}),
            _frame(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 5},
                }
            ),
            _frame({"type": "message_stop"}),
        )
    )
    provider = anthropic_provider(
        api_key="secret",
        default_model="claude-test",
        transport=transport,
    )
    request = ModelRequest(
        messages=(
            ModelMessage.text(MessageRole.SYSTEM, "be concise"),
            ModelMessage(
                MessageRole.USER,
                (
                    TextContent("inspect"),
                    ImageContent(data=b"png", media_type="image/png"),
                ),
            ),
        ),
        tools=(ToolDefinition("lookup", "Lookup", {"type": "object"}),),
    )

    response = await collect_stream(provider.stream(request))

    assert response.text == "hello"
    assert response.finish_reason == FinishReason.TOOL_CALLS
    assert response.usage.input_tokens == 8
    url, wire, _ = transport.stream_calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert wire.headers["x-api-key"] == "secret"
    assert wire.body["system"] == "be concise"
    assert wire.body["messages"][0]["content"][1]["source"]["type"] == "base64"
    assert wire.body["tools"][0]["input_schema"] == {"type": "object"}


@pytest.mark.asyncio
async def test_gemini_native_mapping_uses_sse_and_normalizes_response():
    transport = FakeHttpTransport(
        frames=(
            _frame(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "ok"},
                                    {
                                        "functionCall": {
                                            "name": "lookup",
                                            "args": {"q": "x"},
                                        }
                                    },
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 3,
                        "candidatesTokenCount": 2,
                    },
                }
            ),
        )
    )
    provider = gemini_provider(
        api_key="secret",
        default_model="gemini-test",
        transport=transport,
    )

    response = await collect_stream(
        provider.stream(
            ModelRequest(
                messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                tools=(ToolDefinition("lookup", "Lookup", {"type": "object"}),),
            )
        )
    )

    assert response.text == "ok"
    assert response.finish_reason == FinishReason.STOP
    url, wire, _ = transport.stream_calls[0]
    assert url.endswith(
        "/v1beta/models/gemini-test:streamGenerateContent?alt=sse"
    )
    assert wire.stream_format == HttpStreamFormat.SSE
    assert wire.headers["x-goog-api-key"] == "secret"
    assert wire.body["tools"][0]["functionDeclarations"][0]["name"] == "lookup"


@pytest.mark.asyncio
async def test_ollama_native_mapping_discovers_models_and_uses_ndjson():
    transport = FakeHttpTransport(
        catalog={"models": [{"name": "qwen-local"}]},
        frames=(
            _frame({"message": {"role": "assistant", "content": "local"}}),
            _frame(
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 4,
                    "eval_count": 1,
                }
            ),
        ),
    )
    provider = ollama_provider(default_model="qwen-local", transport=transport)

    models = await provider.list_models()
    response = await collect_stream(
        provider.stream(
            ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hi"),))
        )
    )

    assert [model.model for model in models] == ["qwen-local"]
    assert transport.request_calls[0][0] == "http://127.0.0.1:11434/api/tags"
    assert transport.stream_calls[0][1].stream_format == HttpStreamFormat.NDJSON
    assert response.text == "local"
    assert response.usage.output_tokens == 1


@pytest.mark.asyncio
async def test_qwen_native_mapping_sets_dashscope_stream_parameters():
    transport = FakeHttpTransport(
        frames=(
            _frame(
                {
                    "output": {
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "你好"},
                                "finish_reason": "stop",
                            }
                        ]
                    },
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                }
            ),
        )
    )
    profile = HttpModelProfile(
        "qwen-test",
        frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
                ModelCapability.STRUCTURED_OUTPUT,
            }
        ),
    )
    provider = qwen_native_provider(
        api_key="secret",
        default_model="qwen-test",
        profiles=(profile,),
        transport=transport,
    )

    response = await collect_stream(
        provider.stream(
            ModelRequest(
                messages=(ModelMessage.text(MessageRole.USER, "hi"),),
                response_schema={"type": "object"},
            )
        )
    )

    assert response.text == "你好"
    url, wire, _ = transport.stream_calls[0]
    assert url.endswith("/api/v1/services/aigc/text-generation/generation")
    assert wire.headers["X-DashScope-SSE"] == "enable"
    assert wire.body["parameters"]["incremental_output"] is True
    assert wire.body["parameters"]["response_format"]["type"] == "json_schema"


def test_compatible_vendor_templates_and_registry_are_replaceable():
    deepseek = deepseek_provider(default_model="deepseek-test")
    glm = glm_provider(default_model="glm-test")
    qwen = qwen_compatible_provider(default_model="qwen-test")
    turbo = turbo_provider(
        base_url="https://turbo.example.test/api/v1/ai",
        default_model="turbo-test",
    )

    assert isinstance(deepseek, OpenAICompatibleProvider)
    assert deepseek.base_url == "https://api.deepseek.com"
    assert glm.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert qwen.base_url.endswith("/compatible-mode/v1")
    assert turbo.base_url == "https://turbo.example.test/api/v1/ai"
    assert deepseek.max_tokens_field == "max_tokens"
    assert glm.max_tokens_field == "max_tokens"
    assert turbo.max_tokens_field == "max_tokens"
    assert turbo.include_stream_usage is False
    assert set(BUILTIN_PROVIDER_TEMPLATES) == {
        "anthropic",
        "deepseek",
        "gemini",
        "glm",
        "ollama",
        "qwen",
        "qwen-native",
        "turbo",
    }

    replacement = ProviderTemplate(
        "ollama",
        "Custom Ollama",
        "custom",
        "http://localhost:9999",
        ollama_provider,
    )
    registry = ProviderTemplateRegistry(tuple(BUILTIN_PROVIDER_TEMPLATES.values()))
    previous = registry.register(replacement, replace=True)
    assert previous is BUILTIN_PROVIDER_TEMPLATES["ollama"]
    assert registry.get("ollama") is replacement


@pytest.mark.asyncio
async def test_turbo_template_uses_legacy_compatible_request_fields():
    transport = FakeCompatibleTransport()
    provider = turbo_provider(
        base_url="https://turbo.example.test/api/v1/ai",
        default_model="turbo-test",
        transport=transport,
    )

    response = await collect_stream(
        provider.stream(
            ModelRequest(
                messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                max_output_tokens=32,
            )
        )
    )

    assert response.text == "ok"
    body = transport.stream_calls[0][2]
    assert body["max_tokens"] == 32
    assert "max_completion_tokens" not in body
    assert "stream_options" not in body


@pytest.mark.asyncio
async def test_httpx_generic_transport_parses_sse_and_ndjson():
    httpx = pytest.importorskip("httpx")

    def handler(request):
        if request.url.path == "/sse":
            return httpx.Response(
                200,
                content=(
                    b"event: message\n"
                    b'data: {"value":1}\n\n'
                    b"data: [DONE]\n\n"
                ),
            )
        return httpx.Response(200, content=b'{"value":2}\n{"value":3}\n')

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxProviderTransport(client)
    sse_request = HttpRequest(
        "POST", "/sse", body={}, stream_format=HttpStreamFormat.SSE
    )
    ndjson_request = HttpRequest(
        "POST", "/ndjson", body={}, stream_format=HttpStreamFormat.NDJSON
    )

    sse = [
        frame
        async for frame in transport.stream(
            "https://example.test/sse", request=sse_request, timeout=1
        )
    ]
    ndjson = [
        frame
        async for frame in transport.stream(
            "https://example.test/ndjson", request=ndjson_request, timeout=1
        )
    ]

    assert (sse[0].event, sse[0].data["value"]) == ("message", 1)
    assert [frame.data["value"] for frame in ndjson] == [2, 3]
    await client.aclose()
