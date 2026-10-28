"""Explicit, operation-scoped assembly for parent Workflow approval recovery."""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from w_agent.agents import RunStore
from w_agent.kernel import ScopePath
from w_agent.models import CancellationToken

from .approval import AgentWorkflowApproval
from .approval_review import (
    WorkflowApprovalGrants, WorkflowApprovalLinkStatus, review_workflow_approvals,
)
from .control import WorkflowPauseSource
from .engine import LocalWorkflowEngine
from .invocation import WorkflowNodeInvoker
from .loading import WorkflowEntryLoadError
from .persistence import WorkflowStore
from .types import (
    DagWorkflowDefinition, PythonWorkflowDefinition, StateGraphDefinition,
    WorkflowDefinition, WorkflowKind, WorkflowResult,
)


class WorkflowApprovalResumeError(RuntimeError):
    """The selected approval cannot safely enter parent Workflow recovery."""


@dataclass(frozen=True, slots=True)
class WorkflowApprovalAssemblyContext:
    """Explicit dependencies for trusted developer-owned assembly code.

    Use agent_store for both the child loop and its approval adapter, and inject
    grants as approval_context. No global registry or ambient authority is used.
    The factory owns its clients and closes them when its context exits.
    """

    reference: AgentWorkflowApproval
    workflow_name: str
    workflow_version: str
    workflow_kind: WorkflowKind
    scope: ScopePath
    workflow_store: WorkflowStore
    agent_store: RunStore
    grants: WorkflowApprovalGrants


WorkflowApprovalFactory = Callable[
    [WorkflowApprovalAssemblyContext], AbstractAsyncContextManager[WorkflowDefinition]
]


@asynccontextmanager
async def open_workflow_approval_entry(
    entry: str, context: WorkflowApprovalAssemblyContext,
) -> AsyncIterator[WorkflowDefinition]:
    """Import a separately authorized factory only when entering its context.

    The factory is called with one assembly context and returns an async context
    manager yielding one definition. Ordinary zero-argument workflow entries are
    unchanged. Imports/factories are trusted local Python, not sandboxed code.
    """

    if not isinstance(entry, str) or entry.count(":") != 1:
        raise WorkflowEntryLoadError("approval factory must use module:attribute syntax")
    module_name, attribute = entry.split(":", 1)
    if not module_name.strip() or not attribute.strip():
        raise WorkflowEntryLoadError("approval factory module and attribute are required")
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except Exception:
        raise WorkflowEntryLoadError("approval factory could not be imported") from None
    if not callable(factory):
        raise WorkflowEntryLoadError("approval factory must be callable")
    async with factory(context) as definition:
        yield definition


async def resume_workflow_approval(
    workflow_store: WorkflowStore,
    agent_store: RunStore,
    reference: AgentWorkflowApproval,
    factory: WorkflowApprovalFactory,
    *,
    permissions: Collection[str] = frozenset(),
    state_keys: Sequence[str] | None = None,
    cancellation: CancellationToken | None = None,
    node_invoker: WorkflowNodeInvoker | None = None,
    pause_source: WorkflowPauseSource | None = None,
) -> WorkflowResult:
    """Authorize one exact pending call and resume its parent, not its child.

    Calling this API is the host's explicit approval and execution authorization.
    Review the actual action separately: identifier matching is not authorization.
    The CLI additionally gates imports, this approval, and parent execution.

    Rechecks detect checkpoint changes during assembly, but are not atomic across
    stores and do not replace single-owner execution or trusted local storage.
    Factory code is trusted and must use the supplied dependencies faithfully.
    A paused result does not prove the selected call ran; unused grants are cleared.
    """

    if not isinstance(reference, AgentWorkflowApproval) or not callable(factory):
        raise ValueError("approval resume needs a typed reference and factory")
    if isinstance(permissions, (str, bytes)):
        raise ValueError("permissions must be a collection of names")
    allowed = frozenset(permissions)
    if any(not isinstance(item, str) or not item.strip() for item in allowed):
        raise ValueError("permission names must be nonempty strings")
    # Capture keys before invoking application code; use the same selection twice.
    if state_keys is not None and (
        not isinstance(state_keys, Sequence) or isinstance(state_keys, (str, bytes))
    ):
        raise ValueError("state keys must be a sequence, not a string")
    keys = tuple(state_keys) if state_keys is not None else None
    parent = await workflow_store.load_checkpoint(reference.workflow_run_id)
    child = await agent_store.load_checkpoint(reference.agent_run_id)

    async def require_match() -> None:
        reviews = await review_workflow_approvals(
            workflow_store, agent_store, reference.workflow_run_id, state_keys=keys,
        )
        selected = [review for review in reviews if review.reference == reference]
        if len(selected) != 1 or selected[0].link_status is not WorkflowApprovalLinkStatus.MATCHED:
            raise WorkflowApprovalResumeError("selected approval is absent, stale, or not pending")
        if (
            parent is None or child is None
            or await workflow_store.load_checkpoint(reference.workflow_run_id) != parent
            or await agent_store.load_checkpoint(reference.agent_run_id) != child
        ):
            raise WorkflowApprovalResumeError("approval checkpoints changed; review again")

    await require_match()  # No factory/import invocation before the first check.
    assert parent is not None
    grants = WorkflowApprovalGrants()
    context = WorkflowApprovalAssemblyContext(
        reference, parent.workflow_name, parent.workflow_version, parent.kind,
        parent.scope, workflow_store, agent_store, grants,
    )
    result = None
    try:
        async with factory(context) as definition:
            try:
                if not isinstance(definition, (
                    DagWorkflowDefinition, StateGraphDefinition, PythonWorkflowDefinition,
                )):
                    raise WorkflowApprovalResumeError("factory must yield one workflow definition")
                if (
                    definition.name != parent.workflow_name
                    or definition.version != parent.workflow_version
                    or definition.kind is not parent.kind
                ):
                    raise WorkflowApprovalResumeError("factory yielded a different workflow identity")
                await require_match()
                # Authority starts only after assembly and a second link/snapshot check.
                grants.clear()
                grants.grant(reference, scope=parent.scope, permissions=allowed)
                result = await LocalWorkflowEngine(
                    workflow_store, node_invoker=node_invoker, pause_source=pause_source,
                ).resume(definition, reference.workflow_run_id, cancellation=cancellation)
            finally:
                grants.clear()  # Also clear before developer resource cleanup runs.
    finally:
        grants.clear()  # Covers failed __aenter__, failed __aexit__, and cancellation.
    if result is None:
        raise WorkflowApprovalResumeError("factory suppressed recovery without a result")
    return result
