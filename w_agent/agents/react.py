"""A small public-protocol ReAct loop for local agent development."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, Mapping

from w_agent.models import (
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

from .types import (
    AgentDefinition,
    RunContext,
    RunEvent,
    RunEventType,
    RunResult,
    StopReason,
)


class ReactAgentExecution:
    """Single-use event stream with a final result after completion."""

    def __init__(
        self,
        loop: "ReactAgentLoop",
        definition: AgentDefinition,
        context: RunContext,
    ) -> None:
        self._loop = loop
        self._definition = definition
        self._context = context
        self._started = False
        self._events: list[RunEvent] = []
        self.result: RunResult | None = None

    def __aiter__(self) -> AsyncIterator[RunEvent]:
        if self._started:
            raise RuntimeError("agent execution is single-use")
        self._started = True
        return self._loop._stream_execution(self)

    def emit(self, event_type: RunEventType, **data: Any) -> RunEvent:
        event = RunEvent(
            len(self._events) + 1,
            event_type,
            self._context.run_id,
            data,
        )
        self._events.append(event)
        return event

    def finish(
        self,
        reason: StopReason,
        *,
        output: str,
        messages: list[ModelMessage],
        steps: int,
        tool_calls: int,
        pending: ToolCall | None = None,
    ) -> RunEvent:
        event = self.emit(
            RunEventType.RUN_COMPLETED,
            stop_reason=reason.value,
            steps=steps,
            tool_calls=tool_calls,
            pending_call_id=pending.id if pending is not None else None,
        )
        self.result = RunResult(
            run_id=self._context.run_id,
            stop_reason=reason,
            output=output,
            messages=tuple(messages),
            events=tuple(self._events),
            steps=steps,
            tool_calls=tool_calls,
            pending_tool_call=pending,
        )
        return event


class ReactAgentLoop:
    """Run a bounded model/tool loop using only public framework contracts."""

    def __init__(
        self,
        models: ModelExecutor,
        tools: ToolRegistry,
        tool_executor: ToolExecutorProtocol,
    ) -> None:
        self.models = models
        self.tools = tools
        self.tool_executor = tool_executor

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
        if execution.result is None:
            raise RuntimeError("agent execution ended without a result")
        return execution.result

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
        steps = 0
        tool_calls = 0
        latest_output = ""
        yield execution.emit(
            RunEventType.RUN_STARTED,
            agent=definition.name,
            max_steps=definition.max_steps,
            max_tool_calls=definition.max_tool_calls,
        )

        while steps < definition.max_steps:
            cancellation = context.cancellation
            if cancellation is not None and cancellation.cancelled:
                yield execution.finish(
                    StopReason.CANCELLED,
                    output=latest_output,
                    messages=messages,
                    steps=steps,
                    tool_calls=tool_calls,
                )
                return
            steps += 1
            definitions = self.tools.definitions(scope=context.scope)
            yield execution.emit(
                RunEventType.MODEL_STARTED,
                step=steps,
                tool_count=len(definitions),
            )
            request = ModelRequest(
                messages=tuple(messages),
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
                yield execution.finish(
                    StopReason.CANCELLED,
                    output=latest_output,
                    messages=messages,
                    steps=steps,
                    tool_calls=tool_calls,
                )
                return
            except ModelInvocationError as error:
                yield execution.emit(
                    RunEventType.MODEL_FAILED,
                    step=steps,
                    code=error.failure.code,
                    kind=error.failure.kind.value,
                )
                yield execution.finish(
                    StopReason.MODEL_ERROR,
                    output=latest_output,
                    messages=messages,
                    steps=steps,
                    tool_calls=tool_calls,
                )
                return

            response = invocation.response
            latest_output = response.text
            calls = tuple(
                block
                for block in response.blocks
                if isinstance(block, ToolCallContent)
            )
            if response.blocks:
                messages.append(ModelMessage(MessageRole.ASSISTANT, response.blocks))
            yield execution.emit(
                RunEventType.MODEL_COMPLETED,
                step=steps,
                provider=invocation.provider,
                model=invocation.model,
                finish_reason=response.finish_reason.value,
                text=latest_output,
                tool_call_ids=tuple(call.id for call in calls),
            )

            if not calls:
                yield execution.finish(
                    StopReason.COMPLETED,
                    output=latest_output,
                    messages=messages,
                    steps=steps,
                    tool_calls=tool_calls,
                )
                return

            for emitted_call in calls:
                if tool_calls >= definition.max_tool_calls:
                    yield execution.finish(
                        StopReason.MAX_TOOL_CALLS,
                        output=latest_output,
                        messages=messages,
                        steps=steps,
                        tool_calls=tool_calls,
                    )
                    return
                tool_calls += 1
                arguments, parse_error = _parse_arguments(emitted_call.arguments)
                call = ToolCall(
                    emitted_call.id,
                    emitted_call.name,
                    arguments,
                    scope=context.scope,
                )
                yield execution.emit(
                    RunEventType.TOOL_REQUESTED,
                    step=steps,
                    call_id=call.id,
                    name=call.name,
                    arguments=dict(call.arguments),
                )
                if parse_error is None:
                    tool_context = _tool_context(context)
                    result = await self.tool_executor.execute(call, tool_context)
                else:
                    result = None

                if result is not None and result.outcome == ToolOutcome.NEEDS_APPROVAL:
                    yield execution.emit(
                        RunEventType.TOOL_COMPLETED,
                        step=steps,
                        call_id=call.id,
                        name=call.name,
                        outcome=result.outcome.value,
                        failure_code=result.failure.code if result.failure else None,
                    )
                    yield execution.finish(
                        StopReason.NEEDS_APPROVAL,
                        output=latest_output,
                        messages=messages,
                        steps=steps,
                        tool_calls=tool_calls,
                        pending=call,
                    )
                    return

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
                messages.append(
                    ModelMessage(
                        MessageRole.TOOL,
                        (ToolResultContent(call.id, content, is_error),),
                        name=call.name,
                    )
                )
                yield execution.emit(
                    RunEventType.TOOL_COMPLETED,
                    step=steps,
                    call_id=call.id,
                    name=call.name,
                    outcome=outcome,
                    failure_code=failure_code,
                )
                if result is not None and result.outcome == ToolOutcome.CANCELLED:
                    yield execution.finish(
                        StopReason.CANCELLED,
                        output=latest_output,
                        messages=messages,
                        steps=steps,
                        tool_calls=tool_calls,
                    )
                    return

        yield execution.finish(
            StopReason.MAX_STEPS,
            output=latest_output,
            messages=messages,
            steps=steps,
            tool_calls=tool_calls,
        )


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
