"""Policy-enforced tool execution with bounded time and prompt-free audit."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any, Mapping

from w_agent.kernel import CapabilityNotFoundError

from .policies import default_tool_policy
from .registry import ToolRegistry
from .types import (
    ToolAuditRecord,
    ToolAuditSink,
    ToolBinding,
    ToolCall,
    ToolExecutionContext,
    ToolFailure,
    ToolOutcome,
    ToolPolicy,
    ToolPolicyAction,
    ToolResult,
)


class InMemoryToolAuditSink:
    """Small local audit sink useful for development and tests."""

    def __init__(self) -> None:
        self.records: list[ToolAuditRecord] = []

    async def record(self, entry: ToolAuditRecord) -> None:
        self.records.append(entry)


class ToolExecutor:
    """Resolve, validate, authorize, execute, and audit one tool call."""

    def __init__(
        self,
        tools: ToolRegistry,
        *,
        policy: ToolPolicy | None = None,
        audit: ToolAuditSink | None = None,
        timeout: float = 30,
    ) -> None:
        if timeout <= 0:
            raise ValueError("tool timeout must be positive")
        self.tools = tools
        self.policy = policy or default_tool_policy()
        self.audit = audit or InMemoryToolAuditSink()
        self.timeout = timeout

    async def execute(
        self,
        call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        context = context or ToolExecutionContext()
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        binding: ToolBinding | None = None
        result: ToolResult
        try:
            binding = self.tools.binding(call.name, scope=call.scope)
        except CapabilityNotFoundError:
            result = _failure_result(
                call,
                ToolOutcome.FAILED,
                "tool-not-found",
                f"tool {call.name!r} is not registered in scope {call.scope}",
            )
        else:
            error = validate_tool_arguments(
                binding.definition.input_schema,
                call.arguments,
            )
            if error is not None:
                result = _failure_result(
                    call,
                    ToolOutcome.FAILED,
                    "invalid-tool-arguments",
                    error,
                )
            elif context.cancellation is not None and context.cancellation.cancelled:
                result = _failure_result(
                    call,
                    ToolOutcome.CANCELLED,
                    "tool-cancelled",
                    "tool execution was cancelled before it started",
                )
            else:
                try:
                    decision = await self.policy.evaluate(binding, call, context)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    result = _failure_result(
                        call,
                        ToolOutcome.FAILED,
                        "tool-policy-failed",
                        f"tool policy raised {type(error).__name__}",
                    )
                else:
                    result = await self._execute_decision(
                        binding,
                        call,
                        context,
                        decision,
                    )

        await self._record(call, binding, result, started_at, started)
        return result

    async def _execute_decision(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
        decision,
    ) -> ToolResult:
        if decision.action == ToolPolicyAction.DENY:
            return ToolResult(
                call.id,
                call.name,
                ToolOutcome.DENIED,
                failure=ToolFailure("tool-denied", decision.reason),
                policy_decision=decision,
            )
        if decision.action == ToolPolicyAction.REQUIRE_APPROVAL:
            return ToolResult(
                call.id,
                call.name,
                ToolOutcome.NEEDS_APPROVAL,
                failure=ToolFailure("tool-needs-approval", decision.reason),
                policy_decision=decision,
            )
        return await self._invoke(binding, call, context, decision)

    async def _invoke(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
        decision,
    ) -> ToolResult:
        handler_task = asyncio.create_task(binding.handler(call.arguments, context))
        cancellation_task: asyncio.Task[None] | None = None
        if context.cancellation is not None:
            cancellation_task = asyncio.create_task(context.cancellation.wait())
        try:
            async with asyncio.timeout(self.timeout):
                if cancellation_task is None:
                    value = await handler_task
                else:
                    done, _ = await asyncio.wait(
                        (handler_task, cancellation_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancellation_task in done:
                        handler_task.cancel()
                        await _drain_cancelled(handler_task)
                        return _failure_result(
                            call,
                            ToolOutcome.CANCELLED,
                            "tool-cancelled",
                            "tool execution was cancelled",
                            policy_decision=decision,
                        )
                    value = await handler_task
        except TimeoutError:
            handler_task.cancel()
            await _drain_cancelled(handler_task)
            return _failure_result(
                call,
                ToolOutcome.TIMED_OUT,
                "tool-timeout",
                "tool execution timed out",
                policy_decision=decision,
            )
        except asyncio.CancelledError:
            handler_task.cancel()
            await _drain_cancelled(handler_task)
            raise
        except Exception as error:
            return _failure_result(
                call,
                ToolOutcome.FAILED,
                "tool-execution-failed",
                f"tool raised {type(error).__name__}",
                policy_decision=decision,
            )
        finally:
            if cancellation_task is not None:
                cancellation_task.cancel()
                await _drain_cancelled(cancellation_task)

        return ToolResult(
            call.id,
            call.name,
            ToolOutcome.SUCCEEDED,
            content=_serialize_tool_output(value),
            data=value,
            policy_decision=decision,
        )

    async def _record(
        self,
        call: ToolCall,
        binding: ToolBinding | None,
        result: ToolResult,
        started_at: datetime,
        started: float,
    ) -> None:
        completed_at = datetime.now(UTC)
        await self.audit.record(
            ToolAuditRecord(
                call_id=call.id,
                tool_name=call.name,
                side_effect=binding.side_effect if binding is not None else None,
                argument_keys=tuple(sorted(call.arguments)),
                outcome=result.outcome,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                failure_code=(
                    result.failure.code if result.failure is not None else None
                ),
                policy=(
                    result.policy_decision.policy
                    if result.policy_decision is not None
                    else None
                ),
            )
        )


async def _drain_cancelled(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


def _failure_result(
    call: ToolCall,
    outcome: ToolOutcome,
    code: str,
    message: str,
    *,
    policy_decision=None,
) -> ToolResult:
    return ToolResult(
        call.id,
        call.name,
        outcome,
        failure=ToolFailure(code, message),
        policy_decision=policy_decision,
    )


def _serialize_tool_output(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def validate_tool_arguments(
    schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> str | None:
    """Validate the deterministic JSON-Schema subset used by built-in tools."""

    if schema.get("type", "object") != "object":
        return "top-level tool schema must have type 'object'"
    required = schema.get("required", ())
    missing = [name for name in required if name not in arguments]
    if missing:
        return f"missing required arguments: {', '.join(sorted(missing))}"
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return "tool schema properties must be an object"
    if schema.get("additionalProperties") is False:
        unknown = set(arguments) - set(properties)
        if unknown:
            return f"unknown arguments: {', '.join(sorted(unknown))}"
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            continue
        expected = property_schema.get("type")
        if expected is not None and not _matches_json_type(value, expected):
            return f"argument {name!r} must be {expected}"
        if "enum" in property_schema and value not in property_schema["enum"]:
            return f"argument {name!r} is not an allowed value"
    return None


def _matches_json_type(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_matches_json_type(value, item) for item in expected)
    checks = {
        "null": lambda item: item is None,
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float))
        and not isinstance(item, bool),
        "string": lambda item: isinstance(item, str),
        "array": lambda item: isinstance(item, (list, tuple)),
        "object": lambda item: isinstance(item, Mapping),
    }
    check = checks.get(expected)
    return False if check is None else check(value)
