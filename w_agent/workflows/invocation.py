"""Replaceable workflow node invocation without changing scheduling or stores."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Protocol

from .types import WorkflowNode, WorkflowNodeContext


class WorkflowNodeInvoker(Protocol):
    """Invoke once and return the handler value, before result normalization.

    Implementations must propagate failures and cancellation, and must not retry
    handlers or commit workflow state. The engine owns those boundaries.
    """

    async def invoke(self, node: WorkflowNode, context: WorkflowNodeContext) -> Any:
        ...


class InlineWorkflowNodeInvoker:
    """Preserve the default event-loop-thread execution of sync handlers."""

    async def invoke(self, node: WorkflowNode, context: WorkflowNodeContext) -> Any:
        result = node.handler(context)
        if inspect.isawaitable(result):
            result = await result
        return result


class ThreadedWorkflowNodeInvoker:
    """Offload sync calls, preserving async handlers on the event loop.

    Uses asyncio's default thread executor and copies context variables through
    to_thread. Cancellation drains an already-started sync call before escaping;
    Python cannot forcibly stop that thread. A cancelled call's result is never
    committed. This is an invocation policy, not an isolation boundary.
    """

    async def invoke(self, node: WorkflowNode, context: WorkflowNodeContext) -> Any:
        handler = node.handler
        if inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
            getattr(handler, "__call__", None)
        ):
            return await handler(context)

        worker = asyncio.create_task(asyncio.to_thread(handler, context))
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            await _drain_cancelled_worker(worker)
            raise
        if inspect.isawaitable(result):
            result = await result
        return result


async def _drain_cancelled_worker(worker: asyncio.Task[Any]) -> None:
    """Observe late errors and dispose of an unstarted returned coroutine."""
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Repeated cancellation must not detach a still-running handler.
            continue
        except BaseException:
            # Cancellation remains the caller-visible outcome.
            break
    if not worker.cancelled():
        try:
            result = worker.result()
        except BaseException:
            return
        if inspect.iscoroutine(result):
            result.close()
