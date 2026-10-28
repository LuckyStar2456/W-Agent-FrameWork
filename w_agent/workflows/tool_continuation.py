"""Opt-in, reference-first Workflow execution inside a resumable Agent tool."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from w_agent.kernel import ScopePath
from w_agent.models import ToolDefinition
from w_agent.tools import (
    ToolBinding, ToolContinuation, ToolContinuationError, ToolExecutionContext,
    ToolSideEffect,
)

from .adapters import WorkflowResultMapper, _workflow_result_data
from .persistence import WorkflowStore
from .types import (
    WorkflowCheckpoint, WorkflowCheckpointStatus, WorkflowContext,
    WorkflowDefinition, WorkflowEngineProtocol, WorkflowKind, WorkflowStopReason,
)

_KIND = "w-agent.workflow-tool"
_OWNER_KEY = "_w_agent_workflow_tool"


@dataclass(frozen=True, slots=True)
class WorkflowToolReference:
    """Host-owned linkage, not permission to execute either level's tools."""

    agent_run_id: str
    call_id: str
    tool_name: str
    workflow_run_id: str
    workflow_name: str
    workflow_version: str
    workflow_kind: WorkflowKind
    scope: ScopePath

    def __post_init__(self) -> None:
        for value in (
            self.agent_run_id, self.call_id, self.tool_name, self.workflow_run_id,
            self.workflow_name, self.workflow_version,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("workflow tool reference identity is required")
        if not isinstance(self.workflow_kind, WorkflowKind) or not isinstance(self.scope, ScopePath):
            raise ValueError("workflow tool reference kind and scope must be typed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id, "call_id": self.call_id,
            "tool_name": self.tool_name, "workflow_run_id": self.workflow_run_id,
            "workflow_name": self.workflow_name, "workflow_version": self.workflow_version,
            "workflow_kind": self.workflow_kind.value,
            "scope": [[part.kind, part.value] for part in self.scope],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowToolReference:
        if not isinstance(data, Mapping) or set(data) != {
            "agent_run_id", "call_id", "tool_name", "workflow_run_id",
            "workflow_name", "workflow_version", "workflow_kind", "scope",
        }:
            raise ToolContinuationError("invalid workflow tool reference")
        try:
            pairs = data["scope"]
            if not isinstance(pairs, list) or not all(
                isinstance(pair, list) and len(pair) == 2
                and all(isinstance(value, str) for value in pair) for pair in pairs
            ):
                raise ValueError("invalid scope")
            return cls(**{
                **data, "scope": ScopePath.from_pairs(pairs),
                "workflow_kind": WorkflowKind(data["workflow_kind"]),
            })
        except (TypeError, ValueError):
            raise ToolContinuationError("invalid workflow tool reference") from None


def _ticket(reference: WorkflowToolReference, sequence: int) -> ToolContinuation:
    # Zero means prepared but never started; positive values bind a paused boundary.
    return ToolContinuation(_KIND, {"reference": reference.to_dict(), "sequence": sequence})


def _read_ticket(ticket: ToolContinuation) -> tuple[WorkflowToolReference, int]:
    if (
        ticket.kind != _KIND or ticket.version != 1
        or set(ticket.payload) != {"reference", "sequence"}
        or type(ticket.payload["sequence"]) is not int
        or ticket.payload["sequence"] < 0
    ):
        raise ToolContinuationError("invalid workflow tool continuation")
    return WorkflowToolReference.from_dict(ticket.payload["reference"]), ticket.payload["sequence"]


async def _load_paused_child(
    store: WorkflowStore, reference: WorkflowToolReference,
) -> WorkflowCheckpoint:
    checkpoint = await store.load_checkpoint(reference.workflow_run_id)
    if (
        checkpoint is None or checkpoint.status is not WorkflowCheckpointStatus.PAUSED
        or checkpoint.run_id != reference.workflow_run_id
        or checkpoint.workflow_name != reference.workflow_name
        or checkpoint.workflow_version != reference.workflow_version
        or checkpoint.kind != reference.workflow_kind or checkpoint.scope != reference.scope
        or checkpoint.metadata.get(_OWNER_KEY) != reference.to_dict()
    ):
        raise ToolContinuationError("child checkpoint does not match workflow tool reference")
    return checkpoint


def resumable_workflow_tool(
    engine: WorkflowEngineProtocol,
    definition: WorkflowDefinition,
    store: WorkflowStore,
    *,
    name: str | None = None,
    description: str | None = None,
    required_permissions: frozenset[str] = frozenset({"workflow.execute"}),
    result_mapper: WorkflowResultMapper | None = None,
) -> ToolBinding:
    """Prepare a child reference, then start/resume it only through continuation.

    Supply the engine's exact store and use a durable parent ReAct RunStore for
    restart recovery. Scope and parent ID come from the runtime context, never
    model arguments. Child approval must be independently supplied through the
    Workflow's own node factories; no parent authority is forwarded.

    This is a trusted-local single-owner adapter, not a cross-store transaction.
    A stale/uncertain child or a crash between stores requires diagnosis, not
    automatic replay. Direct binding/executor calls do not claim a parent Run.
    """
    tool_name = name or f"run_{definition.name}"
    mapper = result_mapper or _workflow_result_data
    permissions = frozenset(required_permissions)
    if getattr(engine, "store", store) is not store:
        raise ValueError("workflow tool must use the engine's store")

    def reference_for(context: ToolExecutionContext, child_id: str) -> WorkflowToolReference:
        call = context.invocation
        if call is None or call.name != tool_name or context.agent_run_id is None:
            raise ToolContinuationError("workflow tool requires runtime invocation identity")
        return WorkflowToolReference(
            context.agent_run_id, call.id, call.name, child_id,
            definition.name, definition.version, definition.kind, call.scope,
        )

    async def prepare(arguments: Mapping[str, Any], context: ToolExecutionContext) -> ToolContinuation:
        # No engine call or child state write before the parent persists this ticket.
        return _ticket(reference_for(context, f"workflow-{uuid4().hex}"), 0)

    async def resume(
        arguments: Mapping[str, Any], ticket: ToolContinuation, context: ToolExecutionContext,
    ) -> Any:
        reference, sequence = _read_ticket(ticket)
        if reference != reference_for(context, reference.workflow_run_id):
            raise ToolContinuationError("workflow tool continuation belongs to another invocation")
        if reference.call_id not in context.approved_call_ids or not permissions <= context.permissions:
            raise ToolContinuationError("workflow tool continuation requires explicit authority")
        if sequence == 0:
            if (
                await store.load_checkpoint(reference.workflow_run_id) is not None
                or await store.events(reference.workflow_run_id)
            ):
                raise ToolContinuationError("prepared child already has execution state")
            result = await engine.start(definition, WorkflowContext(
                reference.workflow_run_id, input=arguments.get("input"),
                state=arguments.get("state", {}), scope=reference.scope,
                cancellation=context.cancellation,
                metadata={_OWNER_KEY: reference.to_dict()},
            ))
        else:
            await _load_paused_child(store, reference)
            events = await store.events(reference.workflow_run_id)
            if not events or events[-1].sequence != sequence:
                raise ToolContinuationError("workflow tool continuation boundary is stale")
            result = await engine.resume(
                definition, reference.workflow_run_id, cancellation=context.cancellation,
            )
        if result.run_id != reference.workflow_run_id:
            raise ToolContinuationError("workflow engine returned another child run")
        if result.stop_reason is WorkflowStopReason.PAUSED:
            await _load_paused_child(store, reference)
            events = await store.events(reference.workflow_run_id)
            if result.checkpoint_id != reference.workflow_run_id or not events or events[-1].sequence <= sequence:
                raise ToolContinuationError("workflow pause did not persist a new boundary")
            return _ticket(reference, events[-1].sequence)
        if result.stop_reason is not WorkflowStopReason.COMPLETED:
            raise ToolContinuationError("child workflow did not complete safely")
        if result.checkpoint_id is not None or await store.load_checkpoint(reference.workflow_run_id) is not None:
            raise ToolContinuationError("completed child still has a pending checkpoint")
        return mapper(result)

    return ToolBinding(
        ToolDefinition(tool_name, description or f"Prepare and continue workflow {definition.name!r}.", {
            "type": "object", "properties": {"input": {}, "state": {"type": "object"}},
            "additionalProperties": False,
        }), prepare, side_effect=ToolSideEffect.WRITE,
        required_permissions=permissions, resume_handler=resume,
        metadata={"adapter": "workflow-continuation", "workflow": definition.name, "version": definition.version},
    )
