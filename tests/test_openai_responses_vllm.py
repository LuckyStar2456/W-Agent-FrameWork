import pytest

from w_agent import (
    FinishReason,
    HttpStreamFrame,
    ImageContent,
    MessageRole,
    ModelError,
    ModelFailureKind,
    ModelMessage,
    ModelRequest,
    OpenAIResponsesMapping,
    TextContent,
    ToolCallContent,
    ToolDefinition,
    ToolResultContent,
    VllmProvider,
    collect_stream,
    openai_responses_provider,
    vllm_provider,
)


class FakeHttpTransport:
    def __init__(self, *, catalog=None, frames=()):
        self.catalog = catalog or {"data": []}
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
            yield HttpStreamFrame(frame, frame.get("type"))

    async def aclose(self):
        self.closed = True


class FakeCompatibleTransport:
    def __init__(self, chunks=()):
        self.chunks = chunks or (
            {
                "choices": [
                    {"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}
                ]
            },
            {
                "choices": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )
        self.stream_calls = []

    async def get_json(self, url, *, headers, timeout):
        return {"data": []}

    async def stream_json(self, url, *, headers, body, timeout):
        self.stream_calls.append((url, dict(headers), dict(body), timeout))
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        return None


def _responses_frames():
    return (
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [],
            },
        },
        {
            "type": "response.content_part.added",
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": ""},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "delta": "hello",
        },
        {
            "type": "response.output_text.done",
            "output_index": 0,
            "content_index": 0,
            "text": "hello",
        },
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 1,
            "delta": '{"q":',
        },
        {
            "type": "response.function_call_arguments.done",
            "output_index": 1,
            "arguments": '{"q":"x"}',
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hello"}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": '{"q":"x"}',
                    },
                ],
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "input_tokens_details": {"cached_tokens": 4},
                },
            },
        },
    )


@pytest.mark.asyncio
async def test_openai_responses_maps_request_and_normalizes_stream():
    transport = FakeHttpTransport(frames=_responses_frames())
    provider = openai_responses_provider(
        api_key="secret",
        default_model="gpt-test",
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
            ModelMessage(
                MessageRole.ASSISTANT,
                (ToolCallContent("prior-call", "lookup", '{"q":"old"}'),),
            ),
            ModelMessage(
                MessageRole.TOOL,
                (ToolResultContent("prior-call", "old result"),),
            ),
        ),
        tools=(ToolDefinition("lookup", "Lookup", {"type": "object"}),),
        response_schema={"type": "object", "properties": {}},
        max_output_tokens=64,
        extensions={
            "openai_responses.reasoning": {"effort": "high"},
            "openai_responses.body": {"store": False},
        },
    )

    response = await collect_stream(provider.stream(request))

    assert response.text == "hello"
    assert response.finish_reason == FinishReason.TOOL_CALLS
    assert response.usage.input_tokens == 12
    assert response.usage.output_tokens == 5
    assert response.usage.cached_input_tokens == 4
    tool = next(
        block for block in response.blocks if isinstance(block, ToolCallContent)
    )
    assert (tool.id, tool.name, tool.arguments) == (
        "call_1",
        "lookup",
        '{"q":"x"}',
    )

    url, wire, timeout = transport.stream_calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert wire.headers["Authorization"] == "Bearer secret"
    assert wire.body["instructions"] == "be concise"
    assert wire.body["input"][0]["content"][1]["type"] == "input_image"
    assert wire.body["input"][1]["type"] == "function_call"
    assert wire.body["input"][2] == {
        "type": "function_call_output",
        "call_id": "prior-call",
        "output": "old result",
    }
    assert wire.body["tools"][0]["strict"] is True
    assert wire.body["text"]["format"]["type"] == "json_schema"
    assert wire.body["reasoning"] == {"effort": "high"}
    assert wire.body["store"] is False
    assert timeout == 60.0


@pytest.mark.asyncio
async def test_openai_responses_terminal_frame_can_materialize_output_and_length():
    transport = FakeHttpTransport(
        frames=(
            {
                "type": "response.incomplete",
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "partial"}],
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
            },
        )
    )
    provider = openai_responses_provider(default_model="gpt-test", transport=transport)

    response = await collect_stream(
        provider.stream(
            ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hello"),))
        )
    )

    assert response.text == "partial"
    assert response.finish_reason == FinishReason.LENGTH


@pytest.mark.asyncio
async def test_openai_responses_rejects_reserved_overrides_and_failed_response():
    provider = openai_responses_provider(
        default_model="gpt-test", transport=FakeHttpTransport()
    )
    with pytest.raises(ModelError, match="reserved request fields") as reserved:
        await collect_stream(
            provider.stream(
                ModelRequest(
                    messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                    extensions={"openai_responses.body": {"model": "other"}},
                )
            )
        )
    assert reserved.value.failure.kind == ModelFailureKind.CONFIGURATION

    failed = openai_responses_provider(
        default_model="gpt-test",
        transport=FakeHttpTransport(
            frames=(
                {
                    "type": "response.failed",
                    "response": {
                        "status": "failed",
                        "error": {"code": "server_error", "message": "failed"},
                    },
                },
            )
        ),
    )
    with pytest.raises(ModelError, match="failed") as error:
        await collect_stream(
            failed.stream(
                ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hello"),))
            )
        )
    assert error.value.failure.code == "server_error"


def test_openai_responses_mapping_parses_catalog_strictly():
    mapping = OpenAIResponsesMapping()
    assert mapping.parse_catalog({"data": [{"id": "a"}, {"id": "a"}]}) == ("a",)
    with pytest.raises(ModelError, match="data array"):
        mapping.parse_catalog({"models": []})


@pytest.mark.asyncio
async def test_vllm_template_maps_namespaced_server_extensions():
    transport = FakeCompatibleTransport()
    provider = vllm_provider(
        api_key="local-token",
        default_model="local-model",
        discover_models=False,
        transport=transport,
    )

    response = await collect_stream(
        provider.stream(
            ModelRequest(
                messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                max_output_tokens=20,
                extensions={
                    "vllm.structured_outputs": {"choice": ["yes", "no"]},
                    "vllm.priority": -1,
                    "vllm.request_id": "request-1",
                    "vllm.session_id": "session-1",
                    "vllm.body": {"top_k": 40, "min_p": 0.05},
                },
            )
        )
    )

    assert isinstance(provider, VllmProvider)
    assert provider.base_url == "http://127.0.0.1:8000/v1"
    assert response.text == "ok"
    url, headers, body, _ = transport.stream_calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer local-token"
    assert body["max_tokens"] == 20
    assert body["structured_outputs"] == {"choice": ["yes", "no"]}
    assert body["priority"] == -1
    assert body["request_id"] == "request-1"
    assert body["session_id"] == "session-1"
    assert body["top_k"] == 40
    assert body["min_p"] == 0.05


@pytest.mark.asyncio
async def test_vllm_rejects_conflicting_and_reserved_extensions():
    provider = vllm_provider(
        default_model="local-model",
        discover_models=False,
        transport=FakeCompatibleTransport(),
    )
    with pytest.raises(ModelError, match="mutually exclusive"):
        await collect_stream(
            provider.stream(
                ModelRequest(
                    messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                    response_schema={"type": "object"},
                    extensions={"vllm.structured_outputs": {"choice": ["a"]}},
                )
            )
        )
    with pytest.raises(ModelError, match="reserved request fields"):
        await collect_stream(
            provider.stream(
                ModelRequest(
                    messages=(ModelMessage.text(MessageRole.USER, "hello"),),
                    extensions={"vllm.body": {"model": "other"}},
                )
            )
        )
