"""Read-only approval linkage review and application-owned one-shot grants."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Any

from w_agent.agents import CheckpointStatus, RunStore
from w_agent.kernel import ScopePath
from w_agent.tools import ToolExecutionContext

from .adapters import AgentWorkflowAdapterError
from .approval import AgentWorkflowApproval
from .persistence import WorkflowStore, WorkflowStoreError
from .types import WorkflowCheckpointStatus, WorkflowKind, WorkflowNodeContext


class WorkflowApprovalLinkStatus(StrEnum):
    MATCHED = "matched"
    PARENT_NOT_PAUSED = "parent-not-paused"
    PARENT_UNCERTAIN = "parent-uncertain"
    REFERENCE_MISMATCH = "reference-mismatch"
    CHILD_MISSING = "child-missing"
    CHILD_NOT_PENDING = "child-not-pending"
    CHILD_MISMATCH = "child-mismatch"


@dataclass(frozen=True, slots=True)
class WorkflowApprovalReview:
    """Identifier/status snapshot, never execution authority or an atomic view."""

    reference: AgentWorkflowApproval
    parent_status: WorkflowCheckpointStatus
    child_status: CheckpointStatus | None
    link_status: WorkflowApprovalLinkStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference.to_dict(),
            "parent_status": self.parent_status.value,
            "child_status": self.child_status.value if self.child_status else None,
            "link_status": self.link_status.value,
            "authorized": False,
        }


async def review_workflow_approvals(
    workflow_store: WorkflowStore,
    agent_store: RunStore,
    run_id: str,
    *,
    state_keys: Sequence[str] | None = None,
) -> tuple[WorkflowApprovalReview, ...]:
    """Inspect one selected parent without importing code or executing a child.

    Default discovery examines only the adapter's reserved top-level key prefix.
    Custom keys must be supplied explicitly. Malformed/duplicate references fail
    closed. A matched snapshot validates stored identities and scope, not a new
    executable definition, tool arguments, or permission. Resume revalidates.
    """

    parent = await workflow_store.load_checkpoint(run_id)
    if parent is None:
        raise WorkflowStoreError("workflow run has no checkpoint to review")
    if parent.run_id != run_id:
        raise WorkflowStoreError("workflow store returned a different run")
    if state_keys is None:
        keys = tuple(sorted(
            key for key in parent.state
            if isinstance(key, str) and key.startswith("_w_agent_approval:")
        ))
    else:
        if not isinstance(state_keys, Sequence) or isinstance(state_keys, (str, bytes)) or any(
            not isinstance(key, str) or not key.strip() for key in state_keys
        ):
            raise ValueError("approval state keys must be a sequence of nonempty strings")
        keys = tuple(sorted(set(state_keys)))

    reviews: list[WorkflowApprovalReview] = []
    seen_children: set[str] = set()
    for key in keys:
        if key not in parent.state:
            raise AgentWorkflowAdapterError("selected approval state key is absent")
        value = parent.state[key]
        if value is None:
            continue
        reference = AgentWorkflowApproval.from_dict(value)
        if reference.agent_run_id in seen_children:
            raise AgentWorkflowAdapterError("duplicate child approval reference")
        seen_children.add(reference.agent_run_id)
        active_nodes = (
            parent.remaining_nodes if parent.kind is WorkflowKind.DAG
            else (parent.current_node,)
        )
        child_status = None
        if parent.status is WorkflowCheckpointStatus.RESUMING:
            status = WorkflowApprovalLinkStatus.PARENT_UNCERTAIN
        elif parent.status is not WorkflowCheckpointStatus.PAUSED:
            status = WorkflowApprovalLinkStatus.PARENT_NOT_PAUSED
        elif reference.workflow_run_id != run_id or reference.workflow_node not in active_nodes:
            status = WorkflowApprovalLinkStatus.REFERENCE_MISMATCH
        else:
            child = await agent_store.load_checkpoint(reference.agent_run_id)
            if child is None:
                status = WorkflowApprovalLinkStatus.CHILD_MISSING
            else:
                child_status = child.status
                if child.status is not CheckpointStatus.PENDING_APPROVAL:
                    status = WorkflowApprovalLinkStatus.CHILD_NOT_PENDING
                elif (
                    child.run_id != reference.agent_run_id
                    or child.definition.name != reference.agent_name
                    or child.scope != parent.scope
                    or child.pending_tool_call is None
                    or child.pending_tool_call.id != reference.call_id
                    or child.pending_tool_call.name != reference.tool_name
                ):
                    status = WorkflowApprovalLinkStatus.CHILD_MISMATCH
                else:
                    status = WorkflowApprovalLinkStatus.MATCHED
        reviews.append(WorkflowApprovalReview(reference, parent.status, child_status, status))
    return tuple(reviews)


@dataclass(frozen=True, slots=True)
class _Grant:
    scope: ScopePath
    permissions: frozenset[str]
    expires_at: float


class WorkflowApprovalGrants:
    """One-shot, expiring authority callback for a single host-owned workspace.

    Inject this object explicitly as approval_context; there is no global state,
    persistence, code loading or approval inferred from a review. The application
    calls grant only after reviewing the exact action and granting permissions.
    Consumption precedes execution; failures require a fresh grant. Do not share
    one instance between unrelated stores/workspaces with overlapping identities.
    """

    def __init__(self) -> None:
        self._grants: dict[AgentWorkflowApproval, _Grant] = {}
        self._lock = Lock()

    def grant(
        self,
        reference: AgentWorkflowApproval,
        *,
        scope: ScopePath,
        permissions: Collection[str] = frozenset(),
        ttl_seconds: float = 300.0,
    ) -> None:
        if not isinstance(reference, AgentWorkflowApproval) or not isinstance(scope, ScopePath):
            raise ValueError("approval grant needs a typed reference and scope")
        if isinstance(permissions, (str, bytes)):
            raise ValueError("permissions must be a collection of names")
        allowed = frozenset(permissions)
        if any(not isinstance(item, str) or not item.strip() for item in allowed):
            raise ValueError("permission names must be nonempty strings")
        if (
            isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
            or not isfinite(ttl_seconds) or ttl_seconds <= 0
        ):
            raise ValueError("grant lifetime must be positive and finite")
        now = monotonic()
        with self._lock:
            self._grants = {
                key: value for key, value in self._grants.items() if value.expires_at > now
            }
            self._grants[reference] = _Grant(scope, allowed, now + ttl_seconds)

    def revoke(self, reference: AgentWorkflowApproval) -> None:
        with self._lock:
            self._grants.pop(reference, None)

    def clear(self) -> None:
        with self._lock:
            self._grants.clear()

    def __call__(
        self, context: WorkflowNodeContext, reference: AgentWorkflowApproval
    ) -> ToolExecutionContext:
        empty = ToolExecutionContext(cancellation=context.cancellation)
        if reference.workflow_run_id != context.run_id or reference.workflow_node != context.node:
            return empty
        with self._lock:
            grant = self._grants.get(reference)
            if grant is None:
                return empty
            if grant.expires_at <= monotonic():
                self._grants.pop(reference)
                return empty
            if grant.scope != context.scope:
                return empty
            self._grants.pop(reference)
        return ToolExecutionContext(
            permissions=grant.permissions,
            approved_call_ids=frozenset({reference.call_id}),
            cancellation=context.cancellation,
        )
