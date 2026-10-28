import asyncio
import inspect
import threading
from contextvars import ContextVar

import pytest

from w_agent import (
    DagWorkflowDefinition,
    InMemoryWorkflowStore,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    StateGraphDefinition,
    ThreadedWorkflowNodeInvoker,
    WorkflowCheckpointStatus,
    WorkflowContext,
    WorkflowNode,
    WorkflowNodeResult,
    WorkflowResumeConflictError,
    WorkflowStopReason,
)


@pytest.mark.asyncio
async def test_threaded_sync_node_can_wait_for_async_sibling_and_copies_context():
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    entered = asyncio.Event()
    release = threading.Event()
    trace = ContextVar("workflow-test-trace", default="missing")
    trace_token = trace.set("run-trace")

    def sync_node(context):
        assert threading.get_ident() != loop_thread
        assert trace.get() == "run-trace"
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=3)
        return WorkflowNodeResult(output="sync", state_updates={"loaded": True})

    class AsyncNode:
        async def __call__(self, context):
            assert threading.get_ident() == loop_thread
            await entered.wait()
            release.set()
            return "async"

    definition = DagWorkflowDefinition(
        "mixed", (WorkflowNode("sync", sync_node), WorkflowNode("async", AsyncNode()))
    )
    try:
        result = await asyncio.wait_for(
            LocalWorkflowEngine(
                max_parallel_nodes=2, node_invoker=ThreadedWorkflowNodeInvoker()
            ).start(definition, WorkflowContext("mixed-1")),
            timeout=5,
        )
    finally:
        release.set()
        trace.reset(trace_token)
    assert result.stop_reason is WorkflowStopReason.COMPLETED
    assert result.outputs == {"sync": "sync", "async": "async"}
    assert result.state == {"loaded": True}
    assert result.completed_nodes == ("sync", "async")


@pytest.mark.asyncio
async def test_threaded_sync_factory_awaits_returned_coroutine_on_event_loop():
    loop_thread = threading.get_ident()

    async def value():
        assert threading.get_ident() == loop_thread
        return "awaited"

    def factory(context):
        assert threading.get_ident() != loop_thread
        return value()

    result = await LocalWorkflowEngine(
        node_invoker=ThreadedWorkflowNodeInvoker()
    ).start(PythonWorkflowDefinition("factory", factory), WorkflowContext("factory-1"))
    assert result.stop_reason is WorkflowStopReason.COMPLETED
    assert result.output == "awaited"


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_cancelled_threaded_calls_drain_without_committing_or_replaying(parallel):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    returned = []
    calls = []

    async def late_value():
        raise AssertionError("cancelled result must not execute")

    def blocking(context):
        calls.append(context.node)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=3)
        result = late_value()
        returned.append(result)
        return result

    async def sibling(context):
        await asyncio.Future()

    definition = (
        DagWorkflowDefinition(
            "cancel", (WorkflowNode("sync", blocking), WorkflowNode("async", sibling))
        )
        if parallel
        else PythonWorkflowDefinition("cancel", blocking)
    )
    store = InMemoryWorkflowStore()
    engine = LocalWorkflowEngine(
        store, max_parallel_nodes=2, node_invoker=ThreadedWorkflowNodeInvoker()
    )
    task = asyncio.create_task(engine.start(definition, WorkflowContext("cancel-1")))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        # Let the engine and invocation policy receive cancellation.
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()
        checkpoint = await store.load_checkpoint("cancel-1")
        assert checkpoint.status is WorkflowCheckpointStatus.RESUMING
    finally:
        release.set()
        result = await asyncio.wait_for(task, timeout=5)
    assert result.stop_reason is WorkflowStopReason.CANCELLED
    assert result.completed_nodes == ()
    assert len(calls) == 1
    assert len(returned) == 1
    assert inspect.getcoroutinestate(returned[0]) == inspect.CORO_CLOSED
    with pytest.raises(WorkflowResumeConflictError):
        await engine.resume(definition, "cancel-1")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dag", "graph", "python"])
async def test_custom_invoker_is_used_for_each_frontend_and_resume(kind):
    calls = []

    class CustomInvoker:
        async def invoke(self, node, context):
            calls.append(node.name)
            return node.handler(context)

    def first(context):
        if kind == "python" and context.resume_count > 0:
            return "resumed"
        return WorkflowNodeResult(output="paused", pause=True)

    nodes = (WorkflowNode("first", first), WorkflowNode("last", lambda _: "resumed"))
    if kind == "dag":
        definition = DagWorkflowDefinition("custom", nodes, {"last": ("first",)})
    elif kind == "graph":
        definition = StateGraphDefinition(
            "custom", nodes, "first", transitions={"first": "last"}
        )
    else:
        definition = PythonWorkflowDefinition("custom", first)
    engine = LocalWorkflowEngine(node_invoker=CustomInvoker())
    paused = await engine.start(definition, WorkflowContext("custom-1"))
    resumed = await engine.resume(definition, "custom-1")
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert resumed.stop_reason is WorkflowStopReason.COMPLETED
    assert resumed.output == "resumed"
    assert len(calls) == 2
