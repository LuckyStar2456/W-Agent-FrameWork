"""Deterministic local workflow engine with node-boundary recovery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, Mapping

from w_agent.models import CancellationToken

from .control import WorkflowPauseSource
from .invocation import InlineWorkflowNodeInvoker, WorkflowNodeInvoker
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

    def __init__(
        self,
        store: WorkflowStore | None = None,
        *,
        max_parallel_nodes: int = 1,
        node_invoker: WorkflowNodeInvoker | None = None,
        pause_source: WorkflowPauseSource | None = None,
    ) -> None:
        if (
            isinstance(max_parallel_nodes, bool)
            or not isinstance(max_parallel_nodes, int)
            or max_parallel_nodes < 1
        ):
            raise ValueError("workflow max_parallel_nodes must be positive")
        self.store = store or InMemoryWorkflowStore()
        self.max_parallel_nodes = max_parallel_nodes
        self.node_invoker = (
            InlineWorkflowNodeInvoker() if node_invoker is None else node_invoker
        )
        if not callable(getattr(self.node_invoker, "invoke", None)):
            raise ValueError("workflow node invoker needs an invoke method")
        self.pause_source = pause_source
        if pause_source is not None and not callable(
            getattr(pause_source, "is_pause_requested", None)
        ):
            raise ValueError("workflow pause source needs an is_pause_requested method")

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
            if self.pause_source is not None:
                # Inline nodes and in-memory stores may otherwise never yield
                # to the application's coroutine that requests a pause.
                await asyncio.sleep(0)
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

            if self.pause_source is not None and self.pause_source.is_pause_requested(
                checkpoint.run_id
            ):
                return await self._pause_at_boundary(definition, checkpoint)

            if (
                isinstance(definition, DagWorkflowDefinition)
                and self.max_parallel_nodes > 1
            ):
                ready = _ready_dag_nodes(definition, checkpoint)
                if len(ready) > 1:
                    checkpoint, stopped = await self._run_dag_batch(
                        definition,
                        checkpoint,
                        ready[: self.max_parallel_nodes],
                        cancellation,
                    )
                    if stopped is not None:
                        return stopped
                    continue

            checkpoint = await self.store.claim_checkpoint(checkpoint.run_id)
            await self._emit(
                checkpoint,
                WorkflowEventType.NODE_STARTED,
                {"node": next_node.name},
            )
            try:
                node_result = await _invoke_node(
                    next_node, checkpoint, cancellation, self.node_invoker
                )
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
                WorkflowEventType.NODE_SUSPENDED
                if node_result.suspend else WorkflowEventType.NODE_COMPLETED,
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

    async def _pause_at_boundary(
        self,
        definition: WorkflowDefinition,
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowResult:
        claimed = await self.store.claim_checkpoint(checkpoint.run_id)
        paused = replace(claimed, status=WorkflowCheckpointStatus.PAUSED)
        await self.store.save_checkpoint(paused)
        await self._emit(
            paused,
            WorkflowEventType.WORKFLOW_PAUSED,
            {"source": "external-request"},
        )
        return await self._result(
            definition,
            paused,
            WorkflowStopReason.PAUSED,
            checkpoint_id=paused.run_id,
        )

    async def _run_dag_batch(
        self,
        definition: DagWorkflowDefinition,
        checkpoint: WorkflowCheckpoint,
        nodes: tuple[WorkflowNode, ...],
        cancellation: CancellationToken | None,
    ) -> tuple[WorkflowCheckpoint, WorkflowResult | None]:
        """Run one independent DAG frontier against the same committed snapshot.

        The checkpoint remains RESUMING until the entire batch is merged. A
        failed, cancelled, or conflicting batch is never automatically replayed.
        """
        checkpoint = await self.store.claim_checkpoint(checkpoint.run_id)
        batch_names = tuple(node.name for node in nodes)
        for node in nodes:
            await self._emit(
                checkpoint,
                WorkflowEventType.NODE_STARTED,
                {"node": node.name, "batch": batch_names},
            )
        tasks = [
            asyncio.create_task(
                _invoke_node(node, checkpoint, cancellation, self.node_invoker)
            )
            for node in nodes
        ]
        collection = asyncio.gather(*tasks, return_exceptions=True)
        cancel_waiter = (
            asyncio.create_task(cancellation.wait())
            if cancellation is not None
            else None
        )
        cancelled_batch = False
        try:
            if cancel_waiter is not None:
                done, _pending = await asyncio.wait(
                    {collection, cancel_waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_waiter in done and collection not in done:
                    for task in tasks:
                        task.cancel()
                    await collection
                    cancelled_batch = True
            outcomes = () if cancelled_batch else await collection
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            cancelled_batch = True
            outcomes = ()
        finally:
            if cancel_waiter is not None:
                cancel_waiter.cancel()
                await asyncio.gather(cancel_waiter, return_exceptions=True)

        if cancelled_batch:
            stopped = await self._finish(
                definition,
                checkpoint,
                WorkflowStopReason.CANCELLED,
                keep_checkpoint=True,
                failure="parallel-node-execution-cancelled",
            )
            return checkpoint, stopped

        failures = [
            (node, outcome)
            for node, outcome in zip(nodes, outcomes, strict=True)
            if isinstance(outcome, BaseException)
        ]
        if failures:
            for node, _error in failures:
                await self._emit(
                    checkpoint,
                    WorkflowEventType.NODE_FAILED,
                    {"node": node.name, "code": "parallel-node-execution-failed"},
                )
            cancelled = any(
                isinstance(error, asyncio.CancelledError)
                for _node, error in failures
            )
            stopped = await self._finish(
                definition,
                checkpoint,
                WorkflowStopReason.CANCELLED if cancelled else WorkflowStopReason.FAILED,
                keep_checkpoint=True,
                failure=(
                    "parallel-node-execution-cancelled"
                    if cancelled
                    else "parallel-node-execution-failed"
                ),
            )
            return checkpoint, stopped

        results = tuple(outcomes)
        update_owners: dict[str, str] = {}
        for node, result in zip(nodes, results, strict=True):
            for key in result.state_updates:
                if key in update_owners:
                    await self._emit(
                        checkpoint,
                        WorkflowEventType.NODE_FAILED,
                        {
                            "node": node.name,
                            "code": "parallel-state-conflict",
                            "conflicts_with": update_owners[key],
                        },
                    )
                    stopped = await self._finish(
                        definition,
                        checkpoint,
                        WorkflowStopReason.FAILED,
                        keep_checkpoint=True,
                        failure="parallel-state-conflict",
                    )
                    return checkpoint, stopped
                update_owners[key] = node.name

        checkpoint = _advance_dag_batch(checkpoint, nodes, results)
        for node, result in zip(nodes, results, strict=True):
            await self._emit(
                checkpoint,
                WorkflowEventType.NODE_SUSPENDED
                if result.suspend else WorkflowEventType.NODE_COMPLETED,
                {"node": node.name, "paused": result.pause, "batch": batch_names},
            )
        await self.store.save_checkpoint(checkpoint)
        paused = tuple(
            node.name
            for node, result in zip(nodes, results, strict=True)
            if result.pause
        )
        if paused:
            await self._emit(
                checkpoint,
                WorkflowEventType.WORKFLOW_PAUSED,
                {"node": paused[0], "nodes": paused},
            )
            stopped = await self._result(
                definition,
                checkpoint,
                WorkflowStopReason.PAUSED,
                checkpoint_id=checkpoint.run_id,
            )
            return checkpoint, stopped
        return checkpoint, None

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
        ready = _ready_dag_nodes(definition, checkpoint)
        if ready:
            return ready[0]
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


def _ready_dag_nodes(
    definition: DagWorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
) -> tuple[WorkflowNode, ...]:
    completed = set(checkpoint.completed_nodes)
    nodes = {node.name: node for node in definition.nodes}
    return tuple(
        nodes[name]
        for name in checkpoint.remaining_nodes
        if set(definition.dependencies[name]) <= completed
    )


async def _invoke_node(
    node: WorkflowNode,
    checkpoint: WorkflowCheckpoint,
    cancellation: CancellationToken | None,
    invoker: WorkflowNodeInvoker,
) -> WorkflowNodeResult:
    raw_result = await invoker.invoke(
        node,
        WorkflowNodeContext(
            run_id=checkpoint.run_id,
            node=node.name,
            input=checkpoint.input,
            state=checkpoint.state,
            outputs=checkpoint.outputs,
            scope=checkpoint.scope,
            cancellation=cancellation,
            resume_count=checkpoint.resume_count,
            metadata=checkpoint.metadata,
        )
    )
    return _normalize_result(raw_result)


def _advance_dag_batch(
    checkpoint: WorkflowCheckpoint,
    nodes: tuple[WorkflowNode, ...],
    results: tuple[WorkflowNodeResult, ...],
) -> WorkflowCheckpoint:
    state = dict(checkpoint.state)
    outputs = dict(checkpoint.outputs)
    completed = tuple(
        node.name for node, result in zip(nodes, results, strict=True)
        if not result.suspend
    )
    for node, result in zip(nodes, results, strict=True):
        state.update(result.state_updates)
        if not result.suspend:
            outputs[node.name] = result.output
    return replace(
        checkpoint,
        state=state,
        outputs=outputs,
        completed_nodes=(*checkpoint.completed_nodes, *completed),
        remaining_nodes=tuple(
            name for name in checkpoint.remaining_nodes if name not in completed
        ),
        status=(
            WorkflowCheckpointStatus.PAUSED
            if any(result.pause for result in results)
            else WorkflowCheckpointStatus.READY
        ),
    )


def _advance(
    definition: WorkflowDefinition,
    checkpoint: WorkflowCheckpoint,
    node: WorkflowNode,
    result: WorkflowNodeResult,
) -> WorkflowCheckpoint:
    state = dict(checkpoint.state)
    state.update(result.state_updates)
    if result.suspend:
        return replace(
            checkpoint,
            state=state,
            resume_count=(
                checkpoint.resume_count + 1
                if isinstance(definition, PythonWorkflowDefinition)
                else checkpoint.resume_count
            ),
            status=WorkflowCheckpointStatus.PAUSED,
        )
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
