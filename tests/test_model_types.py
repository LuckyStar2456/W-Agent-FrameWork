import pytest

from w_agent import (
    BlockEnd,
    BlockStart,
    ErrorEvent,
    FinishEvent,
    FinishReason,
    ImageContent,
    MessageRole,
    ModelCapability,
    ModelError,
    ModelFailure,
    ModelFailureKind,
    ModelMessage,
    ModelRequest,
    ModelStreamProtocolError,
    TextContent,
    TextDelta,
    TokenUsage,
    ToolDefinition,
    UsageEvent,
    collect_stream,
)


async def _events(*items):
    for item in items:
        yield item


def test_request_derives_standard_capabilities_and_freezes_extensions():
    request = ModelRequest(
        messages=(
            ModelMessage(
                role=MessageRole.USER,
                content=(
                    TextContent("describe"),
                    ImageContent(url="https://example.test/a.png"),
                ),
            ),
        ),
        tools=(ToolDefinition("lookup", "Look up a record", {"type": "object"}),),
        response_schema={"type": "object"},
        extensions={"vendor.option": True},
    )

    assert request.required_capabilities() == {
        ModelCapability.TEXT_INPUT,
        ModelCapability.TEXT_OUTPUT,
        ModelCapability.IMAGE_INPUT,
        ModelCapability.TOOL_CALLING,
        ModelCapability.STRUCTURED_OUTPUT,
    }
    with pytest.raises(TypeError):
        request.extensions["vendor.option"] = False


@pytest.mark.asyncio
async def test_collect_stream_validates_and_collects_terminal_response():
    response = await collect_stream(
        _events(
            BlockStart(0, "text"),
            TextDelta(0, "hello"),
            BlockEnd(0, TextContent("hello")),
            UsageEvent(TokenUsage(input_tokens=2, output_tokens=1)),
            FinishEvent(FinishReason.STOP),
        )
    )

    assert response.text == "hello"
    assert response.usage.output_tokens == 1
    assert response.finish_reason == FinishReason.STOP


@pytest.mark.asyncio
async def test_collect_stream_rejects_incomplete_or_out_of_order_events():
    with pytest.raises(ModelStreamProtocolError, match="unopened"):
        await collect_stream(
            _events(TextDelta(0, "orphan"), FinishEvent(FinishReason.STOP))
        )

    with pytest.raises(ModelStreamProtocolError, match="without finish"):
        await collect_stream(
            _events(BlockStart(0, "text"), BlockEnd(0, TextContent("x")))
        )

    failure = ModelFailure(ModelFailureKind.RATE_LIMIT, "limited", "try later", True)
    with pytest.raises(ModelError) as error:
        await collect_stream(_events(ErrorEvent(failure)))
    assert error.value.failure is failure
