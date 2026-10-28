"""Explicit two-layer approval for Agent -> Workflow -> Agent tool chains."""

from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from w_agent.agents import (
    AgentDefinition, CheckpointStatus, ResumableAgentLoop, RunCheckpoint,
    RunResult, RunStore,
)
from w_agent.agents.persistence import _checkpoint_to_data as _agent_data
from w_agent.models import CancellationToken
from w_agent.tools import ToolContinuationError, ToolExecutionContext

from .approval_review import (
    WorkflowApprovalGrants, WorkflowApprovalLinkStatus, WorkflowApprovalReview,
    review_workflow_approvals,
)
from .persistence import WorkflowStore, _checkpoint_to_data as _workflow_data
from .tool_continuation import WorkflowToolReference, _load_paused_child, _read_ticket
from .types import WorkflowCheckpoint


class WorkflowToolApprovalError(RuntimeError):
    """A selected two-layer approval chain is stale or cannot be resumed safely."""


@dataclass(frozen=True, slots=True)
class WorkflowToolApprovalReview:
    """A boundary-specific reference snapshot; matching grants no authority."""

    parent: WorkflowToolReference
    sequence: int
    child: WorkflowApprovalReview

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parent, WorkflowToolReference)
            or not isinstance(self.child, WorkflowApprovalReview)
            or type(self.sequence) is not int or self.sequence <= 0
        ):
            raise ValueError("two-layer review requires typed references and a positive sequence")

    def to_dict(self) -> dict[str, Any]:
        parent = self.parent.to_dict()
        parent.pop("scope")
        return {
            "parent": parent, "sequence": self.sequence,
            "child": self.child.to_dict(), "authorized": False,
        }


async def _inspect(
    parent_store: RunStore, workflow_store: WorkflowStore, child_store: RunStore,
    parent_run_id: str, keys: tuple[str, ...] | None,
) -> tuple[RunCheckpoint, WorkflowCheckpoint, tuple[WorkflowToolApprovalReview, ...]]:
    parent = await parent_store.load_checkpoint(parent_run_id)
    if (
        parent is None or parent.run_id != parent_run_id
        or parent.status is not CheckpointStatus.PENDING_APPROVAL
        or parent.tool_continuation is None or parent.pending_tool_call is None
    ):
        raise WorkflowToolApprovalError("parent has no pending workflow continuation")
    try:
        reference, sequence = _read_ticket(parent.tool_continuation)
        call = parent.pending_tool_call
        if (
            sequence == 0 or reference.agent_run_id != parent_run_id
            or reference.call_id != call.id or reference.tool_name != call.name
            or reference.scope != parent.scope or call.scope != parent.scope
        ):
            raise WorkflowToolApprovalError("parent continuation does not match invocation")
        workflow = await _load_paused_child(workflow_store, reference)
    except ToolContinuationError:
        raise WorkflowToolApprovalError("workflow continuation reference is invalid") from None
    events = await workflow_store.events(reference.workflow_run_id)
    if not events or events[-1].sequence != sequence:
        raise WorkflowToolApprovalError("workflow continuation boundary is stale")
    children = await review_workflow_approvals(
        workflow_store, child_store, reference.workflow_run_id, state_keys=keys,
    )
    return parent, workflow, tuple(
        WorkflowToolApprovalReview(reference, sequence, child) for child in children
    )


def _keys(state_keys: Sequence[str] | None) -> tuple[str, ...] | None:
    if state_keys is None:
        return None
    if isinstance(state_keys, (str, bytes)) or not isinstance(state_keys, Sequence) or any(
        not isinstance(key, str) or not key.strip() for key in state_keys
    ):
        raise ValueError("state keys must be a sequence of nonempty strings")
    return tuple(state_keys)


async def review_workflow_tool_approvals(
    parent_store: RunStore, workflow_store: WorkflowStore, child_store: RunStore,
    parent_run_id: str, *, state_keys: Sequence[str] | None = None,
) -> tuple[WorkflowToolApprovalReview, ...]:
    """Read a waiting chain without importing code, executing, or granting.

    Missing/uncertain/stale outer chains raise; inner link statuses are returned
    for inspection. Empty output means no inner approval, not successful work.
    The JSON projection omits scope, prompts, arguments, state and output values.
    """
    _, _, reviews = await _inspect(
        parent_store, workflow_store, child_store, parent_run_id, _keys(state_keys),
    )
    return reviews


@dataclass(frozen=True, slots=True)
class WorkflowToolApprovalAssemblyContext:
    selection: WorkflowToolApprovalReview
    parent_definition: AgentDefinition
    child_definition: AgentDefinition
    parent_store: RunStore
    workflow_store: WorkflowStore
    child_store: RunStore
    grants: WorkflowApprovalGrants


WorkflowToolApprovalFactory = Callable[
    [WorkflowToolApprovalAssemblyContext], AbstractAsyncContextManager[ResumableAgentLoop]
]


