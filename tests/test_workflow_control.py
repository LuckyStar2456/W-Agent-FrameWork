import asyncio

import pytest

from w_agent import (
    AnyWorkflowPauseSource,
    CancellationToken,
    DagWorkflowDefinition,
    InMemoryWorkflowStore,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    StateGraphDefinition,
    WorkflowCheckpointStatus,
    WorkflowContext,
    WorkflowEventType,
    WorkflowNode,
    WorkflowPauseController,
    WorkflowStopReason,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dag", "graph", "python"])
async def test_pause_before_first_node_persists_and_resumes_without_running_code(
    kind, tmp_path
):
    calls = []

    def handler(context):
        calls.append(context.node)
        return "done"

    if kind == "dag":
        definition = DagWorkflowDefinition("pause", (WorkflowNode("node", handler),))
    elif kind == "graph":
        definition = StateGraphDefinition("pause", (WorkflowNode("node", handler),), "node")
    else:
        definition = PythonWorkflowDefinition("pause", handler)
    control = WorkflowPauseController()
    control.request_pause("run-1")
    store = JsonlWorkflowStore(tmp_path)
    engine = LocalWorkflowEngine(store, pause_source=control)
    paused = await engine.start(definition, WorkflowContext("run-1"))
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert calls == []
    checkpoint = await store.load_checkpoint("run-1")
    assert checkpoint.status is WorkflowCheckpointStatus.PAUSED
    assert checkpoint.resume_count == 0
    still_paused = await engine.resume(definition, "run-1")
    assert still_paused.stop_reason is WorkflowStopReason.PAUSED
    assert calls == []
    control.clear("run-1")
    assert calls == []
    resumed = await LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).resume(
        definition, "run-1"
    )
    assert resumed.stop_reason is WorkflowStopReason.COMPLETED
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
async def test_running_pause_drains_current_frontier_and_does_not_replay(parallel):
    control = WorkflowPauseController()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def first(context):
        calls.append(context.node)
        entered.set()
        await release.wait()
        return context.node

    def last(context):
        calls.append(context.node)
        return "joined"

    front = (WorkflowNode("left", first),)
    if parallel:
        front += (WorkflowNode("right", first),)
    definition = DagWorkflowDefinition(
        "frontier", (*front, WorkflowNode("last", last)),
        {"last": tuple(node.name for node in front)},
    )
    store = InMemoryWorkflowStore()
    engine = LocalWorkflowEngine(store, max_parallel_nodes=2, pause_source=control)
    task = asyncio.create_task(engine.start(definition, WorkflowContext("frontier-1")))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        control.request_pause("frontier-1")
        assert not task.done()
    finally:
        release.set()
    paused = await asyncio.wait_for(task, timeout=2)
    assert paused.stop_reason is WorkflowStopReason.PAUSED
    assert paused.completed_nodes == tuple(node.name for node in front)
    assert "last" not in calls
    assert paused.events[-1].type is WorkflowEventType.WORKFLOW_PAUSED
    assert paused.events[-1].data == {"source": "external-request"}
    control.clear("frontier-1")
    resumed = await engine.resume(definition, "frontier-1")
    assert resumed.stop_reason is WorkflowStopReason.COMPLETED
    assert calls == [node.name for node in front] + ["last"]


@pytest.mark.asyncio
async def test_inline_workflow_yields_for_external_pause_coroutine():
    control = WorkflowPauseController()
    entered = asyncio.Event()

    def first(context):
        entered.set()
        return "first"

    async def request():
        await entered.wait()
        control.request_pause("inline-1")

    definition = DagWorkflowDefinition(
        "inline",
        (WorkflowNode("first", first), WorkflowNode("last", lambda _: "last")),
        {"last": ("first",)},
    )
    requester = asyncio.create_task(request())
    try:
        result = await LocalWorkflowEngine(pause_source=control).start(
            definition, WorkflowContext("inline-1")
        )
    finally:
        requester.cancel()
        await asyncio.gather(requester, return_exceptions=True)
    assert result.stop_reason is WorkflowStopReason.PAUSED
    assert result.completed_nodes == ("first",)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "fail", "cancel"])
async def test_pause_does_not_override_terminal_or_uncertain_execution(outcome):
    control = WorkflowPauseController()
    token = CancellationToken()
    store = InMemoryWorkflowStore()

    def handler(context):
        control.request_pause(context.run_id)
        if outcome == "fail":
            raise RuntimeError("private failure")
        if outcome == "cancel":
            token.cancel()
            raise asyncio.CancelledError()
        return "done"

    result = await LocalWorkflowEngine(store, pause_source=control).start(
        PythonWorkflowDefinition("terminal", handler),
        WorkflowContext("terminal-1", cancellation=token),
    )
    expected = {
        "complete": WorkflowStopReason.COMPLETED,
        "fail": WorkflowStopReason.FAILED,
        "cancel": WorkflowStopReason.CANCELLED,
    }
    assert result.stop_reason is expected[outcome]
    checkpoint = await store.load_checkpoint("terminal-1")
    if outcome == "complete":
        assert checkpoint is None
    else:
        assert checkpoint.status is WorkflowCheckpointStatus.RESUMING


@pytest.mark.asyncio
async def test_custom_pause_source_selects_exact_run_id():
    class Source:
        def is_pause_requested(self, run_id):
            return run_id == "selected"

    engine = LocalWorkflowEngine(pause_source=Source())
    definition = PythonWorkflowDefinition("selection", lambda _: "done")
    selected = await engine.start(definition, WorkflowContext("selected"))
    other = await engine.start(definition, WorkflowContext("other"))
    assert selected.stop_reason is WorkflowStopReason.PAUSED
    assert other.stop_reason is WorkflowStopReason.COMPLETED


def test_any_pause_source_preserves_order_exact_id_and_owned_requests():
    local = WorkflowPauseController()
    persistent = WorkflowPauseController()
    source = AnyWorkflowPauseSource(local, persistent)
    assert not source.is_pause_requested("run")
    persistent.request_pause("run")
    assert source.is_pause_requested("run")
    assert not source.is_pause_requested("another")
    local.request_pause("run")
    local.clear("run")
    assert source.is_pause_requested("run")
    assert persistent.is_pause_requested("run")
    persistent.clear("run")
    assert not source.is_pause_requested("run")


def test_any_pause_source_propagates_queried_errors_and_short_circuits():
    class BrokenSource:
        def is_pause_requested(self, run_id):
            raise RuntimeError("unreadable")

    local = WorkflowPauseController()
    source = AnyWorkflowPauseSource(local, BrokenSource())
    with pytest.raises(RuntimeError, match="unreadable"):
        source.is_pause_requested("run")
    local.request_pause("run")
    assert source.is_pause_requested("run")
    # A reached failure cannot be hidden by a later positive source.
    with pytest.raises(RuntimeError, match="unreadable"):
        AnyWorkflowPauseSource(BrokenSource(), local).is_pause_requested("run")


@pytest.mark.parametrize("response", [None, "false", 0, 1, [], {}])
def test_any_pause_source_rejects_non_boolean_responses(response):
    class Source:
        def is_pause_requested(self, run_id):
            return response

    with pytest.raises(TypeError, match="bool"):
        AnyWorkflowPauseSource(Source()).is_pause_requested("run")


def test_any_pause_source_validates_configuration_and_run_id():
    with pytest.raises(ValueError):
        AnyWorkflowPauseSource()
    with pytest.raises(ValueError):
        AnyWorkflowPauseSource(object())
    with pytest.raises(ValueError):
        AnyWorkflowPauseSource(WorkflowPauseController()).is_pause_requested(" ")
