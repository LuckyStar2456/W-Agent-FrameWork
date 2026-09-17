import asyncio

import pytest

from w_agent import (
    AttemptOutcome,
    BlockEnd,
    BlockStart,
    CancellationToken,
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
    WeightedRoutingPolicy,
)


class ScriptedProvider:
    def __init__(self, name, model, outcomes):
        self.name = name
        self.model = model
        self.outcomes = list(outcomes)
        self.requests = []
        self.descriptor = ModelDescriptor(
            provider=name,
            model=model,
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
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, ModelFailure):
            raise ModelError(outcome)
        if outcome == "slow":
            await asyncio.sleep(1)
        if outcome == "protocol":
            yield BlockStart(0, "text")
            return
        text = str(outcome)
        yield BlockStart(0, "text")
        yield TextDelta(0, text)
        yield BlockEnd(0, TextContent(text))
        yield FinishEvent(FinishReason.STOP)


def _failure(kind=ModelFailureKind.NETWORK, *, retryable=True):
    return ModelFailure(kind, "temporary", "temporary failure", retryable)


def _request(model=None):
    return ModelRequest(
        model=model,
        messages=(ModelMessage.text(MessageRole.USER, "private prompt"),),
    )


def _executor(primary, backup=None, *, policy=None, sleep=asyncio.sleep):
    registry = ModelRegistry()
    registry.register(primary.name, primary)
    if backup is not None:
        registry.register(backup.name, backup)
    router = ModelRouter(
        registry,
        WeightedRoutingPolicy(preferred_providers=(primary.name,)),
    )
    return ModelExecutor(registry, router, policy, sleep=sleep)


@pytest.mark.asyncio
async def test_executor_returns_response_decision_and_prompt_free_attempt():
    primary = ScriptedProvider("primary", "chat", ["ok"])
    executor = _executor(primary)

    result = await executor.invoke(_request("primary/chat"))

    assert result.response.text == "ok"
    assert (result.provider, result.model) == ("primary", "chat")
    assert result.attempts[0].outcome == AttemptOutcome.SUCCEEDED
    assert result.attempts[0].failure is None
    assert "private prompt" not in repr(result.attempts)
    assert primary.requests[0].model == "chat"


@pytest.mark.asyncio
async def test_executor_retries_retryable_failure_with_bounded_backoff():
    primary = ScriptedProvider("primary", "chat", [_failure(), "recovered"])
    delays = []

    async def record_sleep(delay):
        delays.append(delay)

    executor = _executor(
        primary,
        policy=InvocationPolicy(
            max_attempts_per_route=2,
            initial_backoff=0.5,
            max_backoff=1,
        ),
        sleep=record_sleep,
    )

    result = await executor.invoke(_request())

    assert result.response.text == "recovered"
    assert [item.outcome for item in result.attempts] == [
        AttemptOutcome.FAILED,
        AttemptOutcome.SUCCEEDED,
    ]
    assert result.attempts[0].next_delay == 0.5
    assert delays == [0.5]


@pytest.mark.asyncio
async def test_executor_fails_over_after_retryable_route_failure():
    primary = ScriptedProvider("primary", "chat", [_failure()])
    backup = ScriptedProvider("backup", "chat", ["backup"])
    executor = _executor(
        primary,
        backup,
        policy=InvocationPolicy(max_routes=2),
    )

    result = await executor.invoke(_request())

    assert result.response.text == "backup"
    assert (result.provider, result.model) == ("backup", "chat")
    assert [(item.provider, item.route_index) for item in result.attempts] == [
        ("primary", 0),
        ("backup", 1),
    ]


@pytest.mark.asyncio
async def test_executor_does_not_replay_nonretryable_failure():
    primary = ScriptedProvider(
        "primary",
        "chat",
        [_failure(ModelFailureKind.AUTHENTICATION, retryable=False)],
    )
    backup = ScriptedProvider("backup", "chat", ["must-not-run"])
    executor = _executor(
        primary,
        backup,
        policy=InvocationPolicy(max_attempts_per_route=3, max_routes=2),
    )

    with pytest.raises(ModelInvocationError) as caught:
        await executor.invoke(_request())

    assert caught.value.failure.kind == ModelFailureKind.AUTHENTICATION
    assert len(caught.value.attempts) == 1
    assert backup.requests == []


@pytest.mark.asyncio
async def test_executor_defaults_to_one_billable_attempt():
    primary = ScriptedProvider("primary", "chat", [_failure(), "must-not-run"])
    backup = ScriptedProvider("backup", "chat", ["must-not-run"])
    executor = _executor(primary, backup)

    with pytest.raises(ModelInvocationError) as caught:
        await executor.invoke(_request())

    assert len(caught.value.attempts) == 1
    assert len(primary.requests) == 1
    assert backup.requests == []


@pytest.mark.asyncio
async def test_replay_safe_false_overrides_resilient_policy():
    primary = ScriptedProvider("primary", "chat", [_failure(), "must-not-run"])
    backup = ScriptedProvider("backup", "chat", ["must-not-run"])
    executor = _executor(
        primary,
        backup,
        policy=InvocationPolicy(max_attempts_per_route=2, max_routes=2),
    )

    with pytest.raises(ModelInvocationError):
        await executor.invoke(_request(), replay_safe=False)

    assert len(primary.requests) == 1
    assert backup.requests == []


@pytest.mark.asyncio
async def test_executor_normalizes_timeout_and_stream_protocol_failure():
    slow = ScriptedProvider("slow", "chat", ["slow"])
    timeout_executor = _executor(slow, policy=InvocationPolicy(timeout=0.01))

    with pytest.raises(ModelInvocationError) as timeout_error:
        await timeout_executor.invoke(_request())
    assert timeout_error.value.failure.kind == ModelFailureKind.TIMEOUT
    assert timeout_error.value.failure.retryable is True

    invalid = ScriptedProvider("invalid", "chat", ["protocol"])
    protocol_executor = _executor(invalid)
    with pytest.raises(ModelInvocationError) as protocol_error:
        await protocol_executor.invoke(_request())
    assert protocol_error.value.failure.kind == ModelFailureKind.PROTOCOL
    assert protocol_error.value.failure.retryable is False


@pytest.mark.asyncio
async def test_executor_honors_pre_cancelled_token():
    primary = ScriptedProvider("primary", "chat", ["must-not-run"])
    executor = _executor(primary)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await executor.invoke(_request(), cancellation=token)
    assert primary.requests == []


def test_invocation_policy_validates_limits_and_backoff():
    with pytest.raises(ValueError, match="max_routes"):
        InvocationPolicy(max_routes=0)
    with pytest.raises(ValueError, match="timeout"):
        InvocationPolicy(timeout=0)

    policy = InvocationPolicy(
        initial_backoff=0.5,
        backoff_multiplier=3,
        max_backoff=2,
    )
    assert [policy.retry_delay(index) for index in (1, 2, 3)] == [0.5, 1.5, 2]
