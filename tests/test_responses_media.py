import base64

import pytest

from w_agent.models import (
    BlockEnd, FinishEvent, HttpStreamFrame, ImageContent, MessageRole, ModelError,
    ModelMessage, ModelRequest, OpenAIResponsesMapping, ToolDefinition,
)


def request(options=None):
    return ModelRequest(
        messages=(ModelMessage.text(MessageRole.USER, "draw"),),
        extensions={"openai_responses.image_generation": options or {}},
    )


def item(data=b"image-bytes", **kwargs):
    return {"type": "image_generation_call", "id": "ig_one", "status": "completed",
            "result": base64.b64encode(data).decode(), **kwargs}


def done(value):
    return HttpStreamFrame({"type": "response.output_item.done", "output_index": 0, "item": value})


def terminal(value):
    return HttpStreamFrame({"type": "response.completed", "response": {"status": "completed", "output": [value]}})


def test_image_tool_is_explicit_and_can_coexist_with_function_tools():
    from dataclasses import replace
    mapping = OpenAIResponsesMapping()
    candidate = replace(request({"output_format": "webp"}), tools=(ToolDefinition("search", "search", {"type": "object"}),))
    wire = mapping.generation_request(candidate, "model")
    assert [tool["type"] for tool in wire.body["tools"]] == ["function", "image_generation"]
    assert wire.body["tools"][-1]["output_format"] == "webp"
    plain = ModelRequest(messages=candidate.messages)
    assert "tools" not in mapping.generation_request(plain, "model").body


@pytest.mark.parametrize("format", ["png", "jpeg", "webp"])
def test_final_media_once_and_correct_format(format):
    decoder = OpenAIResponsesMapping().stream_decoder(request({"output_format": format}), "model")
    value = item()
    events = decoder.feed(done(value)) + decoder.feed(terminal(value))
    images = [event.block for event in events if isinstance(event, BlockEnd)]
    assert images == [ImageContent(data=b"image-bytes", media_type=f"image/{format}")]
    assert isinstance(events[-1], FinishEvent)
    assert decoder.finish() == ()


def test_terminal_only_image_and_partial_preview_not_finalized():
    decoder = OpenAIResponsesMapping().stream_decoder(request(), "model")
    assert decoder.feed(HttpStreamFrame({"type": "response.image_generation_call.partial_image", "partial_image_b64": "aGVsbG8="})) == ()
    events = decoder.feed(terminal(item()))
    assert sum(isinstance(event, BlockEnd) for event in events) == 1


@pytest.mark.parametrize("value", [item(result="@@@"), item(data=b""), item(output_format="gif"), item(id="")])
def test_malformed_image_fails_closed(value):
    decoder = OpenAIResponsesMapping().stream_decoder(request(), "model")
    with pytest.raises(ModelError):
        decoder.feed(done(value))


def test_image_limit_and_terminal_conflict():
    decoder = OpenAIResponsesMapping(max_image_bytes=3).stream_decoder(request(), "model")
    with pytest.raises(ModelError, match="byte limit"):
        decoder.feed(done(item(b"1234")))
    decoder = OpenAIResponsesMapping().stream_decoder(request(), "model")
    decoder.feed(done(item(b"first")))
    with pytest.raises(ModelError, match="conflicts"):
        decoder.feed(terminal(item(b"second")))
