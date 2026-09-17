"""Deterministic local workflow engine with node-boundary recovery."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from typing import Any, Mapping

from w_agent.models import CancellationToken

from .persistence import (
    InMemoryWorkflowStore,
    WorkflowStore,
    WorkflowStoreError,
)
from .types import (
    DagWorkflowDefinition,
    PythonWorkflowDefinition,
    StateGraphDefinition,
    WorkflowCheckpoint,
    WorkflowCheckpointStatus,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowNode,
    WorkflowNodeContext,
    WorkflowNodeResult,
    WorkflowResult,
    WorkflowStopReason,
)


class LocalWorkflowEngine:
    """Run built-in workflow frontends against one replaceable state store.

    Recovery is deliberately limited to completed node boundaries. A checkpoint
    left in ``RESUMING`` means a node may have produced side effects, so the
    engine refuses to replay it automatically.
    """

    def __init__(self, store: WorkflowStore | None = None) -> None:
        self.store = store or InMemoryWorkflowStore()

    async def start(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
    ) -> WorkflowResult:
        if await self.store.events(context.run_id) or await self.store.load_checkpoint(
            context.run_id
        ):
            raise WorkflowStoreError(f"workflow run {context.run_id!r} already exists")
        checkpoint = _initial_checkpoint(definition, context)
        await self.store.save_checkpoint(checkpoint)
        await self._emit(
            checkpoint,
            WorkflowEventType.WORKFLOW_STARTED,
            {
                "workflow": definition.name,
                "version": definition.version,
                "kind": definition.kind.value,
            },
        )
        return await self._drive(definition, checkpoint, context.cancellation)

    async def resume(
        self,
        definition: WorkflowDefinition,
        run_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ) -> WorkflowResult:
        checkpoint = await self.store.load_checkpoint(run_id)
        if checkpoint is None:
            raise WorkflowStoreError(
                f"workflow run {run_id!r} has no resumable checkpoint"
            )
        _validate_definition(definition, checkpoint)
        if checkpoint.status is WorkflowCheckpointStatus.RESUMING:
            from .persistence import WorkflowResumeConflictError

            raise WorkflowResumeConflictError(
                f"workflow run {run_id!r} contains an uncertain node execution"
            )
        await self._emit(
            checkpoint,
            WorkflowEventType.WORKFLOW_RESUMED,
            {"status": checkpoint.status.value},
        )
        return await self._drive(definition, checkpoint, cancellation)

    async def _drive(
        self,
        definition: WorkflowDefinition,
        checkpoint: WorkflowCheckpoint,
        cancellation: CancellationToken | None,
    ) -> WorkflowResult:
        while True:
            if cancellation is not None and cancellation.cancelled:
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.CANCELLED,
                    keep_checkpoint=True,
                )

            next_node = _next_node(definition, checkpoint)
            if next_node is None:
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.COMPLETED,
                )

            if isinstance(definition, StateGraphDefinition) and (
                checkpoint.graph_steps >= definition.max_steps
            ):
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.MAX_STEPS,
                )
            if isinstance(definition, PythonWorkflowDefinition) and (
                checkpoint.resume_count > definition.max_resumes
            ):
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.MAX_STEPS,
                )

            checkpoint = await self.store.claim_checkpoint(checkpoint.run_id)
            await self._emit(
                checkpoint,
                WorkflowEventType.NODE_STARTED,
                {"node": next_node.name},
            )
            try:
                raw_result = next_node.handler(
                    WorkflowNodeContext(
                        run_id=checkpoint.run_id,
                        node=next_node.name,
                        input=checkpoint.input,
                        state=checkpoint.state,
                        outputs=checkpoint.outputs,
                        scope=checkpoint.scope,
                        cancellation=cancellation,
                        resume_count=checkpoint.resume_count,
                        metadata=checkpoint.metadata,
                    )
                )
                if inspect.isawaitable(raw_result):
                    raw_result = await raw_result
                node_result = _normalize_result(raw_result)
                checkpoint = _advance(
                    definition,
                    checkpoint,
                    next_node,
                    node_result,
                )
            except asyncio.CancelledError:
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.CANCELLED,
                    keep_checkpoint=True,
                    failure="node-execution-cancelled",
                )
            except Exception:
                await self._emit(
                    checkpoint,
                    WorkflowEventType.NODE_FAILED,
                    {"node": next_node.name, "code": "node-execution-failed"},
                )
                return await self._finish(
                    definition,
                    checkpoint,
                    WorkflowStopReason.FAILED,
                    keep_checkpoint=True,
                    failure="node-execution-failed",
                )

            await self._emit(
                checkpoint,
                WorkflowEventType.NODE_COMPLETED,
                {"node": next_node.name, "paused": node_result.pause},
            )
            await self.store.save_checkpoint(checkpoint)
            if node_result.pause:
                await self._emit(
                    checkpoint,
                    WorkflowEventType.WORKFLOW_PAUSED,
                    {"node": next_node.name},
                )
                return await self._result(
                    definition,
                    checkpoint,
                    WorkflowStopReason.PAUSED,
                    checkpoint_id=checkpoint.run_id,
                )

    async def _emit(
        self,
        checkpoint: WorkflowCheckpoint,
        event_type: WorkflowEventType,
        data: Mapping[str, Any],
    ) -> WorkflowEvent:
        sequence = len(await self.store.events(checkpoint.run_id)) + 1
        event = WorkflowEvent(
            sequence,
            event_type,
            checkpoint.run_id,
            data,
            session_id=checkpoint.session_id,
        )
        await self.store.append(event)
        return event

    async def _finish(
        self,
        definition: WorkflowDefinition,
        checkpoint: WorkflowCheckpoint,
        reason: WorkflowStopReason,
        *,
        keep_checkpoint: bool = False,
        failure: str | None = None,
    ) -> WorkflowResult:
        await self._emit(
            checkpoint,
            WorkflowEventType.WORKFLOW_COMPLETED,
            {"reason": reason.value},
        )
        if not keep_checkpoint:
            await self.store.delete_checkpoint(checkpoint.run_id)
        return await self._result(
            definition,
            checkpoint,
            reason,
            checkpoint_id=checkpoint.run_id if keep_checkpoint else None,
            failure=failure,
        )

    async def _result(
        self,
        definition: WorkflowDefinition,
        checkpoint: WorkflowCheckpoint,
        reason: WorkflowStopReason,
        *,
        checkpoint_id: str | None = None,
        failure: str | None = None,
    ) -> WorkflowResult:
        return WorkflowResult(
            run_id=checkpoint.run_id,
            stop_reason=reason,
            output=_workflow_output(definition, checkpoint),
            state=checkpoint.state,
            outputs=checkpoint.outputs,
            events=await self.store.events(checkpoint.run_id),
            completed_nodes=checkpoint.completed_nodes,
            checkpoint_id=checkpoint_id,
            failure=failure,
        )


def _initial_checkpoint(
    definition: WorkflowDefinition,
    context: WorkflowContext,
) -> WorkflowCheckpoint:
    remaining: tuple[str, ...] = ()
    current: str | None = None
    if isinstance(definition, DagWorkflowDefinition):
        remaining = tuple(node.name for node in definition.nodes)
    elif isinstance(definition, StateGraphDefinition):
        current = definition.entry
    else:
        current = "python"
    return WorkflowCheckpoint(
        run_id=context.run_id,
        workflow_name=definition.name,
        workflow_version=definition.version,
        kind=definition.kind,
        scope=context.scope,
        input=context.input,
        state=context.state,
        outputs={},
        completed_nodes=(),
        remaining_nodes=remaining,
        current_node=current,
        session_id=context.session_id,
        metadata=context.metadata,
    )


def _validate_definition(
    definition: WorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
) -> None:
    identity = (definition.name, definition.version, definition.kind)
    stored = (
        checkpoint.workflow_name,
        checkpoint.workflow_version,
        checkpoint.kind,
    )
    if identity != stored:
        raise WorkflowStoreError(
            "workflow definition name, version, or kind differs from checkpoint"
        )


def _next_node(
    definition: WorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
) -> WorkflowNode | None:
    if isinstance(definition, DagWorkflowDefinition):
        completed = set(checkpoint.completed_nodes)
        nodes = {node.name: node for node in definition.nodes}
        for name in checkpoint.remaining_nodes:
            if set(definition.dependencies[name]) <= completed:
                return nodes[name]
        if checkpoint.remaining_nodes:
            raise WorkflowStoreError("DAG checkpoint has no executable node")
        return None
    if isinstance(definition, StateGraphDefinition):
        if checkpoint.current_node is None:
            return None
        return _nodes(definition)[checkpoint.current_node]
    return (
        None
        if checkpoint.current_node is None
        else WorkflowNode(
            "python",
            definition.handler,
        )
    )


def _advance(
    definition: WorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
    node: WorkflowNode,
    result: WorkflowNodeResult,
) -> WorkflowCheckpoint:
    state = dict(checkpoint.state)
    state.update(result.state_updates)
    outputs = dict(checkpoint.outputs)
    outputs[node.name] = result.output

    if isinstance(definition, DagWorkflowDefinition):
        remaining = tuple(
            name for name in checkpoint.remaining_nodes if name != node.name
        )
        return replace(
            checkpoint,
            state=state,
            outputs=outputs,
            completed_nodes=(*checkpoint.completed_nodes, node.name),
            remaining_nodes=remaining,
            status=(
                WorkflowCheckpointStatus.PAUSED
                if result.pause
                else WorkflowCheckpointStatus.READY
            ),
        )

    if isinstance(definition, StateGraphDefinition):
        target = (
            result.next_node
            if result.next_node is not None
            else definition.transitions.get(node.name)
        )
        if target is not None and target not in _nodes(definition):
            raise ValueError("state graph node returned an unknown transition")
        return replace(
            checkpoint,
            state=state,
            outputs=outputs,
            completed_nodes=(*checkpoint.completed_nodes, node.name),
            current_node=target,
            graph_steps=checkpoint.graph_steps + 1,
            status=(
                WorkflowCheckpointStatus.PAUSED
                if result.pause
                else WorkflowCheckpointStatus.READY
            ),
        )

    if result.pause:
        return replace(
            checkpoint,
            state=state,
            outputs=outputs,
            current_node="python",
            resume_count=checkpoint.resume_count + 1,
            status=WorkflowCheckpointStatus.PAUSED,
        )
    return replace(
        checkpoint,
        state=state,
        outputs=outputs,
        completed_nodes=("python",),
        current_node=None,
        status=WorkflowCheckpointStatus.READY,
    )


def _normalize_result(value: Any) -> WorkflowNodeResult:
    if isinstance(value, WorkflowNodeResult):
        return value
    return WorkflowNodeResult(output=value)


def _nodes(
    definition: StateGraphDefinition,
) -> dict[str, WorkflowNode]:
    return {node.name: node for node in definition.nodes}


def _workflow_output(
    definition: WorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
) -> Any:
    if isinstance(definition, DagWorkflowDefinition):
        dependencies = {
            dependency
            for values in definition.dependencies.values()
            for dependency in values
        }
        sinks = [
            node.name for node in definition.nodes if node.name not in dependencies
        ]
        available = [name for name in sinks if name in checkpoint.outputs]
        if len(available) == 1:
            return checkpoint.outputs[available[0]]
        return {name: checkpoint.outputs[name] for name in available}
    if isinstance(definition, StateGraphDefinition):
        if not checkpoint.completed_nodes:
            return None
        return checkpoint.outputs.get(checkpoint.completed_nodes[-1])
    return checkpoint.outputs.get("python")
