import pytest

from w_agent import (
    CancellationToken,
    DagWorkflowDefinition,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    StateGraphDefinition,
    WorkflowCheckpointStatus,
    WorkflowContext,
    WorkflowEventType,
    WorkflowNode,
    WorkflowNodeResult,
    WorkflowResumeConflictError,
    WorkflowRegistry,
    WorkflowStopReason,
    WorkflowStoreError,
)


@pytest.mark.asyncio
async def test_dag_runs_ready_nodes_in_definition_order_and_merges_state():
    calls = []

    def summarize(context):
        calls.append(context.node)
        return WorkflowNodeResult(
            output=context.state["value"] * 2,
            state_updates={"summary": "ready"},
        )

    def extract(context):
        calls.append(context.node)
        return WorkflowNodeResult(
            output=context.input["value"],
            state_updates={"value": context.input["value"]},
        )

    definition = DagWorkflowDefinition(
        "document-pipeline",
        (
            WorkflowNode("summarize", summarize),
            WorkflowNode("extract", extract),
        ),
        {"summarize": ("extract",)},
    )

    result = await LocalWorkflowEngine().start(
        definition,
        WorkflowContext("dag-1", input={"value": 4}),
    )

    assert result.stop_reason == WorkflowStopReason.COMPLETED
    assert result.output == 8
    assert result.state == {"value": 4, "summary": "ready"}
    assert result.outputs == {"extract": 4, "summarize": 8}
    assert result.completed_nodes == ("extract", "summarize")
    assert calls == ["extract", "summarize"]
    assert [event.sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )


def test_dag_rejects_cycles_and_unknown_dependencies():
    node_a = WorkflowNode("a", lambda context: None)
    node_b = WorkflowNode("b", lambda context: None)

    with pytest.raises(ValueError, match="cycle"):
        DagWorkflowDefinition(
            "cyclic",
            (node_a, node_b),
            {"a": ("b",), "b": ("a",)},
        )
    with pytest.raises(ValueError, match="unknown"):
        DagWorkflowDefinition("unknown", (node_a,), {"a": ("missing",)})


@pytest.mark.asyncio
async def test_state_graph_uses_dynamic_transition_and_bounds_steps():
    def route(context):
        return WorkflowNodeResult(next_node=context.input["route"])

    definition = StateGraphDefinition(
        "router",
        (
            WorkflowNode("route", route),
            WorkflowNode("fast", lambda context: "fast-result"),
            WorkflowNode("slow", lambda context: "slow-result"),
        ),
        entry="route",
        transitions={"fast": None, "slow": None},
        max_steps=3,
    )
    result = await LocalWorkflowEngine().start(
        definition,
        WorkflowContext("graph-1", input={"route": "fast"}),
    )

    assert result.stop_reason == WorkflowStopReason.COMPLETED
    assert result.output == "fast-result"
    assert result.completed_nodes == ("route", "fast")

    looping = StateGraphDefinition(
        "loop",
        (WorkflowNode("again", lambda context: None),),
        entry="again",
        transitions={"again": "again"},
        max_steps=2,
    )
    bounded = await LocalWorkflowEngine().start(
        looping,
        WorkflowContext("graph-2"),
    )
    assert bounded.stop_reason == WorkflowStopReason.MAX_STEPS
    assert bounded.completed_nodes == ("again", "again")
    assert bounded.checkpoint_id is None


@pytest.mark.asyncio
async def test_python_workflow_resumes_from_explicit_handler_boundary(tmp_path):
    seen = []

    def scripted(context):
        seen.append((context.resume_count, dict(context.metadata)))
        if context.resume_count == 0:
            return WorkflowNodeResult(
                output="waiting",
                state_updates={"draft": "saved"},
                pause=True,
            )
        return WorkflowNodeResult(
            output=f"published:{context.state['draft']}",
            state_updates={"published": True},
        )

    definition = PythonWorkflowDefinition("scripted", scripted)
    store = JsonlWorkflowStore(tmp_path)
    first = await LocalWorkflowEngine(store).start(
        definition,
        WorkflowContext(
            "python-1",
            metadata={"extension": "kept"},
        ),
    )

    assert first.stop_reason == WorkflowStopReason.PAUSED
    assert first.checkpoint_id == "python-1"
    checkpoint = await store.load_checkpoint("python-1")
    assert checkpoint is not None
    assert checkpoint.status == WorkflowCheckpointStatus.PAUSED

    restarted_store = JsonlWorkflowStore(tmp_path)
    resumed = await LocalWorkflowEngine(restarted_store).resume(
        definition,
        "python-1",
    )

    assert resumed.stop_reason == WorkflowStopReason.COMPLETED
    assert resumed.output == "published:saved"
    assert resumed.state == {"draft": "saved", "published": True}
    assert seen == [(0, {"extension": "kept"}), (1, {"extension": "kept"})]
    assert await restarted_store.load_checkpoint("python-1") is None


