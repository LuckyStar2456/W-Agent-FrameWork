"""Opt-in Agent approval continuation inside a suspended Workflow node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any
from uuid import uuid4

from w_agent.agents import (
    AgentDefinition, CheckpointStatus, ResumableAgentLoop, RunContext, RunResult,
    RunStore, StopReason,
)
from w_agent.tools import ToolExecutionContext

from .adapters import (
    AgentMessageFactory, AgentResultMapper, AgentToolContextFactory,
    AgentWorkflowAdapterError, _agent_result_data, _empty_tool_context, _input_messages,
)
from .types import WorkflowNode, WorkflowNodeContext, WorkflowNodeResult


@dataclass(frozen=True, slots=True)
class AgentWorkflowApproval:
    """Reference only: no arguments, messages, credentials, or grants."""

    workflow_run_id: str
    workflow_node: str
    agent_run_id: str
    agent_name: str
    call_id: str
    tool_name: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Agent/Workflow approval reference version")
        for field in (
            self.workflow_run_id, self.workflow_node, self.agent_run_id,
            self.agent_name, self.call_id, self.tool_name,
        ):
            if not isinstance(field, str) or not field.strip():
                raise ValueError("Agent/Workflow approval identity must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AgentWorkflowApproval:
        if not isinstance(value, Mapping) or set(value) != {
            "workflow_run_id", "workflow_node", "agent_run_id", "agent_name",
            "call_id", "tool_name", "schema_version",
        }:
            raise AgentWorkflowAdapterError("invalid Agent/Workflow approval reference")
        try:
            return cls(**value)
        except (ValueError, TypeError):
            raise AgentWorkflowAdapterError("invalid Agent/Workflow approval reference") from None


AgentApprovalContextFactory = Callable[
    [WorkflowNodeContext, AgentWorkflowApproval], ToolExecutionContext
]


def approval_agent_workflow_node(
    name: str,
    loop: ResumableAgentLoop,
    definition: AgentDefinition,
    store: RunStore,
    *,
    messages: AgentMessageFactory | None = None,
    tool_context: AgentToolContextFactory | None = None,
    approval_context: AgentApprovalContextFactory | None = None,
    result_mapper: AgentResultMapper | None = None,
    state_key: str | None = None,
) -> WorkflowNode:
    """Suspend on approval and continue the exact child run on explicit grant.

    The supplied store must be the loop's store. Every resume verifies the link,
    pending call, scope and complete AgentDefinition before requesting fresh
    host authority. Only the referenced call ID is forwarded as approved.
    Without that exact grant, neither the child loop nor a model/tool is run.

    This is not a transaction spanning the two stores. A crash or failed batch
    keeps the parent RESUMING and requires diagnosis, never automatic replay.
    Keep the selected state key reserved for this node across definition versions.
    """

    if not callable(getattr(loop, "resume", None)):
        raise ValueError("approval adapter requires a resumable Agent loop")
    key = state_key if state_key is not None else f"_w_agent_approval:{name}"
    if not isinstance(key, str) or not key.strip():
        raise ValueError("approval state key must not be empty")
    message_factory = messages or _input_messages
    context_factory = tool_context or _empty_tool_context
    mapper = result_mapper or _agent_result_data

    def suspend(reference: AgentWorkflowApproval) -> WorkflowNodeResult:
        return WorkflowNodeResult(
            state_updates={key: reference.to_dict()}, pause=True, suspend=True
        )

    async def validate_pending(
        reference: AgentWorkflowApproval, context: WorkflowNodeContext
    ) -> None:
        if (
            reference.workflow_run_id != context.run_id
            or reference.workflow_node != context.node
            or reference.agent_name != definition.name
        ):
            raise AgentWorkflowAdapterError("approval reference belongs to another node")
        checkpoint = await store.load_checkpoint(reference.agent_run_id)
        if (
            checkpoint is None
            or checkpoint.run_id != reference.agent_run_id
            or checkpoint.status is not CheckpointStatus.PENDING_APPROVAL
            or checkpoint.definition != definition
            or checkpoint.scope != context.scope
            or checkpoint.pending_tool_call is None
            or checkpoint.pending_tool_call.id != reference.call_id
            or checkpoint.pending_tool_call.name != reference.tool_name
        ):
            raise AgentWorkflowAdapterError("Agent approval checkpoint does not match reference")

    async def handler(context: WorkflowNodeContext) -> WorkflowNodeResult:
        saved = context.state.get(key)
        if saved is not None:
            reference = AgentWorkflowApproval.from_dict(saved)
            await validate_pending(reference, context)
            authority = (
                approval_context(context, reference)
                if approval_context is not None else _empty_tool_context(context)
            )
            if not isinstance(authority, ToolExecutionContext):
                raise AgentWorkflowAdapterError("approval factory must return ToolExecutionContext")
            if reference.call_id not in authority.approved_call_ids:
                return suspend(reference)
            # The host's approval cannot silently authorize later queued calls.
            authority = replace(
                authority, approved_call_ids=frozenset({reference.call_id}),
                cancellation=(
                    context.cancellation
                    if context.cancellation is not None else authority.cancellation
                ),
            )
            agent_run_id = reference.agent_run_id
            result = await loop.resume(
                agent_run_id, tool_context=authority, cancellation=context.cancellation
            )
        else:
            agent_run_id = f"agent-{uuid4().hex}"
            result = await loop.run(
                definition,
                RunContext(
                    agent_run_id, message_factory(context), scope=context.scope,
                    cancellation=context.cancellation, tool_context=context_factory(context),
                    metadata={**dict(context.metadata), "workflow_run_id": context.run_id,
                              "workflow_node": context.node},
                ),
            )
        if not isinstance(result, RunResult) or result.run_id != agent_run_id:
            raise AgentWorkflowAdapterError("Agent returned an unexpected run identity")
        if result.stop_reason is StopReason.NEEDS_APPROVAL:
            if result.checkpoint_id != agent_run_id or result.pending_tool_call is None:
                raise AgentWorkflowAdapterError("Agent approval result has no exact checkpoint")
            reference = AgentWorkflowApproval(
                context.run_id, context.node, agent_run_id, definition.name,
                result.pending_tool_call.id, result.pending_tool_call.name,
            )
            await validate_pending(reference, context)
            return suspend(reference)
        if result.stop_reason is not StopReason.COMPLETED:
            raise AgentWorkflowAdapterError("Agent did not complete or reach an approval boundary")
        if (
            result.checkpoint_id is not None or result.pending_tool_call is not None
            or await store.load_checkpoint(agent_run_id) is not None
        ):
            raise AgentWorkflowAdapterError("completed Agent still has a pending checkpoint")
        return WorkflowNodeResult(output=mapper(result), state_updates={key: None})

    return WorkflowNode(name, handler)
