import pytest

from w_agent import (
    AttemptOutcome,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    InvocationPolicy,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelError,
    ModelExecutor,
    ModelFailure,
    ModelFailureKind,
    ModelInvocationError,
    ModelMessage,
    ModelRegistry,
    ModelRequest,
    ModelRouter,
    TextContent,
    TextDelta,
    TokenUsage,
    UsageEvent,
    VerifiedTextPrefixRecovery,
    WeightedRoutingPolicy,
)


class RecoverableProvider:
    def __init__(self, streams):
        self.name = "recoverable"
        self.model = "text"
        self.streams = list(streams)
        self.calls = 0
        self.descriptor = ModelDescriptor(
            provider=self.name,
            model=self.model,
            capabilities=frozenset(
                {
                    ModelCapability.TEXT_INPUT,
                    ModelCapability.TEXT_OUTPUT,
                    ModelCapability.STREAMING,
                }
            ),
        )

    async def list_models(self):
        return (self.descriptor,)

    async def resolve(self, model):
        assert model == self.model
        return self.descriptor

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        for value in self.streams.pop(0):
            if isinstance(value, ModelFailure):
                raise ModelError(value)
            yield value


def _failure():
    return ModelFailure(
        ModelFailureKind.NETWORK,
        "connection-lost",
        "connection lost",
        retryable=True,
    )


def _request():
    return ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hello"),))


def _executor(provider, *, replays, delays):
    registry = ModelRegistry()
    registry.register(provider.name, provider)
    router = ModelRouter(
        registry,
        WeightedRoutingPolicy(preferred_providers=(provider.name,)),
    )

    async def record_sleep(delay):
        delays.append(delay)

    return ModelExecutor(
        registry,
        router,
        InvocationPolicy(
            max_stream_replays=replays,
            initial_backoff=0.1,
            backoff_multiplier=2,
        ),
        sleep=record_sleep,
    )


@pytest.mark.asyncio
async def test_visible_text_stream_replays_exact_prefix_and_emits_only_suffix():
    provider = RecoverableProvider(
        [
            [BlockStart(0, "text"), TextDelta(0, "hel"), _failure()],
            [
                BlockStart(7, "text"),
                TextDelta(7, "he"),
                TextDelta(7, "llo"),
                BlockEnd(7, TextContent("hello")),
                UsageEvent(TokenUsage(4, 2)),
                FinishEvent(FinishReason.STOP),
            ],
        ]
    )
    delays = []
    execution = _executor(provider, replays=1, delays=delays).stream(
        _request(),
        stream_recovery=VerifiedTextPrefixRecovery(),
    )

    events = [event async for event in execution]

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "hel",
        "lo",
    ]
    assert execution.response is not None
    assert execution.response.text == "hello"
    assert execution.response.usage == TokenUsage(4, 2)
    assert provider.calls == 2
    assert delays == [0.1]
    assert [item.outcome for item in execution.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]
    assert [item.events_emitted for item in execution.attempts] == [2, 4]


@pytest.mark.asyncio
async def test_recovery_can_extend_prefix_across_multiple_bounded_replays():
    provider = RecoverableProvider(
        [
            [BlockStart(0, "text"), TextDelta(0, "hel"), _failure()],
            [
                BlockStart(1, "text"),
                TextDelta(1, "hello "),
                _failure(),
            ],
            [
                BlockStart(2, "text"),
                TextDelta(2, "hello"),
                TextDelta(2, " world"),
                BlockEnd(2, TextContent("hello world")),
                FinishEvent(FinishReason.STOP),
            ],
        ]
    )
    delays = []
    execution = _executor(provider, replays=2, delays=delays).stream(
        _request(),
        stream_recovery=VerifiedTextPrefixRecovery(),
    )

    events = [event async for event in execution]

    assert (
        "".join(event.text for event in events if isinstance(event, TextDelta))
        == "hello world"
    )
    assert execution.response is not None
    assert execution.response.text == "hello world"
    assert provider.calls == 3
    assert delays == [0.1, 0.2]
    assert [item.outcome for item in execution.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_divergent_replay_fails_closed_without_exposing_new_text():
    provider = RecoverableProvider(
        [
            [BlockStart(0, "text"), TextDelta(0, "hel"), _failure()],
            [BlockStart(1, "text"), TextDelta(1, "bye")],
        ]
    )
    execution = _executor(provider, replays=1, delays=[]).stream(
        _request(),
        stream_recovery=VerifiedTextPrefixRecovery(),
    )
    visible = []

    with pytest.raises(ModelInvocationError) as caught:
        async for event in execution:
            visible.append(event)

    assert [event.text for event in visible if isinstance(event, TextDelta)] == ["hel"]
    assert caught.value.failure.kind == ModelFailureKind.PROTOCOL
    assert caught.value.failure.code == "invalid-stream-protocol"
    assert provider.calls == 2
    assert len(caught.value.attempts) == 2


@pytest.mark.asyncio
async def test_visible_replay_remains_disabled_without_both_explicit_controls():
    streams = [
        [BlockStart(0, "text"), TextDelta(0, "hel"), _failure()],
        [
            BlockStart(0, "text"),
            TextDelta(0, "hello"),
            BlockEnd(0, TextContent("hello")),
            FinishEvent(FinishReason.STOP),
        ],
    ]
    no_strategy = RecoverableProvider([list(item) for item in streams])
    execution = _executor(no_strategy, replays=1, delays=[]).stream(_request())
    with pytest.raises(ModelInvocationError):
        async for _ in execution:
            pass
    assert no_strategy.calls == 1

    no_budget = RecoverableProvider([list(item) for item in streams])
    execution = _executor(no_budget, replays=0, delays=[]).stream(
        _request(), stream_recovery=VerifiedTextPrefixRecovery()
    )
    with pytest.raises(ModelInvocationError):
        async for _ in execution:
            pass
    assert no_budget.calls == 1