@pytest.mark.asyncio
async def test_jsonl_restart_does_not_repeat_completed_dag_node(tmp_path):
    calls = []

    def prepare(context):
        calls.append("prepare")
        return WorkflowNodeResult(
            output="prepared",
            state_updates={"prepared": True},
            pause=True,
        )

    def publish(context):
        calls.append("publish")
        return f"published:{context.outputs['prepare']}"

    definition = DagWorkflowDefinition(
        "release",
        (WorkflowNode("prepare", prepare), WorkflowNode("publish", publish)),
        {"publish": ("prepare",)},
        version="2",
    )
    first_store = JsonlWorkflowStore(tmp_path)
    paused = await LocalWorkflowEngine(first_store).start(
        definition,
        WorkflowContext("release-1"),
    )
    assert paused.completed_nodes == ("prepare",)

    resumed = await LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).resume(
        definition,
        "release-1",
    )

    assert resumed.stop_reason == WorkflowStopReason.COMPLETED
    assert resumed.output == "published:prepared"
    assert calls == ["prepare", "publish"]
    assert any(
        event.type == WorkflowEventType.WORKFLOW_RESUMED for event in resumed.events
    )


@pytest.mark.asyncio
async def test_claimed_checkpoint_refuses_uncertain_node_replay(tmp_path):
    calls = []

    def handler(context):
        calls.append(context.resume_count)
        return WorkflowNodeResult(pause=True)

    definition = PythonWorkflowDefinition("uncertain", handler)
    store = JsonlWorkflowStore(tmp_path)
    await LocalWorkflowEngine(store).start(
        definition,
        WorkflowContext("uncertain-1"),
    )
    await store.claim_checkpoint("uncertain-1")

    with pytest.raises(WorkflowResumeConflictError, match="uncertain"):
        await LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).resume(
            definition,
            "uncertain-1",
        )
    assert calls == [0]


@pytest.mark.asyncio
async def test_cancellation_stops_at_boundary_and_can_resume():
    calls = []
    definition = DagWorkflowDefinition(
        "cancel",
        (WorkflowNode("work", lambda context: calls.append("work") or "done"),),
    )
    token = CancellationToken()
    token.cancel()
    engine = LocalWorkflowEngine()

    cancelled = await engine.start(
        definition,
        WorkflowContext("cancel-1", cancellation=token),
    )
    assert cancelled.stop_reason == WorkflowStopReason.CANCELLED
    assert calls == []

    resumed = await engine.resume(definition, "cancel-1")
    assert resumed.stop_reason == WorkflowStopReason.COMPLETED
    assert calls == ["work"]


@pytest.mark.asyncio
async def test_node_failure_is_sanitized_and_fails_closed(tmp_path):
    def explode(context):
        raise RuntimeError("secret credential value")

    definition = DagWorkflowDefinition(
        "failure",
        (WorkflowNode("explode", explode),),
    )
    store = JsonlWorkflowStore(tmp_path)
    failed = await LocalWorkflowEngine(store).start(
        definition,
        WorkflowContext("failure-1"),
    )

    assert failed.stop_reason == WorkflowStopReason.FAILED
    assert failed.failure == "node-execution-failed"
    assert "secret credential value" not in str(failed.events)
    checkpoint = await store.load_checkpoint("failure-1")
    assert checkpoint is not None
    assert checkpoint.status == WorkflowCheckpointStatus.RESUMING
    with pytest.raises(WorkflowResumeConflictError):
        await LocalWorkflowEngine(store).resume(definition, "failure-1")


@pytest.mark.asyncio
async def test_resume_rejects_changed_definition_and_unsafe_run_id(tmp_path):
    definition = PythonWorkflowDefinition(
        "versioned",
        lambda context: WorkflowNodeResult(pause=True),
        version="1",
    )
    store = JsonlWorkflowStore(tmp_path)
    await LocalWorkflowEngine(store).start(
        definition,
        WorkflowContext("versioned-1"),
    )

    with pytest.raises(WorkflowStoreError, match="differs"):
        await LocalWorkflowEngine(store).resume(
            PythonWorkflowDefinition(
                "versioned",
                lambda context: "changed",
                version="2",
            ),
            "versioned-1",
        )
    with pytest.raises(ValueError, match="safe"):
        await LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).start(
            definition,
            WorkflowContext("../escape"),
        )


def test_workflow_definitions_use_shared_versioned_registry():
    registry = WorkflowRegistry()
    version_1 = PythonWorkflowDefinition("review", lambda context: "v1", version="1")
    version_2 = PythonWorkflowDefinition("review", lambda context: "v2", version="2")
    first = registry.register(version_1)
    registry.register(version_2)

    assert registry.definition("review") is version_2
    assert registry.definition("review", version="<2") is version_1
    assert registry.definitions() == (version_2,)

    first.dispose()
    with pytest.raises(ValueError, match="must match"):
        registry.register(version_2, version="3")
