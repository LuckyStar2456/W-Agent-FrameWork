import pytest

from w_agent import (
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    JsonlModelCassette,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelRequest,
    RecordingModelProvider,
    ReplayModelProvider,
    ScriptedModelProvider,
    ScriptedModelTurn,
    TextContent,
    TextDelta,
    TokenUsage,
    UsageEvent,
    collect_stream,
)


def _descriptor():
    return ModelDescriptor(
        "scripted",
        "test-model",
        frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
            }
        ),
    )


def _events(text):
    return (
        BlockStart(0, "text"),
        TextDelta(0, text),
        BlockEnd(0, TextContent(text)),
        UsageEvent(TokenUsage(3, 2)),
        FinishEvent(FinishReason.STOP),
    )


def _request(prompt="hello"):
    return ModelRequest(
        (ModelMessage.text(MessageRole.USER, prompt),),
        model="test-model",
    )


@pytest.mark.asyncio
async def test_scripted_provider_is_finite_deterministic_and_network_free():
    provider = ScriptedModelProvider(
        _descriptor(),
        (ScriptedModelTurn(_events("answer"), expected_model="test-model"),),
    )

    response = await collect_stream(provider.stream(_request()))

    assert response.text == "answer"
    assert response.usage == TokenUsage(3, 2)
    assert provider.remaining_turns == 0
    assert provider.requests[0].messages[0].content[0].text == "hello"


@pytest.mark.asyncio
async def test_record_and_replay_uses_explicit_sensitive_content_authority(tmp_path):
    cassette = JsonlModelCassette(tmp_path / "model.jsonl")
    source = ScriptedModelProvider(
        _descriptor(),
        (ScriptedModelTurn(_events("secret answer")),),
    )
    with pytest.raises(ValueError, match="explicit authorization"):
        RecordingModelProvider(
            source,
            cassette,
            allow_sensitive_content=False,
        )
    recording = RecordingModelProvider(
        source,
        cassette,
        allow_sensitive_content=True,
        redact=lambda value: value.replace("secret", "[redacted]"),
    )

    live = await collect_stream(recording.stream(_request("secret prompt")))
    persisted = (tmp_path / "model.jsonl").read_text(encoding="utf-8")

    assert live.text == "secret answer"
    assert "secret prompt" not in persisted
    assert "secret answer" not in persisted
    assert "[redacted] answer" in persisted

    replay = await ReplayModelProvider.from_cassette(
        _descriptor(),
        cassette,
        allow_sensitive_content=True,
    )
    replayed = await collect_stream(replay.stream(_request("different prompt")))

    assert replayed.text == "[redacted] answer"
    assert replayed.usage == TokenUsage(3, 2)
    assert replay.remaining_records == 0


@pytest.mark.asyncio
async def test_replay_rejects_request_shape_mismatch(tmp_path):
    cassette = JsonlModelCassette(tmp_path / "model.jsonl")
    source = ScriptedModelProvider(
        _descriptor(),
        (ScriptedModelTurn(_events("answer")),),
    )
    recording = RecordingModelProvider(
        source,
        cassette,
        allow_sensitive_content=True,
    )
    await collect_stream(recording.stream(_request()))
    replay = await ReplayModelProvider.from_cassette(
        _descriptor(),
        cassette,
        allow_sensitive_content=True,
    )
    mismatched = ModelRequest(
        (
            ModelMessage.text(MessageRole.USER, "one"),
            ModelMessage.text(MessageRole.USER, "two"),
        ),
        model="test-model",
    )

    with pytest.raises(RuntimeError, match="shape"):
        await collect_stream(replay.stream(mismatched))
