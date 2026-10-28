import pytest

from w_agent import (
    AgentDefinition,
    AttemptOutcome,
    BlockEnd,
    BlockStart,
    CursorStreamItem,
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
    NativeCursorRecovery,
    ReactAgentLoop,
    RunContext,
    RunEventType,
    StopReason,
    TextContent,
    TextDelta,
    TokenUsage,
    ToolCallContent,
    ToolCallDelta,
    ToolExecutor,
    ToolRegistry,
    UsageEvent,
    WeightedRoutingPolicy,
)


def _failure():
    return ModelFailure(
        ModelFailureKind.NETWORK,
        "connection-lost",
        "connection lost",
        retryable=True,
    )


class CursorProvider:
    def __init__(self, initial, continuations):
        self.initial = list(initial)
        self.continuations = [list(items) for items in continuations]
        self.initial_calls = 0
        self.resume_cursors = []
        self.normal_calls = 0
        self.descriptor = ModelDescriptor(
            "cursor-provider",
            "model",
            frozenset(
                {
                    ModelCapability.TEXT_INPUT,
                    ModelCapability.TEXT_OUTPUT,
                    ModelCapability.STREAMING,
                    ModelCapability.TOOL_CALLING,
                }
            ),
        )

    async def list_models(self):
        return (self.descriptor,)

    async def resolve(self, model):
        assert model == "model"
        return self.descriptor

    async def stream(self, request, *, cancellation=None):
        self.normal_calls += 1
        for item in self.initial:
            if isinstance(item, ModelFailure):
                raise ModelError(item)
            yield item.event

    async def stream_with_cursor(self, request, *, cancellation=None):
        self.initial_calls += 1
        for item in self.initial:
            if isinstance(item, ModelFailure):
                raise ModelError(item)
            yield item

    async def resume_stream(self, request, cursor, *, cancellation=None):
        self.resume_cursors.append(cursor)
        for item in self.continuations.pop(0):
            if isinstance(item, ModelFailure):
                raise ModelError(item)
            yield item


def _execution(provider, *, recovery=None):
    registry = ModelRegistry()
    registry.register("cursor-provider", provider)
    router = ModelRouter(
        registry,
        WeightedRoutingPolicy(preferred_providers=("cursor-provider",)),
    )
    executor = ModelExecutor(
        registry,
        router,
        InvocationPolicy(initial_backoff=0),
    )
    request = ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "hello"),))
    return executor.stream(request, stream_recovery=recovery)


@pytest.mark.asyncio
async def test_native_cursor_resumes_tool_delta_without_replaying_visible_events():
    provider = CursorProvider(
        [
            CursorStreamItem(BlockStart(0, "tool-call"), "generation:1"),
            CursorStreamItem(
                ToolCallDelta(0, "call-1", "search", '{"q":'),
                "generation:2",
            ),
            _failure(),
        ],
        [
            [
                CursorStreamItem(
                    ToolCallDelta(0, "call-1", "search", '"agent"}'),
                    "generation:3",
                ),
                CursorStreamItem(
                    BlockEnd(0, ToolCallContent("call-1", "search", '{"q":"agent"}')),
                    "generation:4",
                ),
                CursorStreamItem(UsageEvent(TokenUsage(5, 3)), "generation:5"),
                CursorStreamItem(FinishEvent(FinishReason.TOOL_CALLS), "generation:6"),
            ]
        ],
    )
    execution = _execution(provider, recovery=NativeCursorRecovery())

    events = [event async for event in execution]

    deltas = [
        event.arguments_delta
        for event in events
        if isinstance(event, ToolCallDelta)
    ]
    assert deltas == [
        '{"q":', '"agent"}'
    ]
    assert provider.initial_calls == 1
    assert provider.normal_calls == 0
    assert provider.resume_cursors == ["generation:2"]
    assert execution.response is not None
    assert execution.response.blocks == (
        ToolCallContent("call-1", "search", '{"q":"agent"}'),
    )
    assert [attempt.outcome for attempt in execution.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]
    assert execution.attempts[0].usage_reported is False


