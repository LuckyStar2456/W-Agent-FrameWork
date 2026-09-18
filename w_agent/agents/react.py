"""A bounded, resumable ReAct loop built on public framework contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Mapping

from w_agent.models import (
    AttemptRecord,
    CancellationToken,
    MessageRole,
    ModelCost,
    ModelExecutor,
    ModelInvocationError,
    ModelMessage,
    ModelRequest,
    PricingError,
    PricingResolver,
    TextDelta,
    TokenUsage,
    ToolCallContent,
    ToolResultContent,
)
from w_agent.tools import (
    ToolCall,
    ToolExecutionContext,
    ToolExecutorProtocol,
    ToolOutcome,
    ToolRegistry,
)

from .persistence import InMemoryRunStore, RunStore
from .budgeting import TokenEstimate, TokenEstimator
from .types import (
    AgentDefinition,
    CheckpointStatus,
    CostBudget,
    RunCheckpoint,
    RunContext,
    RunEvent,
    RunEventType,
    RunResult,
    StopReason,
)


@dataclass(slots=True)
class _ReactState:
    messages: list[ModelMessage]
    steps: int = 0
    tool_calls: int = 0
    latest_output: str = ""
    usage: TokenUsage = TokenUsage()
    model_calls: int = 0
    reported_usage_calls: int = 0
    attempts: list[AttemptRecord] = field(default_factory=list)
    cost: ModelCost | None = None
    priced_usage_calls: int = 0
    pricing_error: str | None = None


class ReactAgentExecution:
    """Single-use event stream with a final result after completion."""

    def __init__(
        self,
        loop: "ReactAgentLoop",
        definition: AgentDefinition,
        context: RunContext,
        *,
        prior_events: tuple[RunEvent, ...] = (),
        checkpoint: RunCheckpoint | None = None,
    ) -> None:
        self._loop = loop
        self._definition = definition
        self._context = context
        self._checkpoint = checkpoint
        self._started = False
        self._events = list(prior_events)
        self.result: RunResult | None = None

    def __aiter__(self) -> AsyncIterator[RunEvent]:
        if self._started:
            raise RuntimeError("agent execution is single-use")
        self._started = True
        if self._checkpoint is not None:
            return self._loop._resume_execution(self)
        return self._loop._stream_execution(self)

    async def emit(self, event_type: RunEventType, **data: Any) -> RunEvent:
        event = RunEvent(
            len(self._events) + 1,
            event_type,
            self._context.run_id,
            data,
            session_id=self._context.session_id,
        )
        await self._loop.store.append(event)
        self._events.append(event)
        return event

    async def finish(
        self,
        reason: StopReason,
        *,
        state: _ReactState,
        pending: ToolCall | None = None,
    ) -> RunEvent:
        event = await self.emit(
            RunEventType.RUN_COMPLETED,
            stop_reason=reason.value,
            steps=state.steps,
            tool_calls=state.tool_calls,
            pending_call_id=pending.id if pending is not None else None,
            input_tokens=state.usage.input_tokens,
            output_tokens=state.usage.output_tokens,
            total_tokens=state.usage.total_tokens,
            cached_input_tokens=state.usage.cached_input_tokens,
            model_calls=state.model_calls,
            reported_usage_calls=state.reported_usage_calls,
            attempts=_attempt_ledger(tuple(state.attempts)),
            usage_complete=state.reported_usage_calls == state.model_calls,
            cost=_cost_payload(state.cost),
            priced_usage_calls=state.priced_usage_calls,
            cost_complete=(
                state.cost is not None
                and state.priced_usage_calls == state.model_calls
            ),
        )
        self.result = RunResult(
            run_id=self._context.run_id,
            stop_reason=reason,
            output=state.latest_output,
            messages=tuple(state.messages),
            events=tuple(self._events),
            steps=state.steps,
            tool_calls=state.tool_calls,
            pending_tool_call=pending,
            checkpoint_id=(
                self._context.run_id
                if reason == StopReason.NEEDS_APPROVAL
                else None
            ),
            usage=state.usage,
            model_calls=state.model_calls,
            reported_usage_calls=state.reported_usage_calls,
            attempts=tuple(state.attempts),
            cost=state.cost,
            priced_usage_calls=state.priced_usage_calls,
        )
        return event


class ReactResumeExecution:
    """Lazy resume handle that claims a checkpoint only when iteration begins."""

    def __init__(
        self,
        loop: "ReactAgentLoop",
        run_id: str,
        tool_context: ToolExecutionContext,
        cancellation: CancellationToken | None,
    ) -> None:
        self._loop = loop
        self._run_id = run_id
        self._tool_context = tool_context
        self._cancellation = cancellation
        self._started = False
        self.result: RunResult | None = None

    def __aiter__(self) -> AsyncIterator[RunEvent]:
        if self._started:
            raise RuntimeError("agent resume execution is single-use")
        self._started = True
        return self._loop._claim_and_resume(self)


class ReactAgentLoop:
    """Run a bounded model/tool loop with optional durable approval resume."""

    def __init__(
        self,
        models: ModelExecutor,
        tools: ToolRegistry,
        tool_executor: ToolExecutorProtocol,
        *,
        store: RunStore | None = None,
        pricing: PricingResolver | None = None,
        token_estimator: TokenEstimator | None = None,
    ) -> None:
        self.models = models
        self.tools = tools
        self.tool_executor = tool_executor
        self.store = store if store is not None else InMemoryRunStore()
        self.pricing = pricing
        self.token_estimator = token_estimator

    def stream(
        self,
        definition: AgentDefinition,
        context: RunContext,
    ) -> ReactAgentExecution:
        return ReactAgentExecution(self, definition, context)

    async def run(
        self,
        definition: AgentDefinition,
        context: RunContext,
    ) -> RunResult:
        execution = self.stream(definition, context)
        async for _ in execution:
            pass
        return _require_result(execution.result)

    def resume_stream(
        self,
        run_id: str,
        *,
        tool_context: ToolExecutionContext,
        cancellation: CancellationToken | None = None,
    ) -> ReactResumeExecution:
        """Create a lazy stream that atomically claims a stored checkpoint."""

        return ReactResumeExecution(
            self,
            run_id,
            tool_context,
            cancellation,
        )

    async def resume(
        self,
        run_id: str,
        *,
        tool_context: ToolExecutionContext,
        cancellation: CancellationToken | None = None,
    ) -> RunResult:
        execution = self.resume_stream(
            run_id,
            tool_context=tool_context,
            cancellation=cancellation,
        )
        async for _ in execution:
            pass
        return _require_result(execution.result)

    async def _claim_and_resume(
        self,
        outer: ReactResumeExecution,
    ) -> AsyncIterator[RunEvent]:
        checkpoint = await self.store.claim_checkpoint(outer._run_id)
        prior_events = await self.store.events(outer._run_id)
        context = RunContext(
            checkpoint.run_id,
            checkpoint.messages,
            scope=checkpoint.scope,
            cancellation=outer._cancellation,
            tool_context=outer._tool_context,
            session_id=checkpoint.session_id,
        )
        execution = ReactAgentExecution(
            self,
            checkpoint.definition,
            context,
            prior_events=prior_events,
            checkpoint=checkpoint,
        )
        async for event in execution:
            yield event
        outer.result = execution.result

    async def _stream_execution(
        self,
        execution: ReactAgentExecution,
    ) -> AsyncIterator[RunEvent]:
        definition = execution._definition
        context = execution._context
        messages = list(context.messages)
        if definition.system_prompt:
            messages.insert(
                0,
                ModelMessage.text(MessageRole.SYSTEM, definition.system_prompt),
            )
        cost, pricing_error = self._initial_cost(definition)
        state = _ReactState(messages, cost=cost, pricing_error=pricing_error)
        yield await execution.emit(
            RunEventType.RUN_STARTED,
            agent=definition.name,
            max_steps=definition.max_steps,
            max_tool_calls=definition.max_tool_calls,
        )
        if pricing_error is not None:
            yield await execution.emit(
                RunEventType.COST_BUDGET_STOPPED,
                reason=StopReason.COST_UNAVAILABLE.value,
                error=pricing_error,
            )
            yield await self._finish_terminal(
                execution,
                state,
                StopReason.COST_UNAVAILABLE,
            )
            return
        async for event in self._model_loop(execution, state):
            yield event

    async def _resume_execution(
        self,
        execution: ReactAgentExecution,
    ) -> AsyncIterator[RunEvent]:
        checkpoint = execution._checkpoint
        if checkpoint is None:
            raise RuntimeError("resume execution has no checkpoint")
        _, pricing_error = self._initial_cost(checkpoint.definition)
        if checkpoint.cost is not None and checkpoint.definition.cost_budget is not None:
            budget = checkpoint.definition.cost_budget
            if (
                checkpoint.cost.price_table_version != budget.price_table_version
                or checkpoint.cost.currency != budget.currency
            ):
                pricing_error = "checkpoint-cost-identity-mismatch"
        state = _ReactState(
            messages=list(checkpoint.messages),
            steps=checkpoint.steps,
            tool_calls=checkpoint.tool_calls,
            latest_output=checkpoint.latest_output,
            usage=checkpoint.usage,
            model_calls=checkpoint.model_calls,
            reported_usage_calls=checkpoint.reported_usage_calls,
            attempts=list(checkpoint.attempts),
            cost=checkpoint.cost,
            priced_usage_calls=checkpoint.priced_usage_calls,
            pricing_error=pricing_error,
        )
        yield await execution.emit(
            RunEventType.RUN_RESUMED,
            checkpoint_status=checkpoint.status.value,
            pending_call_id=(
                checkpoint.pending_tool_call.id
                if checkpoint.pending_tool_call is not None
                else None
            ),
        )
        if pricing_error is not None or (
            checkpoint.definition.cost_budget is not None and state.cost is None
        ):
            yield await execution.emit(
                RunEventType.COST_BUDGET_STOPPED,
                reason=StopReason.COST_UNAVAILABLE.value,
                error=pricing_error or "checkpoint-cost-unavailable",
            )
            yield await self._finish_terminal(
                execution,
                state,
                StopReason.COST_UNAVAILABLE,
            )
            return

        remaining = checkpoint.remaining_tool_calls
        if checkpoint.pending_tool_call is not None:
            events, halted = await self._execute_call(
                execution,
                state,
                checkpoint.pending_tool_call,
                parse_error=None,
                remaining=remaining,
                requested=True,
                resumable=True,
            )
            for event in events:
                yield event
            if halted:
                return

        events, halted = await self._process_calls(
            execution,
            state,
            remaining,
            resumable=True,
        )
        for event in events:
            yield event
        if halted:
            return

        await self._save_ready_checkpoint(execution, state, ())
        async for event in self._model_loop(execution, state):
            yield event

    async def _model_loop(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
    ) -> AsyncIterator[RunEvent]:
        definition = execution._definition
        context = execution._context
        while state.steps < definition.max_steps:
            exhausted = _exhausted_budget_limits(definition, state.usage)
            if state.model_calls and exhausted:
                yield await execution.emit(
                    RunEventType.TOKEN_BUDGET_STOPPED,
                    step=state.steps,
                    reason=StopReason.TOKEN_BUDGET.value,
                    exceeded_limits=exhausted,
                    input_tokens=state.usage.input_tokens,
                    output_tokens=state.usage.output_tokens,
                    total_tokens=state.usage.total_tokens,
                )
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.TOKEN_BUDGET,
                )
                return
            cost_budget = definition.cost_budget
            if (
                state.model_calls
                and cost_budget is not None
                and state.cost is not None
                and state.cost.total >= cost_budget.max_cost
            ):
                yield await execution.emit(
                    RunEventType.COST_BUDGET_STOPPED,
                    step=state.steps,
                    reason=StopReason.COST_BUDGET.value,
                    max_cost=str(cost_budget.max_cost),
                    cost=_cost_payload(state.cost),
                )
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.COST_BUDGET,
                )
                return
            cancellation = context.cancellation
            if cancellation is not None and cancellation.cancelled:
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.CANCELLED,
                )
                return
            state.steps += 1
            definitions = self.tools.definitions(scope=context.scope)
            request = ModelRequest(
                messages=tuple(state.messages),
                model=definition.model,
                tools=definitions,
                temperature=definition.temperature,
                max_output_tokens=_request_output_limit(definition, state.usage),
                extensions=definition.extensions,
            )
            budget = definition.token_budget
            if self.token_estimator is not None or (
                budget is not None and budget.require_estimate
            ):
                estimate, estimate_error = await self._estimate_request(request)
            else:
                estimate, estimate_error = None, None
            if estimate_error is not None:
                yield await execution.emit(
                    RunEventType.TOKEN_ESTIMATE_UNAVAILABLE,
                    step=state.steps,
                    error=estimate_error,
                    required=(budget.require_estimate if budget is not None else False),
                )
                if budget is not None and budget.require_estimate:
                    yield await execution.emit(
                        RunEventType.TOKEN_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.TOKEN_ESTIMATE_UNAVAILABLE.value,
                        exceeded_limits=(),
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.TOKEN_ESTIMATE_UNAVAILABLE,
                    )
                    return
            if estimate is not None:
                projected_input = state.usage.input_tokens + estimate.input_tokens
                projected_total = state.usage.total_tokens + estimate.input_tokens
                estimated_limit = _request_output_limit(
                    definition,
                    state.usage,
                    estimated_input_tokens=estimate.input_tokens,
                )
                exceeded = _estimated_budget_limits(
                    definition,
                    state.usage,
                    estimate.input_tokens,
                )
                yield await execution.emit(
                    RunEventType.TOKEN_ESTIMATED,
                    step=state.steps,
                    input_tokens=estimate.input_tokens,
                    estimator=estimate.estimator,
                    exact=estimate.exact,
                    projected_input_tokens=projected_input,
                    projected_total_tokens=projected_total,
                    max_output_tokens=(
                        estimated_limit
                        if estimated_limit and estimated_limit > 0
                        else None
                    ),
                )
                soft_limits = _soft_budget_limits(
                    definition,
                    TokenUsage(projected_input, state.usage.output_tokens),
                )
                if soft_limits:
                    yield await execution.emit(
                        RunEventType.TOKEN_BUDGET_WARNING,
                        step=state.steps,
                        phase="preflight",
                        limits=soft_limits,
                        soft_limit_ratio=str(budget.soft_limit_ratio),
                    )
                if exceeded or estimated_limit == 0:
                    stopped_limits = exceeded or ("total_tokens",)
                    yield await execution.emit(
                        RunEventType.TOKEN_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.TOKEN_BUDGET.value,
                        exceeded_limits=stopped_limits,
                        estimated=True,
                        input_tokens=state.usage.input_tokens,
                        output_tokens=state.usage.output_tokens,
                        total_tokens=state.usage.total_tokens,
                        estimated_input_tokens=estimate.input_tokens,
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.TOKEN_BUDGET,
                    )
                    return
                request = replace(request, max_output_tokens=estimated_limit)
            yield await execution.emit(
                RunEventType.MODEL_STARTED,
                step=state.steps,
                tool_count=len(definitions),
                estimated_input_tokens=(
                    estimate.input_tokens if estimate is not None else None
                ),
            )
            try:
                if definition.emit_text_deltas:
                    invocation = self.models.stream(
                        request,
                        scope=context.scope,
                        cancellation=cancellation,
                    )
                    async for model_event in invocation:
                        if isinstance(model_event, TextDelta):
                            yield await execution.emit(
                                RunEventType.MODEL_TEXT_DELTA,
                                step=state.steps,
                                block_index=model_event.index,
                                text=model_event.text,
                            )
                else:
                    invocation = await self.models.invoke(
                        request,
                        scope=context.scope,
                        cancellation=cancellation,
                    )
            except asyncio.CancelledError:
                if cancellation is None or not cancellation.cancelled:
                    raise
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.CANCELLED,
                )
                return
            except ModelInvocationError as error:
                _record_attempt_usage(
                    state,
                    error.attempts,
                    pricing=self.pricing,
                    cost_budget=definition.cost_budget,
                )
                yield await execution.emit(
                    RunEventType.MODEL_FAILED,
                    step=state.steps,
                    code=error.failure.code,
                    kind=error.failure.kind.value,
                    attempts=_attempt_ledger(error.attempts),
                    attempt_usage_complete=_attempt_usage_complete(error.attempts),
                )
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.MODEL_ERROR,
                )
                return

            response = invocation.response
            if response is None:
                raise RuntimeError("model execution completed without a response")
            _record_attempt_usage(
                state,
                invocation.attempts,
                pricing=self.pricing,
                cost_budget=definition.cost_budget,
            )
            state.latest_output = response.text
            calls = tuple(
                block
                for block in response.blocks
                if isinstance(block, ToolCallContent)
            )
            if response.blocks:
                state.messages.append(
                    ModelMessage(MessageRole.ASSISTANT, response.blocks)
                )
            yield await execution.emit(
                RunEventType.MODEL_COMPLETED,
                step=state.steps,
                provider=invocation.provider,
                model=invocation.model,
                finish_reason=response.finish_reason.value,
                text=state.latest_output,
                tool_call_ids=tuple(call.id for call in calls),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
                cached_input_tokens=response.usage.cached_input_tokens,
                usage_reported=response.usage_reported,
                attempts=_attempt_ledger(invocation.attempts),
                attempt_usage_complete=_attempt_usage_complete(invocation.attempts),
            )
            yield await execution.emit(
                RunEventType.TOKEN_USAGE,
                step=state.steps,
                input_tokens=state.usage.input_tokens,
                output_tokens=state.usage.output_tokens,
                total_tokens=state.usage.total_tokens,
                cached_input_tokens=state.usage.cached_input_tokens,
                model_calls=state.model_calls,
                reported_usage_calls=state.reported_usage_calls,
                usage_complete=(
                    state.reported_usage_calls == state.model_calls
                ),
            )

            soft_limits = _soft_budget_limits(definition, state.usage)
            if soft_limits:
                yield await execution.emit(
                    RunEventType.TOKEN_BUDGET_WARNING,
                    step=state.steps,
                    phase="reconciled",
                    limits=soft_limits,
                    soft_limit_ratio=str(definition.token_budget.soft_limit_ratio),
                )

            cost_budget = definition.cost_budget
            if cost_budget is not None:
                yield await execution.emit(
                    RunEventType.COST_USAGE,
                    step=state.steps,
                    cost=_cost_payload(state.cost),
                    max_cost=str(cost_budget.max_cost),
                    priced_usage_calls=state.priced_usage_calls,
                    cost_complete=(
                        state.cost is not None
                        and state.priced_usage_calls == state.model_calls
                    ),
                )
                if (
                    state.pricing_error is not None
                    or state.cost is None
                    or state.priced_usage_calls != state.model_calls
                ):
                    yield await execution.emit(
                        RunEventType.COST_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.COST_UNAVAILABLE.value,
                        error=state.pricing_error or "attempt-cost-unavailable",
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.COST_UNAVAILABLE,
                    )
                    return
                if state.cost.total > cost_budget.max_cost:
                    yield await execution.emit(
                        RunEventType.COST_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.COST_BUDGET.value,
                        max_cost=str(cost_budget.max_cost),
                        cost=_cost_payload(state.cost),
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.COST_BUDGET,
                    )
                    return

            budget = definition.token_budget
            if budget is not None:
                if budget.require_usage and not _attempt_usage_complete(
                    invocation.attempts
                ):
                    yield await execution.emit(
                        RunEventType.TOKEN_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.TOKEN_USAGE_UNAVAILABLE.value,
                        exceeded_limits=(),
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.TOKEN_USAGE_UNAVAILABLE,
                    )
                    return
                exceeded = budget.exceeded_limits(state.usage)
                if exceeded:
                    yield await execution.emit(
                        RunEventType.TOKEN_BUDGET_STOPPED,
                        step=state.steps,
                        reason=StopReason.TOKEN_BUDGET.value,
                        exceeded_limits=exceeded,
                        input_tokens=state.usage.input_tokens,
                        output_tokens=state.usage.output_tokens,
                        total_tokens=state.usage.total_tokens,
                    )
                    yield await self._finish_terminal(
                        execution,
                        state,
                        StopReason.TOKEN_BUDGET,
                    )
                    return

            if not calls:
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.COMPLETED,
                )
                return

            events, halted = await self._process_calls(
                execution,
                state,
                calls,
                resumable=execution._checkpoint is not None,
            )
            for event in events:
                yield event
            if halted:
                return

        yield await self._finish_terminal(
            execution,
            state,
            StopReason.MAX_STEPS,
        )

    async def _process_calls(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
        calls: tuple[ToolCallContent, ...],
        *,
        resumable: bool,
    ) -> tuple[list[RunEvent], bool]:
        events: list[RunEvent] = []
        for index, emitted_call in enumerate(calls):
            if state.tool_calls >= execution._definition.max_tool_calls:
                events.append(
                    await self._finish_terminal(
                        execution,
                        state,
                        StopReason.MAX_TOOL_CALLS,
                    )
                )
                return events, True
            state.tool_calls += 1
            arguments, parse_error = _parse_arguments(emitted_call.arguments)
            call = ToolCall(
                emitted_call.id,
                emitted_call.name,
                arguments,
                scope=execution._context.scope,
            )
            call_events, halted = await self._execute_call(
                execution,
                state,
                call,
                parse_error=parse_error,
                remaining=calls[index + 1 :],
                requested=False,
                resumable=resumable,
            )
            events.extend(call_events)
            if halted:
                return events, True
        return events, False

    async def _execute_call(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
        call: ToolCall,
        *,
        parse_error: str | None,
        remaining: tuple[ToolCallContent, ...],
        requested: bool,
        resumable: bool,
    ) -> tuple[list[RunEvent], bool]:
        events: list[RunEvent] = []
        if not requested:
            events.append(
                await execution.emit(
                    RunEventType.TOOL_REQUESTED,
                    step=state.steps,
                    call_id=call.id,
                    name=call.name,
                    arguments=dict(call.arguments),
                )
            )
        if resumable:
            await self.store.save_checkpoint(
                self._checkpoint(
                    execution,
                    state,
                    pending=call,
                    remaining=remaining,
                    status=CheckpointStatus.RESUMING,
                )
            )

        result = None
        if parse_error is None:
            result = await self.tool_executor.execute(
                call,
                _tool_context(execution._context),
            )

        if result is not None and result.outcome == ToolOutcome.NEEDS_APPROVAL:
            await self.store.save_checkpoint(
                self._checkpoint(
                    execution,
                    state,
                    pending=call,
                    remaining=remaining,
                    status=CheckpointStatus.PENDING_APPROVAL,
                )
            )
            events.append(
                await execution.emit(
                    RunEventType.TOOL_COMPLETED,
                    step=state.steps,
                    call_id=call.id,
                    name=call.name,
                    outcome=result.outcome.value,
                    failure_code=result.failure.code if result.failure else None,
                )
            )
            events.append(
                await execution.finish(
                    StopReason.NEEDS_APPROVAL,
                    state=state,
                    pending=call,
                )
            )
            return events, True

        if result is None:
            content = _error_content("invalid-tool-arguments", parse_error)
            is_error = True
            outcome = ToolOutcome.FAILED.value
            failure_code = "invalid-tool-arguments"
        else:
            content = (
                result.content
                if result.outcome == ToolOutcome.SUCCEEDED
                else _error_content(
                    result.failure.code if result.failure else "tool-error",
                    result.failure.message if result.failure else "tool failed",
                )
            )
            is_error = result.is_error
            outcome = result.outcome.value
            failure_code = result.failure.code if result.failure else None
        state.messages.append(
            ModelMessage(
                MessageRole.TOOL,
                (ToolResultContent(call.id, content, is_error),),
                name=call.name,
            )
        )
        events.append(
            await execution.emit(
                RunEventType.TOOL_COMPLETED,
                step=state.steps,
                call_id=call.id,
                name=call.name,
                outcome=outcome,
                failure_code=failure_code,
            )
        )
        if resumable:
            await self._save_ready_checkpoint(execution, state, remaining)
        if result is not None and result.outcome == ToolOutcome.CANCELLED:
            events.append(
                await self._finish_terminal(
                    execution,
                    state,
                    StopReason.CANCELLED,
                )
            )
            return events, True
        return events, False

    def _checkpoint(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
        *,
        pending: ToolCall | None,
        remaining: tuple[ToolCallContent, ...],
        status: CheckpointStatus,
    ) -> RunCheckpoint:
        return RunCheckpoint(
            run_id=execution._context.run_id,
            session_id=execution._context.session_id,
            definition=execution._definition,
            scope=execution._context.scope,
            messages=tuple(state.messages),
            pending_tool_call=pending,
            remaining_tool_calls=remaining,
            steps=state.steps,
            tool_calls=state.tool_calls,
            latest_output=state.latest_output,
            status=status,
            usage=state.usage,
            model_calls=state.model_calls,
            reported_usage_calls=state.reported_usage_calls,
            attempts=tuple(state.attempts),
            cost=state.cost,
            priced_usage_calls=state.priced_usage_calls,
        )

    def _initial_cost(
        self,
        definition: AgentDefinition,
    ) -> tuple[ModelCost | None, str | None]:
        budget = definition.cost_budget
        if budget is None:
            return None, None
        if self.pricing is None:
            return None, "pricing-resolver-unavailable"
        try:
            table = self.pricing.table(budget.price_table_version)
        except PricingError:
            return None, "price-table-unavailable"
        if table.currency != budget.currency:
            return None, "price-table-currency-mismatch"
        return table.zero(), None

    async def _estimate_request(
        self,
        request: ModelRequest,
    ) -> tuple[TokenEstimate | None, str | None]:
        if self.token_estimator is None:
            return None, "estimator-unavailable"
        try:
            estimate = await self.token_estimator.estimate(request)
        except Exception:
            return None, "estimator-failed"
        if not isinstance(estimate, TokenEstimate):
            return None, "invalid-estimator-result"
        return estimate, None

    async def _save_ready_checkpoint(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
        remaining: tuple[ToolCallContent, ...],
    ) -> None:
        await self.store.save_checkpoint(
            self._checkpoint(
                execution,
                state,
                pending=None,
                remaining=remaining,
                status=CheckpointStatus.READY,
            )
        )

    async def _finish_terminal(
        self,
        execution: ReactAgentExecution,
        state: _ReactState,
        reason: StopReason,
    ) -> RunEvent:
        event = await execution.finish(reason, state=state)
        await self.store.delete_checkpoint(execution._context.run_id)
        return event


def _require_result(result: RunResult | None) -> RunResult:
    if result is None:
        raise RuntimeError("agent execution ended without a result")
    return result


def _add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        cached_input_tokens=(
            left.cached_input_tokens + right.cached_input_tokens
        ),
    )


def _record_attempt_usage(
    state: _ReactState,
    attempts: tuple[AttemptRecord, ...],
    *,
    pricing: PricingResolver | None,
    cost_budget: CostBudget | None,
) -> None:
    state.attempts.extend(attempts)
    state.model_calls += len(attempts)
    for attempt in attempts:
        if attempt.usage is not None:
            state.usage = _add_usage(state.usage, attempt.usage)
            state.reported_usage_calls += 1
            if (
                cost_budget is not None
                and pricing is not None
                and state.cost is not None
            ):
                try:
                    quoted = pricing.quote(
                        cost_budget.price_table_version,
                        attempt.provider,
                        attempt.model,
                        attempt.usage,
                    )
                    state.cost = state.cost.add(quoted)
                    state.priced_usage_calls += 1
                except PricingError:
                    state.pricing_error = "attempt-price-unavailable"


def _cost_payload(cost: ModelCost | None) -> dict[str, str] | None:
    if cost is None:
        return None
    return {
        "currency": cost.currency,
        "price_table_version": cost.price_table_version,
        "input_cost": str(cost.input_cost),
        "output_cost": str(cost.output_cost),
        "cached_input_cost": str(cost.cached_input_cost),
        "total": str(cost.total),
    }


def _attempt_usage_complete(attempts: tuple[AttemptRecord, ...]) -> bool:
    return bool(attempts) and all(attempt.usage_reported for attempt in attempts)


def _attempt_ledger(
    attempts: tuple[AttemptRecord, ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "ordinal": attempt.ordinal,
            "route_index": attempt.route_index,
            "route_attempt": attempt.route_attempt,
            "provider": attempt.provider,
            "model": attempt.model,
            "outcome": attempt.outcome.value,
            "duration_ms": attempt.duration_ms,
            "events_emitted": attempt.events_emitted,
            "failure_code": (
                attempt.failure.code if attempt.failure is not None else None
            ),
            "input_tokens": (
                attempt.usage.input_tokens if attempt.usage is not None else None
            ),
            "output_tokens": (
                attempt.usage.output_tokens if attempt.usage is not None else None
            ),
            "cached_input_tokens": (
                attempt.usage.cached_input_tokens
                if attempt.usage is not None
                else None
            ),
            "total_tokens": (
                attempt.usage.total_tokens if attempt.usage is not None else None
            ),
            "usage_reported": attempt.usage_reported,
        }
        for attempt in attempts
    )


def _request_output_limit(
    definition: AgentDefinition,
    usage: TokenUsage,
    *,
    estimated_input_tokens: int = 0,
) -> int | None:
    """Cap a request by the remaining measurable output/total run budget."""

    limits = [definition.max_output_tokens]
    budget = definition.token_budget
    if budget is not None:
        if budget.max_output_tokens is not None:
            limits.append(budget.max_output_tokens - usage.output_tokens)
        if budget.max_total_tokens is not None:
            limits.append(
                budget.max_total_tokens - usage.total_tokens - estimated_input_tokens
            )
    available = [limit for limit in limits if limit is not None]
    return min(available) if available else None


def _estimated_budget_limits(
    definition: AgentDefinition,
    usage: TokenUsage,
    estimated_input_tokens: int,
) -> tuple[str, ...]:
    budget = definition.token_budget
    if budget is None:
        return ()
    projected_input = usage.input_tokens + estimated_input_tokens
    projected_total = usage.total_tokens + estimated_input_tokens
    exceeded: list[str] = []
    if (
        budget.max_input_tokens is not None
        and projected_input > budget.max_input_tokens
    ):
        exceeded.append("input_tokens")
    if (
        budget.max_total_tokens is not None
        and projected_total >= budget.max_total_tokens
    ):
        exceeded.append("total_tokens")
    return tuple(exceeded)


def _soft_budget_limits(
    definition: AgentDefinition,
    usage: TokenUsage,
) -> tuple[str, ...]:
    budget = definition.token_budget
    if budget is None or budget.soft_limit_ratio is None:
        return ()
    ratio = budget.soft_limit_ratio
    if not isinstance(ratio, Decimal):  # normalized by TokenBudget
        raise RuntimeError("soft token limit ratio was not normalized")
    reached: list[str] = []
    values = (
        ("input_tokens", usage.input_tokens, budget.max_input_tokens),
        ("output_tokens", usage.output_tokens, budget.max_output_tokens),
        ("total_tokens", usage.total_tokens, budget.max_total_tokens),
    )
    for name, current, limit in values:
        if limit is not None and Decimal(current) / Decimal(limit) >= ratio:
            reached.append(name)
    return tuple(reached)


def _exhausted_budget_limits(
    definition: AgentDefinition,
    usage: TokenUsage,
) -> tuple[str, ...]:
    budget = definition.token_budget
    if budget is None:
        return ()
    exhausted: list[str] = []
    if (
        budget.max_input_tokens is not None
        and usage.input_tokens >= budget.max_input_tokens
    ):
        exhausted.append("input_tokens")
    if (
        budget.max_output_tokens is not None
        and usage.output_tokens >= budget.max_output_tokens
    ):
        exhausted.append("output_tokens")
    if (
        budget.max_total_tokens is not None
        and usage.total_tokens >= budget.max_total_tokens
    ):
        exhausted.append("total_tokens")
    return tuple(exhausted)


def _tool_context(context: RunContext) -> ToolExecutionContext:
    cancellation = context.cancellation or context.tool_context.cancellation
    if cancellation is context.tool_context.cancellation:
        return context.tool_context
    return replace(context.tool_context, cancellation=cancellation)


def _parse_arguments(value: str) -> tuple[Mapping[str, Any], str | None]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}, "tool arguments are not valid JSON"
    if not isinstance(parsed, dict):
        return {}, "tool arguments must decode to an object"
    return parsed, None


def _error_content(code: str, message: str | None) -> str:
    return json.dumps(
        {"error": code, "message": message or "tool failed"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
