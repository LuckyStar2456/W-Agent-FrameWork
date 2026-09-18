"""Policy-driven model invocation with bounded retry and failover."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from w_agent.kernel import ScopePath

from .errors import ModelError, ModelFailure, ModelFailureKind
from .provider import CancellationToken, ModelProvider, ModelRegistry
from .routing import ModelRouter, RouteDecision
from .stream_recovery import StreamRecoveryStrategy
from .types import (
    ModelRequest,
    ModelResponse,
    ModelStreamProtocolError,
    ModelStreamValidator,
    StreamEvent,
    TokenUsage,
    collect_stream,
)


class AttemptOutcome(StrEnum):
    """Terminal state of one provider/model attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class InvocationPolicyProtocol(Protocol):
    """Replaceable policy surface consumed by :class:`ModelExecutor`."""

    max_attempts_per_route: int
    max_routes: int
    timeout: float

    def permits_retry(self, failure: ModelFailure) -> bool: ...

    def retry_delay(self, failed_attempt_on_route: int) -> float: ...


@dataclass(frozen=True, slots=True)
class InvocationPolicy:
    """Explicit cost and reliability limits for one invocation."""

    max_attempts_per_route: int = 1
    max_routes: int = 1
    max_stream_replays: int = 0
    timeout: float = 60.0
    initial_backoff: float = 0.25
    backoff_multiplier: float = 2.0
    max_backoff: float = 5.0
    retryable_kinds: frozenset[ModelFailureKind] = field(
        default_factory=lambda: frozenset(
            {
                ModelFailureKind.RATE_LIMIT,
                ModelFailureKind.TIMEOUT,
                ModelFailureKind.NETWORK,
                ModelFailureKind.PROVIDER,
            }
        )
    )

    def __post_init__(self) -> None:
        if self.max_attempts_per_route < 1:
            raise ValueError("max_attempts_per_route must be at least 1")
        if self.max_routes < 1:
            raise ValueError("max_routes must be at least 1")
        if self.max_stream_replays < 0:
            raise ValueError("max_stream_replays must not be negative")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.initial_backoff < 0 or self.max_backoff < 0:
            raise ValueError("backoff values must not be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        object.__setattr__(self, "retryable_kinds", frozenset(self.retryable_kinds))

    def permits_retry(self, failure: ModelFailure) -> bool:
        """Return whether a normalized failure may be replayed."""

        return failure.retryable and failure.kind in self.retryable_kinds

    def retry_delay(self, failed_attempt_on_route: int) -> float:
        """Return deterministic delay after a failed route attempt."""

        if failed_attempt_on_route < 1:
            raise ValueError("failed_attempt_on_route must be at least 1")
        value = self.initial_backoff * (
            self.backoff_multiplier ** (failed_attempt_on_route - 1)
        )
        return min(value, self.max_backoff)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """Prompt-free audit record for one invocation attempt."""

    ordinal: int
    route_index: int
    route_attempt: int
    provider: str
    model: str
    outcome: AttemptOutcome
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    events_emitted: int = 0
    failure: ModelFailure | None = None
    next_delay: float | None = None
    usage: TokenUsage | None = None
    usage_reported: bool = False

    def __post_init__(self) -> None:
        if self.ordinal < 1 or self.route_index < 0 or self.route_attempt < 1:
            raise ValueError("invalid attempt indexes")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")
        if self.events_emitted < 0:
            raise ValueError("events_emitted must not be negative")
        if self.outcome == AttemptOutcome.SUCCEEDED and self.failure is not None:
            raise ValueError("successful attempts cannot have a failure")
        if self.outcome == AttemptOutcome.FAILED and self.failure is None:
            raise ValueError("failed attempts need a failure")
        if self.usage_reported != (self.usage is not None):
            raise ValueError("attempt usage value and reporting flag must agree")


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    """Collected response plus route decision and immutable attempt history."""

    response: ModelResponse
    decision: RouteDecision
    provider: str
    model: str
    attempts: tuple[AttemptRecord, ...]


class ModelInvocationError(ModelError):
    """Final normalized failure with the decision and all completed attempts."""

    def __init__(
        self,
        failure: ModelFailure,
        decision: RouteDecision,
        attempts: tuple[AttemptRecord, ...],
    ) -> None:
        super().__init__(failure)
        self.decision = decision
        self.attempts = attempts


class ModelStreamExecution:
    """Single-use async stream handle with observable execution state."""

    def __init__(
        self,
        executor: "ModelExecutor",
        request: ModelRequest,
        *,
        decision: RouteDecision | None,
        policy: InvocationPolicyProtocol,
        scope: ScopePath | None,
        cancellation: CancellationToken | None,
        replay_safe: bool,
        stream_recovery: StreamRecoveryStrategy | None,
    ) -> None:
        self._executor = executor
        self._request = request
        self._provided_decision = decision
        self._policy = policy
        self._scope = scope
        self._cancellation = cancellation
        self._replay_safe = replay_safe
        self._stream_recovery = stream_recovery
        self._started = False
        self.decision: RouteDecision | None = decision
        self.provider: str | None = None
        self.model: str | None = None
        self.response: ModelResponse | None = None
        self._attempts: list[AttemptRecord] = []

    @property
    def attempts(self) -> tuple[AttemptRecord, ...]:
        return tuple(self._attempts)

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        if self._started:
            raise RuntimeError("model stream execution is single-use")
        self._started = True
        return self._executor._stream_execution(self)


class ModelExecutor:
    """Execute a route decision using an explicit bounded replay policy."""

    def __init__(
        self,
        models: ModelRegistry,
        router: ModelRouter | None = None,
        policy: InvocationPolicyProtocol | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.models = models
        self.router = router or ModelRouter(models)
        self.policy = policy or InvocationPolicy()
        self._sleep = sleep

    async def invoke(
        self,
        request: ModelRequest,
        *,
        decision: RouteDecision | None = None,
        policy: InvocationPolicyProtocol | None = None,
        scope: ScopePath | None = None,
        cancellation: CancellationToken | None = None,
        replay_safe: bool = True,
    ) -> ModelInvocationResult:
        """Collect one complete response, retrying only normalized safe failures.

        Setting retry or failover limits above one can create additional billable
        model calls. ``replay_safe=False`` forces exactly one attempt on the selected
        route even if the configured policy permits more.
        """

        active_policy = policy or self.policy
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        route_decision = decision or await self.router.route(request, scope=scope)
        routes = (
            (route_decision.provider, route_decision.model),
            *route_decision.fallbacks,
        )
        route_limit = active_policy.max_routes if replay_safe else 1
        attempt_limit = active_policy.max_attempts_per_route if replay_safe else 1
        routes = routes[:route_limit]
        attempts: list[AttemptRecord] = []
        last_failure: ModelFailure | None = None

        for route_index, (provider_name, model) in enumerate(routes):
            for route_attempt in range(1, attempt_limit + 1):
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                ordinal = len(attempts) + 1
                started_at = datetime.now(UTC)
                started = time.perf_counter()
                try:
                    provider = self.models.provider(provider_name, scope=scope)
                    routed_request = replace(request, model=model)
                    async with asyncio.timeout(active_policy.timeout):
                        response = await collect_stream(
                            provider.stream(
                                routed_request,
                                cancellation=cancellation,
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failure = _normalize_failure(error, provider_name, model)
                    last_failure = failure
                    can_replay = replay_safe and active_policy.permits_retry(failure)
                    retry_same_route = can_replay and route_attempt < attempt_limit
                    can_failover = can_replay and route_index + 1 < len(routes)
                    delay = (
                        active_policy.retry_delay(route_attempt)
                        if retry_same_route
                        else None
                    )
                    attempts.append(
                        _attempt_record(
                            ordinal=ordinal,
                            route_index=route_index,
                            route_attempt=route_attempt,
                            provider=provider_name,
                            model=model,
                            outcome=AttemptOutcome.FAILED,
                            started_at=started_at,
                            started=started,
                            failure=failure,
                            next_delay=delay,
                        )
                    )
                    if retry_same_route:
                        await self._wait_for_retry(delay or 0, cancellation)
                        continue
                    if can_failover:
                        break
                    raise ModelInvocationError(
                        failure,
                        route_decision,
                        tuple(attempts),
                    ) from error

                attempts.append(
                    _attempt_record(
                        ordinal=ordinal,
                        route_index=route_index,
                        route_attempt=route_attempt,
                        provider=provider_name,
                        model=model,
                        outcome=AttemptOutcome.SUCCEEDED,
                        started_at=started_at,
                        started=started,
                        usage=(response.usage if response.usage_reported else None),
                        usage_reported=response.usage_reported,
                    )
                )
                return ModelInvocationResult(
                    response=response,
                    decision=route_decision,
                    provider=provider_name,
                    model=model,
                    attempts=tuple(attempts),
                )

        failure = last_failure or ModelFailure(
            ModelFailureKind.CONFIGURATION,
            "no-executable-route",
            "route decision did not contain an executable route",
        )
        raise ModelInvocationError(failure, route_decision, tuple(attempts))

    def stream(
        self,
        request: ModelRequest,
        *,
        decision: RouteDecision | None = None,
        policy: InvocationPolicyProtocol | None = None,
        scope: ScopePath | None = None,
        cancellation: CancellationToken | None = None,
        replay_safe: bool = True,
        stream_recovery: StreamRecoveryStrategy | None = None,
    ) -> ModelStreamExecution:
        """Create a single-use pass-through execution handle.

        Retry and failover are allowed only before the first event is yielded to
        the caller. Visible-stream replay requires both an explicit recovery
        strategy and a positive ``policy.max_stream_replays`` value.
        """

        return ModelStreamExecution(
            self,
            request,
            decision=decision,
            policy=policy or self.policy,
            scope=scope,
            cancellation=cancellation,
            replay_safe=replay_safe,
            stream_recovery=stream_recovery,
        )

    async def _stream_execution(
        self,
        execution: ModelStreamExecution,
    ) -> AsyncIterator[StreamEvent]:
        cancellation = execution._cancellation
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        decision = execution._provided_decision or await self.router.route(
            execution._request,
            scope=execution._scope,
        )
        execution.decision = decision
        policy = execution._policy
        stream_replay_limit = _stream_replay_limit(policy)
        routes = ((decision.provider, decision.model), *decision.fallbacks)
        route_limit = policy.max_routes if execution._replay_safe else 1
        attempt_limit = policy.max_attempts_per_route if execution._replay_safe else 1
        routes = routes[:route_limit]
        last_failure: ModelFailure | None = None

        for route_index, (provider_name, model) in enumerate(routes):
            for route_attempt in range(1, attempt_limit + 1):
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                ordinal = len(execution._attempts) + 1
                started_at = datetime.now(UTC)
                started = time.perf_counter()
                emitted = 0
                validator = ModelStreamValidator()
                visible_events: list[StreamEvent] = []
                try:
                    provider = self.models.provider(
                        provider_name,
                        scope=execution._scope,
                    )
                    routed_request = replace(execution._request, model=model)
                    provider_stream = provider.stream(
                        routed_request,
                        cancellation=cancellation,
                    )
                    try:
                        while True:
                            try:
                                async with asyncio.timeout(policy.timeout):
                                    event = await provider_stream.__anext__()
                            except StopAsyncIteration:
                                break
                            validator.feed(event)
                            emitted += 1
                            visible_events.append(event)
                            yield event
                    finally:
                        closer = getattr(provider_stream, "aclose", None)
                        if closer is not None:
                            await closer()
                    response = validator.finish()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failure = _normalize_failure(error, provider_name, model)
                    last_failure = failure
                    before_visibility = emitted == 0
                    strategy = execution._stream_recovery
                    can_recover_visible = (
                        execution._replay_safe
                        and not before_visibility
                        and strategy is not None
                        and stream_replay_limit > 0
                        and policy.permits_retry(failure)
                        and strategy.can_recover(routed_request, tuple(visible_events))
                    )
                    if can_recover_visible:
                        async for recovered_event in self._recover_visible_stream(
                            execution,
                            decision=decision,
                            provider=provider,
                            routed_request=routed_request,
                            provider_name=provider_name,
                            model=model,
                            route_index=route_index,
                            route_attempt=route_attempt,
                            validator=validator,
                            visible_events=visible_events,
                            initial_ordinal=ordinal,
                            initial_started_at=started_at,
                            initial_started=started,
                            initial_emitted=emitted,
                            initial_failure=failure,
                            replay_limit=stream_replay_limit,
                        ):
                            yield recovered_event
                        return
                    can_replay = (
                        execution._replay_safe
                        and before_visibility
                        and policy.permits_retry(failure)
                    )
                    retry_same_route = can_replay and route_attempt < attempt_limit
                    can_failover = can_replay and route_index + 1 < len(routes)
                    delay = (
                        policy.retry_delay(route_attempt) if retry_same_route else None
                    )
                    execution._attempts.append(
                        _attempt_record(
                            ordinal=ordinal,
                            route_index=route_index,
                            route_attempt=route_attempt,
                            provider=provider_name,
                            model=model,
                            outcome=AttemptOutcome.FAILED,
                            started_at=started_at,
                            started=started,
                            events_emitted=emitted,
                            failure=failure,
                            next_delay=delay,
                        )
                    )
                    if retry_same_route:
                        await self._wait_for_retry(delay or 0, cancellation)
                        continue
                    if can_failover:
                        break
                    raise ModelInvocationError(
                        failure,
                        decision,
                        execution.attempts,
                    ) from error

                execution._attempts.append(
                    _attempt_record(
                        ordinal=ordinal,
                        route_index=route_index,
                        route_attempt=route_attempt,
                        provider=provider_name,
                        model=model,
                        outcome=AttemptOutcome.SUCCEEDED,
                        started_at=started_at,
                        started=started,
                        events_emitted=emitted,
                        usage=(response.usage if response.usage_reported else None),
                        usage_reported=response.usage_reported,
                    )
                )
                execution.provider = provider_name
                execution.model = model
                execution.response = response
                return

        failure = last_failure or ModelFailure(
            ModelFailureKind.CONFIGURATION,
            "no-executable-route",
            "route decision did not contain an executable route",
        )
        raise ModelInvocationError(failure, decision, execution.attempts)

    async def _recover_visible_stream(
        self,
        execution: ModelStreamExecution,
        *,
        decision: RouteDecision,
        provider: ModelProvider,
        routed_request: ModelRequest,
        provider_name: str,
        model: str,
        route_index: int,
        route_attempt: int,
        validator: ModelStreamValidator,
        visible_events: list[StreamEvent],
        initial_ordinal: int,
        initial_started_at: datetime,
        initial_started: float,
        initial_emitted: int,
        initial_failure: ModelFailure,
        replay_limit: int,
    ) -> AsyncIterator[StreamEvent]:
        """Replay one visible text stream with exact semantic prefix checks."""

        policy = execution._policy
        cancellation = execution._cancellation
        strategy = execution._stream_recovery
        if strategy is None:
            raise RuntimeError("stream recovery strategy disappeared")
        first_delay = policy.retry_delay(1)
        execution._attempts.append(
            _attempt_record(
                ordinal=initial_ordinal,
                route_index=route_index,
                route_attempt=route_attempt,
                provider=provider_name,
                model=model,
                outcome=AttemptOutcome.FAILED,
                started_at=initial_started_at,
                started=initial_started,
                events_emitted=initial_emitted,
                failure=initial_failure,
                next_delay=first_delay,
            )
        )

        for replay_index in range(1, replay_limit + 1):
            delay = policy.retry_delay(replay_index)
            await self._wait_for_retry(delay, cancellation)
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            ordinal = len(execution._attempts) + 1
            replay_route_attempt = route_attempt + replay_index
            started_at = datetime.now(UTC)
            started = time.perf_counter()
            emitted = 0
            replay_filter = strategy.start(routed_request, tuple(visible_events))
            try:
                provider_stream = provider.stream(
                    routed_request,
                    cancellation=cancellation,
                )
                try:
                    while True:
                        try:
                            async with asyncio.timeout(policy.timeout):
                                event = await provider_stream.__anext__()
                        except StopAsyncIteration:
                            break
                        for recovered in replay_filter.feed(event):
                            validator.feed(recovered)
                            visible_events.append(recovered)
                            emitted += 1
                            yield recovered
                finally:
                    closer = getattr(provider_stream, "aclose", None)
                    if closer is not None:
                        await closer()
                replay_filter.finish()
                response = validator.finish()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failure = _normalize_failure(error, provider_name, model)
                can_retry = (
                    replay_index < replay_limit
                    and policy.permits_retry(failure)
                    and strategy.can_recover(routed_request, tuple(visible_events))
                )
                next_delay = policy.retry_delay(replay_index + 1) if can_retry else None
                execution._attempts.append(
                    _attempt_record(
                        ordinal=ordinal,
                        route_index=route_index,
                        route_attempt=replay_route_attempt,
                        provider=provider_name,
                        model=model,
                        outcome=AttemptOutcome.FAILED,
                        started_at=started_at,
                        started=started,
                        events_emitted=emitted,
                        failure=failure,
                        next_delay=next_delay,
                    )
                )
                if can_retry:
                    continue
                raise ModelInvocationError(
                    failure,
                    decision,
                    execution.attempts,
                ) from error

            execution._attempts.append(
                _attempt_record(
                    ordinal=ordinal,
                    route_index=route_index,
                    route_attempt=replay_route_attempt,
                    provider=provider_name,
                    model=model,
                    outcome=AttemptOutcome.SUCCEEDED,
                    started_at=started_at,
                    started=started,
                    events_emitted=emitted,
                    usage=(response.usage if response.usage_reported else None),
                    usage_reported=response.usage_reported,
                )
            )
            execution.provider = provider_name
            execution.model = model
            execution.response = response
            return

        raise RuntimeError("stream recovery loop exhausted without a result")

    async def _wait_for_retry(
        self,
        delay: float,
        cancellation: CancellationToken | None,
    ) -> None:
        if delay <= 0:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            return
        if cancellation is None:
            await self._sleep(delay)
            return
        sleep_task = asyncio.create_task(self._sleep(delay))
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, pending = await asyncio.wait(
                {sleep_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if cancel_task in done:
                cancellation.raise_if_cancelled()
            await sleep_task
        finally:
            for task in (sleep_task, cancel_task):
                if not task.done():
                    task.cancel()


def _attempt_record(
    *,
    ordinal: int,
    route_index: int,
    route_attempt: int,
    provider: str,
    model: str,
    outcome: AttemptOutcome,
    started_at: datetime,
    started: float,
    failure: ModelFailure | None = None,
    next_delay: float | None = None,
    events_emitted: int = 0,
    usage: TokenUsage | None = None,
    usage_reported: bool = False,
) -> AttemptRecord:
    return AttemptRecord(
        ordinal=ordinal,
        route_index=route_index,
        route_attempt=route_attempt,
        provider=provider,
        model=model,
        outcome=outcome,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        events_emitted=events_emitted,
        failure=failure,
        next_delay=next_delay,
        usage=usage,
        usage_reported=usage_reported,
    )


def _stream_replay_limit(policy: InvocationPolicyProtocol) -> int:
    value = getattr(policy, "max_stream_replays", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("policy.max_stream_replays must be a non-negative integer")
    return value


def _normalize_failure(
    error: Exception,
    provider: str,
    model: str,
) -> ModelFailure:
    if isinstance(error, ModelError):
        source = error.failure
        return ModelFailure(
            kind=source.kind,
            code=source.code,
            message=source.message,
            retryable=source.retryable,
            provider=source.provider or provider,
            model=source.model or model,
        )
    if isinstance(error, TimeoutError):
        return ModelFailure(
            ModelFailureKind.TIMEOUT,
            "invocation-timeout",
            "model invocation timed out",
            retryable=True,
            provider=provider,
            model=model,
        )
    if isinstance(error, ModelStreamProtocolError):
        return ModelFailure(
            ModelFailureKind.PROTOCOL,
            "invalid-stream-protocol",
            str(error),
            retryable=False,
            provider=provider,
            model=model,
        )
    return ModelFailure(
        ModelFailureKind.PROVIDER,
        "unhandled-provider-error",
        f"provider raised {type(error).__name__}",
        retryable=False,
        provider=provider,
        model=model,
    )
