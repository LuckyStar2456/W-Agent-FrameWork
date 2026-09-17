"""A bounded, resumable ReAct loop built on public framework contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any, Mapping

from w_agent.models import (
    CancellationToken,
    MessageRole,
    ModelExecutor,
    ModelInvocationError,
    ModelMessage,
    ModelRequest,
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
from .types import (
    AgentDefinition,
    CheckpointStatus,
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
    ) -> None:
        self.models = models
        self.tools = tools
        self.tool_executor = tool_executor
        self.store = store if store is not None else InMemoryRunStore()

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
        state = _ReactState(messages)
        yield await execution.emit(
            RunEventType.RUN_STARTED,
            agent=definition.name,
            max_steps=definition.max_steps,
            max_tool_calls=definition.max_tool_calls,
        )
        async for event in self._model_loop(execution, state):
            yield event

    async def _resume_execution(
        self,
        execution: ReactAgentExecution,
    ) -> AsyncIterator[RunEvent]:
        checkpoint = execution._checkpoint
        if checkpoint is None:
            raise RuntimeError("resume execution has no checkpoint")
        state = _ReactState(
            list(checkpoint.messages),
            checkpoint.steps,
            checkpoint.tool_calls,
            checkpoint.latest_output,
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
            yield await execution.emit(
                RunEventType.MODEL_STARTED,
                step=state.steps,
                tool_count=len(definitions),
            )
            request = ModelRequest(
                messages=tuple(state.messages),
                model=definition.model,
                tools=definitions,
                temperature=definition.temperature,
                max_output_tokens=definition.max_output_tokens,
                extensions=definition.extensions,
            )
            try:
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
                yield await execution.emit(
                    RunEventType.MODEL_FAILED,
                    step=state.steps,
                    code=error.failure.code,
                    kind=error.failure.kind.value,
                )
                yield await self._finish_terminal(
                    execution,
                    state,
                    StopReason.MODEL_ERROR,
                )
                return

            response = invocation.response
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
            )

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
        )

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
