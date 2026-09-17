"""Convenience adapters between public agent and workflow contracts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import uuid4

from w_agent.agents import AgentDefinition, AgentLoop, RunContext, RunResult, StopReason
from w_agent.kernel import ScopePath
from w_agent.models import MessageRole, ModelMessage, ToolDefinition
from w_agent.tools import (
    ToolBinding,
    ToolExecutionContext,
    ToolSideEffect,
)

from .types import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEngineProtocol,
    WorkflowNode,
    WorkflowNodeContext,
    WorkflowResult,
)

AgentMessageFactory = Callable[[WorkflowNodeContext], tuple[ModelMessage, ...]]
AgentToolContextFactory = Callable[[WorkflowNodeContext], ToolExecutionContext]
AgentResultMapper = Callable[[RunResult], Any]
WorkflowResultMapper = Callable[[WorkflowResult], Any]


class AgentWorkflowAdapterError(RuntimeError):
    """An adapted agent stopped outside the caller-approved terminal set."""


def agent_workflow_node(
    name: str,
    loop: AgentLoop,
    definition: AgentDefinition,
    *,
    messages: AgentMessageFactory | None = None,
    tool_context: AgentToolContextFactory | None = None,
    result_mapper: AgentResultMapper | None = None,
    accepted_stop_reasons: frozenset[StopReason] = frozenset(
        {StopReason.COMPLETED}
    ),
) -> WorkflowNode:
    """Adapt one agent run into a workflow node.

    The default accepts completed agent runs only. Callers must explicitly add
    other stop reasons before approval checkpoints or budget stops can become a
    normal workflow-node output.
    """

    if not accepted_stop_reasons:
        raise ValueError("accepted agent stop reasons must not be empty")
    message_factory = messages or _input_messages
    context_factory = tool_context or _empty_tool_context
    mapper = result_mapper or _agent_result_data

    async def handler(context: WorkflowNodeContext) -> Any:
        agent_run_id = (
            f"agent-{_safe_fragment(context.run_id)}-"
            f"{_safe_fragment(context.node)}-{uuid4().hex}"
        )
        result = await loop.run(
            definition,
            RunContext(
                agent_run_id,
                message_factory(context),
                scope=context.scope,
                cancellation=context.cancellation,
                tool_context=context_factory(context),
                metadata={
                    **dict(context.metadata),
                    "workflow_run_id": context.run_id,
                    "workflow_node": context.node,
                },
            ),
        )
        if result.stop_reason not in accepted_stop_reasons:
            raise AgentWorkflowAdapterError(
                f"agent stopped with {result.stop_reason.value}"
            )
        return mapper(result)

    return WorkflowNode(name, handler)


def workflow_start_tool(
    engine: WorkflowEngineProtocol,
    definition: WorkflowDefinition,
    *,
    name: str | None = None,
    description: str | None = None,
    scope: ScopePath | None = None,
    side_effect: ToolSideEffect = ToolSideEffect.WRITE,
    required_permissions: frozenset[str] = frozenset({"workflow.execute"}),
    result_mapper: WorkflowResultMapper | None = None,
) -> ToolBinding:
    """Expose starting one fixed workflow definition as a governed tool."""

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        run_id = f"workflow-{uuid4().hex}"
        result = await engine.start(
            definition,
            WorkflowContext(
                run_id,
                input=arguments.get("input"),
                state=arguments.get("state", {}),
                scope=scope or ScopePath.application(),
                cancellation=context.cancellation,
                metadata={"started_by": "agent-tool"},
            ),
        )
        return (result_mapper or _workflow_result_data)(result)

    return ToolBinding(
        ToolDefinition(
            name or f"run_{definition.name}",
            description or f"Run workflow {definition.name!r}.",
            {
                "type": "object",
                "properties": {
                    "input": {},
                    "state": {"type": "object"},
                },
                "additionalProperties": False,
            },
        ),
        handler,
        side_effect=side_effect,
        required_permissions=required_permissions,
        metadata={
            "adapter": "workflow-start",
            "workflow": definition.name,
            "version": definition.version,
        },
    )


def workflow_resume_tool(
    engine: WorkflowEngineProtocol,
    definition: WorkflowDefinition,
    *,
    name: str | None = None,
    description: str | None = None,
    side_effect: ToolSideEffect = ToolSideEffect.WRITE,
    required_permissions: frozenset[str] = frozenset({"workflow.execute"}),
    result_mapper: WorkflowResultMapper | None = None,
) -> ToolBinding:
    """Expose resume for one fixed workflow definition as a governed tool."""

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        result = await engine.resume(
            definition,
            arguments["run_id"],
            cancellation=context.cancellation,
        )
        return (result_mapper or _workflow_result_data)(result)

    return ToolBinding(
        ToolDefinition(
            name or f"resume_{definition.name}",
            description or f"Resume workflow {definition.name!r}.",
            {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ),
        handler,
        side_effect=side_effect,
        required_permissions=required_permissions,
        metadata={
            "adapter": "workflow-resume",
            "workflow": definition.name,
            "version": definition.version,
        },
    )


def _input_messages(context: WorkflowNodeContext) -> tuple[ModelMessage, ...]:
    value = context.input
    if isinstance(value, ModelMessage):
        return (value,)
    if (
        isinstance(value, tuple)
        and value
        and all(isinstance(item, ModelMessage) for item in value)
    ):
        return value
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    return (ModelMessage.text(MessageRole.USER, text),)


def _empty_tool_context(context: WorkflowNodeContext) -> ToolExecutionContext:
    return ToolExecutionContext(cancellation=context.cancellation)


def _agent_result_data(result: RunResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "stop_reason": result.stop_reason.value,
        "output": result.output,
        "steps": result.steps,
        "tool_calls": result.tool_calls,
        "checkpoint_id": result.checkpoint_id,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
            "cached_input_tokens": result.usage.cached_input_tokens,
            "complete": result.usage_complete,
        },
    }


def _workflow_result_data(result: WorkflowResult) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "stop_reason": result.stop_reason.value,
        "output": result.output,
        "completed_nodes": list(result.completed_nodes),
        "checkpoint_id": result.checkpoint_id,
        "failure": result.failure,
    }


def _safe_fragment(value: str) -> str:
    sanitized = "".join(
        character if character.isalnum() or character in "_.-" else "-"
        for character in value
    ).strip(".-")
    return sanitized[:48] or "run"