@pytest.mark.asyncio
async def test_react_loop_can_opt_into_native_cursor_recovery():
    provider = CursorProvider(
        [
            CursorStreamItem(BlockStart(0, "text"), "run:1"),
            CursorStreamItem(TextDelta(0, "hello"), "run:2"),
            _failure(),
        ],
        [[
            CursorStreamItem(BlockEnd(0, TextContent("hello")), "run:3"),
            CursorStreamItem(UsageEvent(TokenUsage(5, 2)), "run:4"),
            CursorStreamItem(FinishEvent(FinishReason.STOP), "run:5"),
        ]],
    )
    registry = ModelRegistry()
    registry.register("cursor-provider", provider)
    router = ModelRouter(
        registry,
        WeightedRoutingPolicy(preferred_providers=("cursor-provider",)),
    )
    executor = ModelExecutor(
        registry,
        router,
        InvocationPolicy(initial_backoff=0),
    )
    tools = ToolRegistry()
    loop = ReactAgentLoop(
        executor,
        tools,
        ToolExecutor(tools),
        stream_recovery=NativeCursorRecovery(),
    )
    context = RunContext(
        "run-1",
        (ModelMessage.text(MessageRole.USER, "hello"),),
    )

    result = await loop.run(
        AgentDefinition("cursor-agent", emit_text_deltas=True),
        context,
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.output == "hello"
    assert provider.initial_calls == 1
    assert provider.resume_cursors == ["run:2"]
    assert provider.normal_calls == 0
    assert [attempt.outcome for attempt in result.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]
    assert [event.data["text"] for event in result.events
            if event.type is RunEventType.MODEL_TEXT_DELTA] == ["hello"]


@pytest.mark.asyncio
async def test_native_cursor_rejects_repeated_position_before_visibility():
    provider = CursorProvider(
        [CursorStreamItem(BlockStart(0, "text"), "same"), _failure()],
        [[CursorStreamItem(TextDelta(0, "duplicate"), "same")]],
    )
    execution = _execution(provider, recovery=NativeCursorRecovery())
    visible = []

    with pytest.raises(ModelInvocationError) as raised:
        async for event in execution:
            visible.append(event)

    assert visible == [BlockStart(0, "text")]
    assert raised.value.failure.kind == ModelFailureKind.PROTOCOL
    assert provider.resume_cursors == ["same"]


@pytest.mark.asyncio
async def test_native_cursor_requires_explicit_strategy():
    provider = CursorProvider(
        [CursorStreamItem(BlockStart(0, "text"), "one"), _failure()],
        [],
    )
    execution = _execution(provider)

    with pytest.raises(ModelInvocationError):
        async for _event in execution:
            pass

    assert provider.normal_calls == 1
    assert provider.initial_calls == 0
    assert provider.resume_cursors == []


@pytest.mark.asyncio
async def test_native_cursor_uses_latest_position_after_second_interruption():
    provider = CursorProvider(
        [
            CursorStreamItem(BlockStart(0, "text"), "generation:1"),
            _failure(),
        ],
        [
            [CursorStreamItem(TextDelta(0, "hello"), "generation:2"), _failure()],
            [
                CursorStreamItem(BlockEnd(0, TextContent("hello")), "generation:3"),
                CursorStreamItem(FinishEvent(FinishReason.STOP), "generation:4"),
            ],
        ],
    )
    execution = _execution(provider, recovery=NativeCursorRecovery(max_resumes=2))

    events = [event async for event in execution]

    assert provider.resume_cursors == ["generation:1", "generation:2"]
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "hello"
    ]
    assert execution.response is not None
    assert execution.response.text == "hello"
    assert [attempt.outcome for attempt in execution.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]


def test_native_cursor_recovery_requires_positive_bound():
    with pytest.raises(ValueError, match="positive integer"):
        NativeCursorRecovery(max_resumes=0)