@asynccontextmanager
async def open_workflow_tool_approval_entry(
    entry: str, context: WorkflowToolApprovalAssemblyContext,
) -> AsyncIterator[ResumableAgentLoop]:
    """Load a separately authorized trusted-Python factory upon context entry."""
    if not isinstance(entry, str) or entry.count(":") != 1:
        raise WorkflowToolApprovalError("factory must use module:attribute syntax")
    module, attribute = entry.split(":", 1)
    if not module.strip() or not attribute.strip():
        raise WorkflowToolApprovalError("factory module and attribute are required")
    try:
        factory = getattr(importlib.import_module(module), attribute)
    except Exception:
        raise WorkflowToolApprovalError("factory could not be imported") from None
    if not callable(factory):
        raise WorkflowToolApprovalError("factory must be callable")
    async with factory(context) as loop:
        yield loop


def _permissions(values: Collection[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("permissions must be a collection of names")
    result = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError("permission names must be nonempty strings")
    return result


async def resume_workflow_tool_approval(
    parent_store: RunStore, workflow_store: WorkflowStore, child_store: RunStore,
    selection: WorkflowToolApprovalReview, factory: WorkflowToolApprovalFactory,
    *, parent_permissions: Collection[str] = frozenset(),
    child_permissions: Collection[str] = frozenset(),
    state_keys: Sequence[str] | None = None,
    cancellation: CancellationToken | None = None,
) -> RunResult:
    """Explicitly approve one outer call and one selected inner call.

    Invocation is host authorization for both calls and parent continuation,
    including subsequent model/node work. Permissions remain independent.
    The factory must assemble the supplied stores, exact definitions and grants
    into the resumable parent loop. It owns/closes its clients. No child loop or
    middle Workflow is resumed directly here; parent claims precede effects.

    Snapshots detect assembly-time changes, not concurrent ownership or atomic
    commits across stores. Trusted local single-owner execution is required.
    A returned paused result does not prove the selected inner tool executed.
    """
    if not isinstance(selection, WorkflowToolApprovalReview) or not callable(factory):
        raise ValueError("two-layer approval requires a typed selection and factory")
    outer_permissions = _permissions(parent_permissions)
    inner_permissions = _permissions(child_permissions)
    keys = _keys(state_keys)

    async def capture() -> tuple[RunCheckpoint, RunCheckpoint, str]:
        parent, workflow, reviews = await _inspect(
            parent_store, workflow_store, child_store, selection.parent.agent_run_id, keys,
        )
        if reviews.count(selection) != 1 or selection.child.link_status is not WorkflowApprovalLinkStatus.MATCHED:
            raise WorkflowToolApprovalError("selected two-layer approval is absent or stale")
        child = await child_store.load_checkpoint(selection.child.reference.agent_run_id)
        reference = selection.child.reference
        if (
            child is None or child.run_id != reference.agent_run_id
            or child.status is not CheckpointStatus.PENDING_APPROVAL
            or child.definition.name != reference.agent_name
            or child.scope != selection.parent.scope or child.pending_tool_call is None
            or child.pending_tool_call.id != reference.call_id
            or child.pending_tool_call.name != reference.tool_name
            or child.pending_tool_call.scope != selection.parent.scope
        ):
            raise WorkflowToolApprovalError("selected child checkpoint changed or mismatched")
        # Value snapshots, not borrowed shallow dataclasses: trusted factory code
        # may mutate nested input/argument dictionaries in an in-memory store.
        snapshot = json.dumps(
            [_agent_data(parent), _workflow_data(workflow), _agent_data(child)],
            sort_keys=True, ensure_ascii=False,
        )
        return parent, child, snapshot

    parent, child, before = await capture()  # No factory/import before preflight.
    grants = WorkflowApprovalGrants()
    context = WorkflowToolApprovalAssemblyContext(
        selection, parent.definition, child.definition,
        parent_store, workflow_store, child_store, grants,
    )
    result = None
    try:
        async with factory(context) as loop:
            try:
                if not callable(getattr(loop, "resume", None)) or getattr(loop, "store", parent_store) is not parent_store:
                    raise WorkflowToolApprovalError("factory must yield a parent loop using the supplied store")
                _, _, after = await capture()
                if after != before:
                    raise WorkflowToolApprovalError("approval checkpoints changed; review again")
                grants.clear()
                grants.grant(selection.child.reference, scope=selection.parent.scope, permissions=inner_permissions)
                resumed = await loop.resume(
                    selection.parent.agent_run_id,
                    tool_context=ToolExecutionContext(
                        permissions=outer_permissions,
                        approved_call_ids={selection.parent.call_id}, cancellation=cancellation,
                    ), cancellation=cancellation,
                )
                if not isinstance(resumed, RunResult) or resumed.run_id != selection.parent.agent_run_id:
                    raise WorkflowToolApprovalError("parent loop returned an invalid result")
                result = resumed
            finally:
                grants.clear()
    finally:
        grants.clear()
    if result is None:
        raise WorkflowToolApprovalError("factory suppressed recovery without a result")
    return result
