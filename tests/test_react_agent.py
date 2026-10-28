import pytest

from w_agent import (
    AgentDefinition,
    AudioContent,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    InvocationPolicy,
    ImageContent,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelError,
    ModelExecutor,
    ModelFailure,
    ModelFailureKind,
    ModelMessage,
    ModelRequest,
    ModelRegistry,
    ModelRouter,
    NativeCursorRecovery,
    JsonlRunStore,
    CostBudget,
    CostEstimate,
    CharacterTokenEstimator,
    ModelCost,
    ModelPrice,
    PriceTable,
    PricingCatalog,
    ReactAgentLoop,
    RunResumeConflictError,
    RunContext,
    RunEventType,
    StopReason,
    StandardMultimodalEventEncoder,
    TextContent,
    TextDelta,
    TokenBudget,
    TokenEstimate,
    TokenEstimationError,
    TokenUsage,
    ToolCallContent,
    ToolCallDelta,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolResultContent,
    ToolSideEffect,
    ToolBinding,
    ToolContinuation,
    ToolContinuationError,
    ToolDefinition,
    CheckpointStatus,
    UsageEvent,
    WeightedRoutingPolicy,
    python_tool,
    safe_run_event_to_dict,
)


class AgentProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.descriptor = ModelDescriptor(
            "fake",
            "chat",
            frozenset(
                {
                    ModelCapability.TEXT_INPUT,
                    ModelCapability.TEXT_OUTPUT,
                    ModelCapability.STREAMING,
                    ModelCapability.TOOL_CALLING,
                }
            ),
        )

    async def list_models(self):
        return (self.descriptor,)

    async def resolve(self, model):
        assert model == "chat"
        return self.descriptor

    async def stream(self, request, *, cancellation=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, ModelFailure):
            raise ModelError(response)
        blocks, reason = response[:2]
        for index, block in enumerate(blocks):
            yield BlockStart(index, block.type)
            if isinstance(block, TextContent):
                yield TextDelta(index, block.text)
            elif isinstance(block, ToolCallContent):
                yield ToolCallDelta(index, block.id, block.name, block.arguments)
            yield BlockEnd(index, block)
        if len(response) == 3:
            yield UsageEvent(response[2])
        yield FinishEvent(reason)


def _loop(
    responses,
    binding,
    *,
    store=None,
    policy=None,
    pricing=None,
    token_estimator=None,
    cost_estimator=None,
    stream_recovery=None,
    output_event_encoder=None,
    tool_result_event_encoder=None,
):
    provider = AgentProvider(responses)
    models = ModelRegistry()
    models.register("fake", provider)
    router = ModelRouter(
        models,
        WeightedRoutingPolicy(preferred_providers=("fake",)),
    )
    model_executor = ModelExecutor(models, router, policy)
    tools = ToolRegistry()
    tools.register_binding(binding)
    tool_executor = ToolExecutor(tools)
    return ReactAgentLoop(
        model_executor,
        tools,
        tool_executor,
        store=store,
        pricing=pricing,
        token_estimator=token_estimator,
        cost_estimator=cost_estimator,
        stream_recovery=stream_recovery,
        output_event_encoder=output_event_encoder,
        tool_result_event_encoder=tool_result_event_encoder,
    ), provider


def _context(**kwargs):
    return RunContext(
        "run-1",
        (ModelMessage.text(MessageRole.USER, "calculate"),),
        **kwargs,
    )


@pytest.mark.parametrize("record", [False, True])
async def test_tool_result_recording_is_opt_in_and_safe_projection_hides_body(record):
    writes = []
    def write():
        writes.append(True)
        return "PRIVATE_RESULT"
    loop, provider = _loop([
        ((ToolCallContent("call", "write", "{}"),), FinishReason.TOOL_CALLS),
        ((TextContent("done"),), FinishReason.STOP),
    ], python_tool(write))
    result = await loop.run(AgentDefinition("agent", emit_tool_results=record), _context())
    event = next(e for e in result.events if e.type is RunEventType.TOOL_COMPLETED)
    assert result.stop_reason is StopReason.COMPLETED and writes == [True]
    assert len(provider.requests) == 2
    if record:
        assert event.data["result_recording"] == "recorded"
        assert event.data["result"] == {"kind": "text", "text": "PRIVATE_RESULT", "is_error": False}
    else:
        assert "result_recording" not in event.data and "result" not in event.data
    assert "PRIVATE_RESULT" not in str(safe_run_event_to_dict(event))
    assert provider.requests[1].messages[-1].content[0].content == "PRIVATE_RESULT"


async def test_failed_tool_records_only_its_model_visible_error():
    def broken():
        raise RuntimeError("PRIVATE_EXCEPTION")
    loop, provider = _loop([
        ((ToolCallContent("call", "broken", "{}"),), FinishReason.TOOL_CALLS),
        ((TextContent("done"),), FinishReason.STOP),
    ], python_tool(broken))
    result = await loop.run(AgentDefinition("agent", emit_tool_results=True), _context())
    event = next(e for e in result.events if e.type is RunEventType.TOOL_COMPLETED)
    model_result = provider.requests[1].messages[-1].content[0]
    assert event.data["result"]["text"] == model_result.content
    assert event.data["result"]["is_error"] is True
    assert "PRIVATE_EXCEPTION" not in str(dict(event.data))


@pytest.mark.parametrize("mode", ["off", "omit", "raise", "oversize", "invalid", "redact"])
async def test_result_encoder_failure_or_omission_never_replays_completed_tool(mode):
    writes, encoded = [], []
    def write():
        writes.append(True)
        return "PRIVATE_RESULT"
    class Encoder:
        def encode(self, result, *, name):
            encoded.append((result.content, name))
            if mode == "omit":
                return None
            if mode in {"off", "raise"}:
                raise RuntimeError("PRIVATE_ENCODER_ERROR")
            if mode == "oversize":
                return {"text": "x" * 1024}
            if mode == "invalid":
                return {"value": float("nan")}
            return {"kind": "application.redacted", "text": "[MASKED]"}
    loop, provider = _loop([
        ((ToolCallContent("call", "write", "{}"),), FinishReason.TOOL_CALLS),
        ((TextContent("done"),), FinishReason.STOP),
    ], python_tool(write), tool_result_event_encoder=Encoder())
    result = await loop.run(AgentDefinition(
        "agent", emit_tool_results=mode != "off", max_tool_result_event_bytes=128,
    ), _context())
    event = next(e for e in result.events if e.type is RunEventType.TOOL_COMPLETED)
    assert result.stop_reason is StopReason.COMPLETED and writes == [True]
    assert provider.requests[1].messages[-1].content[0].content == "PRIVATE_RESULT"
    assert "PRIVATE" not in str(dict(event.data))
    if mode == "off":
        assert encoded == [] and "result_recording" not in event.data
    else:
        assert encoded == [("PRIVATE_RESULT", "write")]
        expected = "recorded" if mode == "redact" else "omitted" if mode == "omit" else "failed"
        assert event.data["result_recording"] == expected
        assert ("result" in event.data) is (mode == "redact")


@pytest.mark.parametrize("encoder_fails", [False, True])
async def test_tool_result_recording_survives_continuation_restart_without_recording_ticket(tmp_path, encoder_fails):
    starts, resumes = [], []
    async def prepare(arguments, context):
        starts.append(True)
        return ToolContinuation("application.wait", {"PRIVATE_TICKET": "reference"})
    async def resume(arguments, ticket, context):
        resumes.append(True)
        return "PRIVATE_FINISHED"
    binding = ToolBinding(ToolDefinition("wait", "wait", {"type": "object"}), prepare, resume_handler=resume)
    first, first_provider = _loop([
        ((ToolCallContent("call", "wait", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=JsonlRunStore(tmp_path))
    waiting = await first.run(AgentDefinition(
        "agent", emit_tool_results=True, max_tool_result_event_bytes=2048,
    ), _context())
    checkpoint = await first.store.load_checkpoint("run-1")
    assert checkpoint.definition.emit_tool_results is True
    assert checkpoint.definition.max_tool_result_event_bytes == 2048
    boundary = next(e for e in waiting.events if e.type is RunEventType.TOOL_COMPLETED)
    assert "result" not in boundary.data and "result_recording" not in boundary.data
    class Encoder:
        def encode(self, result, *, name):
            raise RuntimeError("PRIVATE_ENCODING")
    restarted, provider = _loop([
        ((TextContent("done"),), FinishReason.STOP),
    ], binding, store=JsonlRunStore(tmp_path), tool_result_event_encoder=Encoder() if encoder_fails else None)
    finished = await restarted.resume("run-1", tool_context=ToolExecutionContext(approved_call_ids={"call"}))
    assert finished.stop_reason is StopReason.COMPLETED and starts == resumes == [True]
    assert len(first_provider.requests) == len(provider.requests) == 1
    completed = [e for e in await restarted.store.events("run-1") if e.type is RunEventType.TOOL_COMPLETED]
    assert completed[-1].data["result_recording"] == ("failed" if encoder_fails else "recorded")
    assert "PRIVATE_TICKET" not in str([dict(e.data) for e in completed])
    assert await restarted.store.load_checkpoint("run-1") is None


async def test_tool_result_event_store_failure_retains_uncertain_continuation(tmp_path):
    from w_agent import RunStoreError
    class FailingStore(JsonlRunStore):
        async def append(self, event):
            if event.type is RunEventType.TOOL_COMPLETED and event.data.get("result_recording") == "recorded":
                raise RunStoreError("store unavailable")
            await super().append(event)
    starts, resumes = [], []
    async def prepare(arguments, context):
        starts.append(True)
        return ToolContinuation("application.wait", {})
    async def resume(arguments, ticket, context):
        resumes.append(True)
        return "done"
    binding = ToolBinding(ToolDefinition("wait", "wait", {"type": "object"}), prepare, resume_handler=resume)
    loop, provider = _loop([
        ((ToolCallContent("call", "wait", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=FailingStore(tmp_path))
    await loop.run(AgentDefinition("agent", emit_tool_results=True), _context())
    authority = ToolExecutionContext(approved_call_ids={"call"})
    with pytest.raises(RunStoreError):
        await loop.resume("run-1", tool_context=authority)
    assert (await loop.store.load_checkpoint("run-1")).status is CheckpointStatus.RESUMING
    with pytest.raises(RunResumeConflictError):
        await loop.resume("run-1", tool_context=authority)
    assert starts == resumes == [True] and len(provider.requests) == 1


@pytest.mark.parametrize("coordinated", [False, True])
async def test_workflow_tool_suspends_parent_and_requires_separate_child_authority(tmp_path, coordinated):
    from contextlib import asynccontextmanager
    from w_agent import (
        DagWorkflowDefinition, JsonlWorkflowStore, LocalWorkflowEngine,
        ScopePath, WorkflowApprovalGrants, WorkflowNode, approval_agent_workflow_node,
        resumable_workflow_tool, review_workflow_approvals,
        resume_workflow_tool_approval, review_workflow_tool_approvals,
    )

    writes, after = [], []
    def write():
        writes.append("write")
        return "written"
    child_store = JsonlRunStore(tmp_path / "inner-agent")
    inner, inner_provider = _loop([
        ((ToolCallContent("inner-call", "write", "{}"),), FinishReason.TOOL_CALLS),
        ((TextContent("child done"),), FinishReason.STOP),
    ], python_tool(write, side_effect=ToolSideEffect.WRITE,
                   required_permissions=frozenset({"write.allowed"})), store=child_store)
    grants = WorkflowApprovalGrants()
    node = approval_agent_workflow_node(
        "agent", inner, AgentDefinition("inner"), child_store,
        tool_context=lambda ctx: ToolExecutionContext(permissions={"write.allowed"}),
        approval_context=grants,
    )
    workflow = DagWorkflowDefinition("child", (node, WorkflowNode("after", lambda _: after.append(True))),
                                     {"after": ("agent",)})
    workflow_store = JsonlWorkflowStore(tmp_path / "workflow")
    binding = resumable_workflow_tool(LocalWorkflowEngine(workflow_store), workflow, workflow_store)
    parent_store = JsonlRunStore(tmp_path / "parent")
    parent, initial_provider = _loop([
        ((ToolCallContent("outer-call", "run_child", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=parent_store)
    authority = ToolExecutionContext(permissions={"workflow.execute"}, approved_call_ids={"outer-call"},
                                     agent_run_id="FORGED_PARENT")
    result = await parent.run(AgentDefinition("outer"), _context(tool_context=authority))
    assert result.stop_reason is StopReason.NEEDS_APPROVAL
    ticket = (await parent_store.load_checkpoint("run-1")).tool_continuation
    assert ticket.payload["reference"]["agent_run_id"] == "run-1"
    child_id = ticket.payload["reference"]["workflow_run_id"]
    assert await workflow_store.events(child_id) == ()
    assert inner_provider.requests == [] and writes == []

    # Fresh parent/store/binding resumes from persisted ticket without model replay.
    fresh_workflow_store = JsonlWorkflowStore(tmp_path / "workflow")
    fresh_binding = resumable_workflow_tool(LocalWorkflowEngine(fresh_workflow_store), workflow, fresh_workflow_store)
    resumed, provider = _loop([((TextContent("all done"),), FinishReason.STOP)], fresh_binding,
                              store=JsonlRunStore(tmp_path / "parent"))
    stopped = await resumed.resume("run-1", tool_context=authority)
    assert stopped.stop_reason is StopReason.NEEDS_APPROVAL
    assert writes == [] and after == [] and provider.requests == []
    assert len(inner_provider.requests) == 1
    stopped_again = await resumed.resume("run-1", tool_context=authority)
    assert stopped_again.stop_reason is StopReason.NEEDS_APPROVAL
    assert writes == [] and len(inner_provider.requests) == 1
    reviews = await review_workflow_approvals(fresh_workflow_store, child_store, child_id)
    reference = reviews[0].reference
    if coordinated:
        selected, = await review_workflow_tool_approvals(resumed.store, fresh_workflow_store, child_store, "run-1")
        service_providers = []
        @asynccontextmanager
        async def factory(context):
            approval_node = approval_agent_workflow_node(
                "agent", inner, context.child_definition, context.child_store,
                approval_context=context.grants,
            )
            assembled = DagWorkflowDefinition("child", (
                approval_node, WorkflowNode("after", lambda _: after.append(True)),
            ), {"after": ("agent",)})
            tool = resumable_workflow_tool(LocalWorkflowEngine(context.workflow_store), assembled, context.workflow_store)
            parent_loop, final_provider = _loop([((TextContent("all done"),), FinishReason.STOP)], tool,
                                               store=context.parent_store)
            service_providers.append(final_provider)
            yield parent_loop
        completed = await resume_workflow_tool_approval(
            resumed.store, fresh_workflow_store, child_store, selected, factory,
            parent_permissions={"workflow.execute"}, child_permissions={"write.allowed"},
        )
        assert provider.requests == []
        provider = service_providers[0]
    else:
        grants.grant(reference, scope=ScopePath.application(), permissions={"write.allowed"})
        completed = await resumed.resume("run-1", tool_context=authority)
    assert completed.stop_reason is StopReason.COMPLETED
    assert writes == ["write"] and after == [True]
    assert len(initial_provider.requests) == 1 and len(provider.requests) == 1
    assert len(inner_provider.requests) == 2 and completed.tool_calls == 1
    assert await resumed.store.load_checkpoint("run-1") is None


async def test_failed_workflow_child_keeps_parent_uncertain_without_model_success(tmp_path):
    from w_agent import JsonlWorkflowStore, LocalWorkflowEngine, PythonWorkflowDefinition, resumable_workflow_tool

    calls = []
    def fail(context):
        calls.append("entered")
        raise RuntimeError("PRIVATE_CHILD_ERROR")
    store = JsonlWorkflowStore(tmp_path / "workflow")
    binding = resumable_workflow_tool(LocalWorkflowEngine(store), PythonWorkflowDefinition("child", fail), store)
    loop, provider = _loop([
        ((ToolCallContent("call", "run_child", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=JsonlRunStore(tmp_path / "parent"))
    authority = ToolExecutionContext(permissions={"workflow.execute"}, approved_call_ids={"call"})
    await loop.run(AgentDefinition("agent"), _context(tool_context=authority))
    with pytest.raises(ToolContinuationError) as caught:
        await loop.resume("run-1", tool_context=authority)
    assert "PRIVATE" not in str(caught.value)
    checkpoint = await loop.store.load_checkpoint("run-1")
    assert checkpoint.status is CheckpointStatus.RESUMING
    assert checkpoint.tool_continuation is not None
    assert not any(message.role is MessageRole.TOOL for message in checkpoint.messages)
    with pytest.raises(RunResumeConflictError):
        await loop.resume("run-1", tool_context=authority)
    assert calls == ["entered"] and len(provider.requests) == 1


async def test_tool_continuation_survives_restart_without_start_or_model_replay(tmp_path):
    starts, resumes = [], []
    async def prepare(arguments, context):
        starts.append(context.invocation.id)
        return ToolContinuation("workflow.reference", {"child": "child-1", "phase": 0})
    async def resume(arguments, continuation, context):
        resumes.append(continuation.payload["phase"])
        if continuation.payload["phase"] == 0:
            return ToolContinuation("workflow.reference", {"child": "child-1", "phase": 1})
        return "finished"
    binding = ToolBinding(
        ToolDefinition("wait", "wait", {"type": "object"}), prepare, resume_handler=resume,
    )
    first, initial_provider = _loop([
        ((ToolCallContent("call", "wait", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=JsonlRunStore(tmp_path))
    waiting = await first.run(AgentDefinition("agent"), _context())
    assert waiting.stop_reason is StopReason.NEEDS_APPROVAL
    assert starts == ["call"] and resumes == [] and len(initial_provider.requests) == 1
    assert not any(message.role is MessageRole.TOOL for message in waiting.messages)
    stored = await JsonlRunStore(tmp_path).load_checkpoint("run-1")
    assert stored.schema_version == 2 and stored.tool_continuation.payload["phase"] == 0

    restarted, provider = _loop([
        ((TextContent("done"),), FinishReason.STOP),
    ], binding, store=JsonlRunStore(tmp_path))
    held = await restarted.resume("run-1", tool_context=ToolExecutionContext())
    assert held.stop_reason is StopReason.NEEDS_APPROVAL and resumes == []
    assert provider.requests == []
    authority = ToolExecutionContext(approved_call_ids={"call"})
    second = await restarted.resume("run-1", tool_context=authority)
    assert second.stop_reason is StopReason.NEEDS_APPROVAL
    assert starts == ["call"] and resumes == [0] and provider.requests == []
    finished = await restarted.resume("run-1", tool_context=authority)
    assert finished.stop_reason is StopReason.COMPLETED
    assert starts == ["call"] and resumes == [0, 1] and len(provider.requests) == 1
    assert finished.tool_calls == 1
    assert await restarted.store.load_checkpoint("run-1") is None


@pytest.mark.parametrize("unsupported", [False, True])
async def test_failed_continuation_retains_uncertain_parent(tmp_path, unsupported):
    async def prepare(arguments, context):
        return ToolContinuation("kind", {"child": "child"})
    async def resume(arguments, continuation, context):
        raise RuntimeError("PRIVATE_CHILD_FAILURE")
    binding = ToolBinding(ToolDefinition("wait", "wait", {"type": "object"}), prepare,
                          resume_handler=resume)
    loop, provider = _loop([
        ((ToolCallContent("call", "wait", "{}"),), FinishReason.TOOL_CALLS),
    ], binding, store=JsonlRunStore(tmp_path))
    await loop.run(AgentDefinition("agent"), _context())
    if unsupported:
        class ExecutorWithoutResume:
            async def execute(self, call, context=None):
                pytest.fail("continuation must not replay execute")
        loop.tool_executor = ExecutorWithoutResume()
    with pytest.raises(ToolContinuationError) as caught:
        await loop.resume("run-1", tool_context=ToolExecutionContext(approved_call_ids={"call"}))
    assert "PRIVATE" not in str(caught.value)
    checkpoint = await loop.store.load_checkpoint("run-1")
    assert checkpoint.status is CheckpointStatus.RESUMING
    assert checkpoint.tool_continuation is not None and checkpoint.schema_version == 2
    assert len(provider.requests) == 1
    with pytest.raises(RunResumeConflictError):
        await loop.resume("run-1", tool_context=ToolExecutionContext(approved_call_ids={"call"}))


@pytest.mark.asyncio
async def test_react_loop_runs_model_tool_model_to_completion():
    def add(left: int, right: int) -> int:
        return left + right

    loop, provider = _loop(
        [
            (
                (ToolCallContent("tool-1", "add", '{"left":2,"right":3}'),),
                FinishReason.TOOL_CALLS,
            ),
            ((TextContent("The answer is 5."),), FinishReason.STOP),
        ],
        python_tool(add),
    )

    result = await loop.run(
        AgentDefinition("calculator", system_prompt="Use tools."),
        _context(),
    )

    assert result.stop_reason == StopReason.COMPLETED
    assert result.output == "The answer is 5."
    assert (result.steps, result.tool_calls) == (2, 1)
    assert [event.sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    assert result.events[-1].type == RunEventType.RUN_COMPLETED
    assert provider.requests[0].tools[0].name == "add"
    tool_message = provider.requests[1].messages[-1]
    assert isinstance(tool_message.content[0], ToolResultContent)
    assert tool_message.content[0].content == "5"


@pytest.mark.asyncio
async def test_react_stream_is_single_use_and_exposes_final_result():
    loop, _ = _loop(
        [((TextContent("done"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
    )
    execution = loop.stream(AgentDefinition("simple"), _context())

    events = [event async for event in execution]

    assert events[0].type == RunEventType.RUN_STARTED
    assert execution.result is not None
    assert execution.result.output == "done"
    with pytest.raises(RuntimeError, match="single-use"):
        execution.__aiter__()


@pytest.mark.asyncio
async def test_react_opt_in_projects_model_text_deltas_before_completion():
    loop, _ = _loop(
        [((TextContent("streamed"),), FinishReason.STOP, TokenUsage(3, 2))],
        python_tool(lambda: "unused", name="unused"),
    )

    result = await loop.run(
        AgentDefinition("streaming", emit_text_deltas=True),
        _context(),
    )

    event_types = [event.type for event in result.events]
    delta = next(
        event
        for event in result.events
        if event.type is RunEventType.MODEL_TEXT_DELTA
    )
    assert delta.data == {"step": 1, "block_index": 0, "text": "streamed"}
    assert event_types.index(RunEventType.MODEL_TEXT_DELTA) < event_types.index(
        RunEventType.MODEL_COMPLETED
    )
    assert result.output == "streamed"


@pytest.mark.asyncio
async def test_react_model_text_deltas_are_disabled_by_default():
    loop, _ = _loop(
        [((TextContent("collected"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
    )

    result = await loop.run(AgentDefinition("collected"), _context())

    assert all(
        event.type is not RunEventType.MODEL_TEXT_DELTA for event in result.events
    )
    assert all(
        event.type is not RunEventType.MODEL_TOOL_CALL_DELTA
        for event in result.events
    )
    assert all(
        event.type is not RunEventType.MODEL_OUTPUT_BLOCK
        for event in result.events
    )


@pytest.mark.asyncio
async def test_react_explicitly_persists_provider_neutral_media_outputs():
    loop, _ = _loop(
        [
            (
                (
                    ImageContent(data=b"png", media_type="image/png"),
                    AudioContent(url="https://media.test/reply.wav"),
                ),
                FinishReason.STOP,
            )
        ],
        python_tool(lambda: "unused", name="unused"),
    )

    result = await loop.run(
        AgentDefinition("media", emit_output_blocks=True),
        _context(),
    )

    events = [
        event
        for event in result.events
        if event.type is RunEventType.MODEL_OUTPUT_BLOCK
    ]
    assert [event.data["block"]["kind"] for event in events] == [
        "image",
        "audio",
    ]
    assert events[0].data["block"]["data_base64"] == "cG5n"
    assert events[0].data["block"]["size_bytes"] == 3
    assert events[1].data["block"]["url"] == (
        "https://media.test/reply.wav"
    )
    completed = next(
        event
        for event in result.events
        if event.type is RunEventType.MODEL_COMPLETED
    )
    assert events[-1].sequence < completed.sequence


@pytest.mark.asyncio
async def test_react_stops_cleanly_when_explicit_media_encoding_fails():
    loop, _ = _loop(
        [
            (
                (ImageContent(data=b"too-large", media_type="image/png"),),
                FinishReason.STOP,
                TokenUsage(3, 2),
            )
        ],
        python_tool(lambda: "unused", name="unused"),
        output_event_encoder=StandardMultimodalEventEncoder(
            max_inline_bytes=2
        ),
    )

    result = await loop.run(
        AgentDefinition("media", emit_output_blocks=True),
        _context(),
    )

    assert result.stop_reason is StopReason.OUTPUT_EVENT_ERROR
    failure = next(
        event
        for event in result.events
        if event.type is RunEventType.MODEL_OUTPUT_BLOCK_FAILED
    )
    assert failure.data == {
        "step": 1,
        "block_index": 0,
        "code": "output-event-encoding-failed",
    }
    assert result.usage == TokenUsage(3, 2)
    assert result.events[-1].type is RunEventType.RUN_COMPLETED


@pytest.mark.asyncio
async def test_react_tool_deltas_require_separate_opt_in_and_safe_view_hides_body(
    tmp_path,
):
    store = JsonlRunStore(tmp_path)
    loop, _ = _loop(
        [
            (
                (ToolCallContent("call-1", "lookup", '{"secret":"hidden"}'),),
                FinishReason.TOOL_CALLS,
            ),
            ((TextContent("done"),), FinishReason.STOP),
        ],
        python_tool(lambda secret: "ok", name="lookup"),
        store=store,
    )

    result = await loop.run(
        AgentDefinition("tool-delta", emit_tool_call_deltas=True),
        _context(),
    )

    deltas = [
        event
        for event in result.events
        if event.type is RunEventType.MODEL_TOOL_CALL_DELTA
    ]
    assert result.stop_reason is StopReason.COMPLETED
    assert len(deltas) == 1
    assert deltas[0].data["call_id"] == "call-1"
    assert deltas[0].data["arguments_delta"] == '{"secret":"hidden"}'
    assert all(
        event.type is not RunEventType.MODEL_TEXT_DELTA
        for event in result.events
    )
    assert safe_run_event_to_dict(deltas[0])["data"] == {
        "step": 1,
        "block_index": 0,
    }
    persisted = await JsonlRunStore(tmp_path).events("run-1")
    assert (
        next(
            event
            for event in persisted
            if event.type is RunEventType.MODEL_TOOL_CALL_DELTA
        ).data["arguments_delta"]
        == '{"secret":"hidden"}'
    )


@pytest.mark.asyncio
async def test_react_loop_stops_for_explicit_tool_approval():
    calls = []

    def save(text: str) -> str:
        calls.append(text)
        return "saved"

    loop, _ = _loop(
        [
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
            )
        ],
        python_tool(save, side_effect=ToolSideEffect.WRITE),
    )

    result = await loop.run(AgentDefinition("writer"), _context())

    assert result.stop_reason == StopReason.NEEDS_APPROVAL
    assert result.pending_tool_call is not None
    assert result.pending_tool_call.id == "write-1"
    assert calls == []


@pytest.mark.asyncio
async def test_react_loop_uses_local_approval_and_permission_context():
    calls = []

    def save(text: str) -> str:
        calls.append(text)
        return "saved"

    loop, _ = _loop(
        [
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
            ),
            ((TextContent("saved"),), FinishReason.STOP),
        ],
        python_tool(
            save,
            side_effect=ToolSideEffect.WRITE,
            required_permissions=frozenset({"notes.write"}),
        ),
    )
    context = _context(
        tool_context=ToolExecutionContext(
            permissions=frozenset({"notes.write"}),
            approved_call_ids=frozenset({"write-1"}),
        )
    )

    result = await loop.run(AgentDefinition("writer"), context)

    assert result.stop_reason == StopReason.COMPLETED
    assert calls == ["value"]


@pytest.mark.asyncio
async def test_react_loop_returns_tool_argument_errors_to_model():
    calls = 0

    def no_args() -> str:
        nonlocal calls
        calls += 1
        return "not called"

    loop, provider = _loop(
        [
            (
                (ToolCallContent("bad-1", "no_args", "not-json"),),
                FinishReason.TOOL_CALLS,
            ),
            ((TextContent("recovered"),), FinishReason.STOP),
        ],
        python_tool(no_args),
    )

    result = await loop.run(AgentDefinition("recover"), _context())

    assert result.stop_reason == StopReason.COMPLETED
    assert calls == 0
    tool_result = provider.requests[1].messages[-1].content[0]
    assert isinstance(tool_result, ToolResultContent)
    assert tool_result.is_error is True
    assert "invalid-tool-arguments" in tool_result.content


@pytest.mark.asyncio
async def test_react_loop_enforces_step_and_tool_budgets():
    def ping() -> str:
        return "pong"

    loop, _ = _loop(
        [
            (
                (ToolCallContent("ping-1", "ping", "{}"),),
                FinishReason.TOOL_CALLS,
            )
        ],
        python_tool(ping),
    )
    max_steps = await loop.run(AgentDefinition("bounded", max_steps=1), _context())

    other_loop, _ = _loop(
        [
            (
                (ToolCallContent("ping-2", "ping", "{}"),),
                FinishReason.TOOL_CALLS,
            )
        ],
        python_tool(ping),
    )
    max_tools = await other_loop.run(
        AgentDefinition("bounded", max_tool_calls=0),
        _context(),
    )

    assert max_steps.stop_reason == StopReason.MAX_STEPS
    assert max_tools.stop_reason == StopReason.MAX_TOOL_CALLS


@pytest.mark.asyncio
async def test_react_loop_exposes_cumulative_input_and_output_usage():
    loop, _ = _loop(
        [
            (
                (ToolCallContent("ping-1", "ping", "{}"),),
                FinishReason.TOOL_CALLS,
                TokenUsage(10, 2, 3),
            ),
            (
                (TextContent("done"),),
                FinishReason.STOP,
                TokenUsage(12, 3, 4),
            ),
        ],
        python_tool(lambda: "pong", name="ping"),
    )

    result = await loop.run(AgentDefinition("metered"), _context())

    assert result.usage == TokenUsage(22, 5, 7)
    assert result.usage.total_tokens == 27
    assert result.model_calls == 2
    assert result.reported_usage_calls == 2
    assert result.usage_complete is True
    usage_events = [
        event for event in result.events if event.type == RunEventType.TOKEN_USAGE
    ]
    assert usage_events[-1].data["input_tokens"] == 22
    assert usage_events[-1].data["output_tokens"] == 5
    model_events = [
        event for event in result.events if event.type == RunEventType.MODEL_COMPLETED
    ]
    assert model_events[0].data["attempt_usage_complete"] is True
    assert model_events[0].data["attempts"][0]["input_tokens"] == 10
    assert model_events[1].data["attempts"][0]["output_tokens"] == 3
    assert result.events[-1].data["usage_complete"] is True


@pytest.mark.asyncio
async def test_react_loop_stops_before_tools_when_actual_usage_exceeds_budget():
    calls = 0

    def ping() -> str:
        nonlocal calls
        calls += 1
        return "pong"

    loop, provider = _loop(
        [
            (
                (ToolCallContent("ping-1", "ping", "{}"),),
                FinishReason.TOOL_CALLS,
                TokenUsage(8, 4),
            )
        ],
        python_tool(ping),
    )

    result = await loop.run(
        AgentDefinition(
            "bounded",
            max_output_tokens=3,
            token_budget=TokenBudget(max_total_tokens=10),
        ),
        _context(),
    )

    assert result.stop_reason == StopReason.TOKEN_BUDGET
    assert result.usage == TokenUsage(8, 4)
    assert calls == 0
    assert provider.requests[0].max_output_tokens == 3
    budget_event = next(
        event
        for event in result.events
        if event.type == RunEventType.TOKEN_BUDGET_STOPPED
    )
    assert budget_event.data["exceeded_limits"] == ("total_tokens",)


@pytest.mark.asyncio
async def test_react_loop_can_fail_closed_when_provider_omits_usage():
    loop, _ = _loop(
        [((TextContent("unmetered"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
    )

    result = await loop.run(
        AgentDefinition(
            "strict-metering",
            token_budget=TokenBudget(
                max_total_tokens=10,
                require_usage=True,
            ),
        ),
        _context(),
    )

    assert result.stop_reason == StopReason.TOKEN_USAGE_UNAVAILABLE
    assert result.model_calls == 1
    assert result.reported_usage_calls == 0
    assert result.usage_complete is False


@pytest.mark.asyncio
async def test_react_preflight_estimate_caps_output_and_emits_soft_warning():
    class FixedEstimator:
        async def estimate(self, request):
            return TokenEstimate(12, "fixed:v1", exact=True)

    loop, provider = _loop(
        [((TextContent("done"),), FinishReason.STOP, TokenUsage(12, 2))],
        python_tool(lambda: "unused", name="unused"),
        token_estimator=FixedEstimator(),
    )

    result = await loop.run(
        AgentDefinition(
            "estimated",
            max_output_tokens=10,
            token_budget=TokenBudget(
                max_total_tokens=20,
                require_estimate=True,
                soft_limit_ratio="0.5",
            ),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert provider.requests[0].max_output_tokens == 8
    estimated = next(
        event for event in result.events if event.type is RunEventType.TOKEN_ESTIMATED
    )
    assert estimated.data["input_tokens"] == 12
    assert estimated.data["exact"] is True
    assert estimated.data["max_output_tokens"] == 8
    warnings = [
        event
        for event in result.events
        if event.type is RunEventType.TOKEN_BUDGET_WARNING
    ]
    assert warnings[0].data["phase"] == "preflight"
    assert "total_tokens" in warnings[0].data["limits"]


@pytest.mark.asyncio
async def test_react_preflight_stops_before_request_that_fills_total_budget():
    class FixedEstimator:
        async def estimate(self, request):
            return TokenEstimate(10, "fixed:v1")

    loop, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
        token_estimator=FixedEstimator(),
    )

    result = await loop.run(
        AgentDefinition(
            "estimated",
            token_budget=TokenBudget(max_total_tokens=10),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.TOKEN_BUDGET
    assert provider.requests == []
    stopped = next(
        event
        for event in result.events
        if event.type is RunEventType.TOKEN_BUDGET_STOPPED
    )
    assert stopped.data["estimated"] is True
    assert stopped.data["exceeded_limits"] == ("total_tokens",)


@pytest.mark.asyncio
async def test_react_required_estimate_fails_closed_when_unavailable():
    loop, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
    )

    result = await loop.run(
        AgentDefinition(
            "estimated",
            token_budget=TokenBudget(require_estimate=True),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.TOKEN_ESTIMATE_UNAVAILABLE
    assert provider.requests == []
    unavailable = next(
        event
        for event in result.events
        if event.type is RunEventType.TOKEN_ESTIMATE_UNAVAILABLE
    )
    assert unavailable.data["error"] == "estimator-unavailable"


@pytest.mark.asyncio
async def test_optional_estimator_failure_is_visible_and_does_not_block():
    class FailingEstimator:
        async def estimate(self, request):
            raise TokenEstimationError("provider tokenizer unavailable")

    loop, provider = _loop(
        [((TextContent("done"),), FinishReason.STOP, TokenUsage(4, 1))],
        python_tool(lambda: "unused", name="unused"),
        token_estimator=FailingEstimator(),
    )

    result = await loop.run(AgentDefinition("estimated"), _context())

    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.requests) == 1
    unavailable = next(
        event
        for event in result.events
        if event.type is RunEventType.TOKEN_ESTIMATE_UNAVAILABLE
    )
    assert unavailable.data["error"] == "estimator-failed"


@pytest.mark.asyncio
async def test_character_estimator_is_explicit_and_rejects_multimodal_input():
    estimator = CharacterTokenEstimator(
        characters_per_token=2,
        tokens_per_message=1,
        base_tokens=1,
    )
    estimate = await estimator.estimate(
        ModelRequest(messages=(ModelMessage.text(MessageRole.USER, "abcd"),))
    )

    assert estimate.input_tokens == 6
    assert estimate.exact is False
    assert estimate.estimator.startswith("character-heuristic:v1")
    with pytest.raises(TokenEstimationError, match="image or audio"):
        await estimator.estimate(
            ModelRequest(
                messages=(
                    ModelMessage(
                        MessageRole.USER,
                        (ImageContent(url="https://example.invalid/image.png"),),
                    ),
                )
            )
        )


@pytest.mark.asyncio
async def test_react_loop_enforces_versioned_cost_budget_before_tools():
    calls = 0

    def ping() -> str:
        nonlocal calls
        calls += 1
        return "pong"

    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1000000", "1000000"),),
            ),
        )
    )
    loop, _ = _loop(
        [
            (
                (ToolCallContent("ping-1", "ping", "{}"),),
                FinishReason.TOOL_CALLS,
                TokenUsage(8, 4),
            )
        ],
        python_tool(ping),
        pricing=pricing,
    )

    result = await loop.run(
        AgentDefinition(
            "cost-bounded",
            cost_budget=CostBudget("10", "prices-v1", "USD"),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COST_BUDGET
    assert result.cost is not None
    assert result.cost.total == 12
    assert result.cost_complete is True
    assert result.priced_usage_calls == 1
    assert calls == 0
    cost_event = next(
        event for event in result.events if event.type is RunEventType.COST_USAGE
    )
    assert cost_event.data["cost"]["total"] == "12"


@pytest.mark.asyncio
async def test_cost_preflight_stops_before_model_from_replay_envelope():
    class FixedTokenEstimator:
        async def estimate(self, request):
            return TokenEstimate(3, "exact:test", exact=True)

    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1000000", "1000000"),),
            ),
        )
    )
    loop, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP, TokenUsage(3, 1))],
        python_tool(lambda: "unused", name="unused"),
        pricing=pricing,
        token_estimator=FixedTokenEstimator(),
        policy=InvocationPolicy(max_attempts_per_route=2),
    )

    result = await loop.run(
        AgentDefinition(
            "cost-preflight",
            max_output_tokens=4,
            cost_budget=CostBudget(
                "10",
                "prices-v1",
                estimate_before_call=True,
                require_estimate=True,
            ),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COST_BUDGET
    assert provider.requests == []
    estimated = next(
        event for event in result.events if event.type is RunEventType.COST_ESTIMATED
    )
    assert estimated.data["primary_attempt_cost"]["total"] == "7"
    assert estimated.data["cost"]["total"] == "14"
    assert estimated.data["projected_cost"]["total"] == "14"
    assert estimated.data["attempt_count"] == 2
    assert estimated.data["conservative"] is True


@pytest.mark.asyncio
async def test_stream_cursor_resumes_are_included_in_cost_preflight():
    class FixedTokenEstimator:
        async def estimate(self, request):
            return TokenEstimate(3, "exact:test", exact=True)

    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1000000", "1000000"),),
            ),
        )
    )
    loop, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
        pricing=pricing,
        token_estimator=FixedTokenEstimator(),
        stream_recovery=NativeCursorRecovery(max_resumes=2),
    )

    result = await loop.run(
        AgentDefinition(
            "cursor-cost-preflight",
            max_output_tokens=4,
            emit_text_deltas=True,
            cost_budget=CostBudget(
                "10",
                "prices-v1",
                estimate_before_call=True,
                require_estimate=True,
            ),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COST_BUDGET
    assert provider.requests == []
    estimated = next(
        event for event in result.events if event.type is RunEventType.COST_ESTIMATED
    )
    assert estimated.data["attempt_count"] == 3
    assert estimated.data["cost"]["total"] == "21"


@pytest.mark.asyncio
async def test_required_cost_preflight_fails_closed_without_token_estimate():
    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1", "1"),),
            ),
        )
    )
    loop, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP, TokenUsage(1, 1))],
        python_tool(lambda: "unused", name="unused"),
        pricing=pricing,
    )

    result = await loop.run(
        AgentDefinition(
            "strict-cost-preflight",
            max_output_tokens=4,
            cost_budget=CostBudget(
                "1",
                "prices-v1",
                estimate_before_call=True,
                require_estimate=True,
            ),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COST_ESTIMATE_UNAVAILABLE
    assert provider.requests == []
    unavailable = next(
        event
        for event in result.events
        if event.type is RunEventType.COST_ESTIMATE_UNAVAILABLE
    )
    assert unavailable.data["error"] == "token-estimate-unavailable"


@pytest.mark.asyncio
async def test_custom_cost_estimator_and_soft_warning_are_visible():
    class FixedTokenEstimator:
        async def estimate(self, request):
            return TokenEstimate(2, "fixed-token:v1")

    class FixedCostEstimator:
        def __init__(self):
            self.requests = []

        async def estimate(self, request):
            self.requests.append(request)
            return CostEstimate(
                ModelCost("USD", "prices-v1", "0.2"),
                ModelCost("USD", "prices-v1", "0.6"),
                route_count=1,
                attempt_count=1,
                estimator="application-cost:v1",
            )

    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1", "1"),),
            ),
        )
    )
    cost_estimator = FixedCostEstimator()
    loop, provider = _loop(
        [((TextContent("done"),), FinishReason.STOP, TokenUsage(2, 1))],
        python_tool(lambda: "unused", name="unused"),
        pricing=pricing,
        token_estimator=FixedTokenEstimator(),
        cost_estimator=cost_estimator,
    )

    result = await loop.run(
        AgentDefinition(
            "custom-cost",
            max_output_tokens=3,
            cost_budget=CostBudget(
                "1",
                "prices-v1",
                estimate_before_call=True,
                soft_limit_ratio="0.5",
            ),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.requests) == 1
    assert cost_estimator.requests[0].estimated_input_tokens == 2
    warnings = [
        event
        for event in result.events
        if event.type is RunEventType.COST_BUDGET_WARNING
    ]
    assert warnings[0].data["phase"] == "preflight"
    assert warnings[0].data["cost"]["total"] == "0.6"


@pytest.mark.asyncio
async def test_react_cost_budget_fails_closed_without_usage_or_pricing():
    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1", "2"),),
            ),
        )
    )
    unmetered, _ = _loop(
        [((TextContent("unmetered"),), FinishReason.STOP)],
        python_tool(lambda: "unused", name="unused"),
        pricing=pricing,
    )
    missing_resolver, provider = _loop(
        [((TextContent("must not run"),), FinishReason.STOP, TokenUsage(1, 1))],
        python_tool(lambda: "unused", name="unused"),
    )
    definition = AgentDefinition(
        "strict-cost",
        cost_budget=CostBudget("1", "prices-v1", "USD"),
    )

    unmetered_result = await unmetered.run(definition, _context())
    missing_result = await missing_resolver.run(definition, _context())

    assert unmetered_result.stop_reason is StopReason.COST_UNAVAILABLE
    assert unmetered_result.cost_complete is False
    assert missing_result.stop_reason is StopReason.COST_UNAVAILABLE
    assert provider.requests == []


@pytest.mark.asyncio
async def test_react_attempt_ledger_marks_retry_usage_incomplete():
    loop, _ = _loop(
        [
            ModelFailure(
                ModelFailureKind.NETWORK,
                "temporary",
                "temporary failure",
                retryable=True,
            ),
            (
                (TextContent("recovered"),),
                FinishReason.STOP,
                TokenUsage(7, 2),
            ),
        ],
        python_tool(lambda: "unused", name="unused"),
        policy=InvocationPolicy(max_attempts_per_route=2, initial_backoff=0),
    )

    result = await loop.run(
        AgentDefinition(
            "strict-retry",
            token_budget=TokenBudget(require_usage=True),
        ),
        _context(),
    )

    assert result.stop_reason is StopReason.TOKEN_USAGE_UNAVAILABLE
    assert result.model_calls == 2
    assert result.reported_usage_calls == 1
    assert result.usage == TokenUsage(7, 2)
    assert result.usage_complete is False
    assert [item.outcome.value for item in result.attempts] == [
        "failed",
        "succeeded",
    ]
    completed = next(
        event for event in result.events if event.type is RunEventType.MODEL_COMPLETED
    )
    assert completed.data["attempt_usage_complete"] is False
    assert completed.data["attempts"][0]["failure_code"] == "temporary"


@pytest.mark.asyncio
async def test_attempt_checkpoint_persists_ledger_without_failure_message(tmp_path):
    class FixedEstimator:
        async def estimate(self, request):
            return TokenEstimate(1, "fixed:v1")

    store = JsonlRunStore(tmp_path)
    loop, _ = _loop(
        [
            ModelFailure(
                ModelFailureKind.NETWORK,
                "temporary",
                "secret provider response",
                retryable=True,
            ),
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
                TokenUsage(6, 2),
            ),
        ],
        python_tool(
            lambda text: text,
            name="save",
            side_effect=ToolSideEffect.WRITE,
        ),
        store=store,
        policy=InvocationPolicy(max_attempts_per_route=2, initial_backoff=0),
        token_estimator=FixedEstimator(),
    )

    result = await loop.run(
        AgentDefinition(
            "writer",
            emit_text_deltas=True,
            emit_tool_call_deltas=True,
            emit_output_blocks=True,
            token_budget=TokenBudget(
                require_estimate=True,
                soft_limit_ratio="0.8",
            ),
        ),
        _context(),
    )
    checkpoint = await JsonlRunStore(tmp_path).load_checkpoint("run-1")
    persisted = (tmp_path / "runs" / "run-1" / "checkpoint.json").read_text(
        encoding="utf-8"
    )

    assert result.stop_reason is StopReason.NEEDS_APPROVAL
    assert checkpoint is not None
    assert len(checkpoint.attempts) == 2
    assert checkpoint.attempts[0].failure is not None
    assert checkpoint.definition.token_budget is not None
    assert checkpoint.definition.emit_text_deltas is True
    assert checkpoint.definition.emit_tool_call_deltas is True
    assert checkpoint.definition.emit_output_blocks is True
    assert checkpoint.definition.token_budget.require_estimate is True
    assert str(checkpoint.definition.token_budget.soft_limit_ratio) == "0.8"
    assert '"soft_limit_ratio":"0.8"' in persisted
    assert '"emit_tool_call_deltas":true' in persisted
    assert '"emit_output_blocks":true' in persisted
    assert "omitted" in checkpoint.attempts[0].failure.message
    assert "secret provider response" not in persisted


@pytest.mark.asyncio
async def test_cost_ledger_survives_approval_checkpoint_resume(tmp_path):
    saved = []
    binding = python_tool(
        lambda text: saved.append(text) or "saved",
        name="save",
        side_effect=ToolSideEffect.WRITE,
    )
    pricing = PricingCatalog(
        (
            PriceTable(
                "prices-v1",
                "USD",
                (ModelPrice("fake", "chat", "1000000", "1000000"),),
            ),
        )
    )
    definition = AgentDefinition(
        "priced-writer",
        cost_budget=CostBudget(
            "100",
            "prices-v1",
            "USD",
            estimate_before_call=True,
            soft_limit_ratio="0.8",
        ),
    )
    first_loop, _ = _loop(
        [
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
                TokenUsage(6, 2),
            )
        ],
        binding,
        store=JsonlRunStore(tmp_path),
        pricing=pricing,
    )

    pending = await first_loop.run(definition, _context())
    checkpoint = await JsonlRunStore(tmp_path).load_checkpoint("run-1")

    assert pending.stop_reason is StopReason.NEEDS_APPROVAL
    assert checkpoint is not None
    assert checkpoint.cost is not None
    assert checkpoint.cost.total == 8
    assert checkpoint.priced_usage_calls == 1
    assert checkpoint.definition.cost_budget is not None
    assert checkpoint.definition.cost_budget.estimate_before_call is True
    assert str(checkpoint.definition.cost_budget.soft_limit_ratio) == "0.8"

    second_loop, _ = _loop(
        [((TextContent("saved"),), FinishReason.STOP, TokenUsage(7, 3))],
        binding,
        store=JsonlRunStore(tmp_path),
        pricing=pricing,
    )
    resumed = await second_loop.resume(
        "run-1",
        tool_context=ToolExecutionContext(
            approved_call_ids=frozenset({"write-1"})
        ),
    )

    assert resumed.stop_reason is StopReason.COMPLETED
    assert resumed.cost is not None
    assert resumed.cost.total == 18
    assert resumed.cost_complete is True
    assert resumed.priced_usage_calls == 2
    assert saved == ["value"]


@pytest.mark.asyncio
async def test_react_approval_resumes_from_jsonl_without_repeating_model(tmp_path):
    saved = []

    def save(text: str) -> str:
        saved.append(text)
        return "saved"

    binding = python_tool(save, side_effect=ToolSideEffect.WRITE)
    first_store = JsonlRunStore(tmp_path)
    first_loop, first_provider = _loop(
        [
            (
                (
                    ToolCallContent("write-1", "save", '{"text":"value"}'),
                    ToolCallContent("write-2", "save", '{"text":"second"}'),
                ),
                FinishReason.TOOL_CALLS,
                TokenUsage(10, 2),
            )
        ],
        binding,
        store=first_store,
    )
    initial = await first_loop.run(
        AgentDefinition("writer"),
        _context(session_id="session-1"),
    )
    summaries = await first_store.list_checkpoints()

    assert initial.stop_reason == StopReason.NEEDS_APPROVAL
    assert initial.checkpoint_id == "run-1"
    assert len(first_provider.requests) == 1
    assert saved == []
    assert len(summaries) == 1
    assert summaries[0].run_id == "run-1"
    assert summaries[0].session_id == "session-1"
    assert summaries[0].pending_call_id == "write-1"
    assert summaries[0].pending_tool_name == "save"
    assert summaries[0].pending_argument_keys == ("text",)
    assert "value" not in repr(summaries[0])

    second_store = JsonlRunStore(tmp_path)
    second_loop, second_provider = _loop(
        [
            (
                (TextContent("both saved"),),
                FinishReason.STOP,
                TokenUsage(12, 3),
            )
        ],
        binding,
        store=second_store,
    )
    resumed = await second_loop.resume(
        "run-1",
        tool_context=ToolExecutionContext(
            approved_call_ids=frozenset({"write-1", "write-2"})
        ),
    )

    assert resumed.stop_reason == StopReason.COMPLETED
    assert resumed.output == "both saved"
    assert saved == ["value", "second"]
    assert len(first_provider.requests) == 1
    assert len(second_provider.requests) == 1
    assert resumed.events[0].type == RunEventType.RUN_STARTED
    assert any(event.type == RunEventType.RUN_RESUMED for event in resumed.events)
    assert [event.sequence for event in resumed.events] == list(
        range(1, len(resumed.events) + 1)
    )
    assert all(event.session_id == "session-1" for event in resumed.events)
    assert resumed.usage == TokenUsage(22, 5)
    assert resumed.usage_complete is True
    assert len(resumed.attempts) == 2
    assert resumed.attempts[0].usage == TokenUsage(10, 2)
    assert resumed.attempts[1].usage == TokenUsage(12, 3)
    assert await second_store.load_checkpoint("run-1") is None
    assert await second_store.list_checkpoints() == ()
    assert (tmp_path / "runs" / "run-1" / "events.jsonl").is_file()


@pytest.mark.asyncio
async def test_resume_without_approval_recreates_pending_checkpoint(tmp_path):
    calls = []

    def save(text: str) -> str:
        calls.append(text)
        return "saved"

    binding = python_tool(save, side_effect=ToolSideEffect.WRITE)
    store = JsonlRunStore(tmp_path)
    loop, provider = _loop(
        [
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
            ),
            ((TextContent("saved"),), FinishReason.STOP),
        ],
        binding,
        store=store,
    )
    await loop.run(AgentDefinition("writer"), _context())

    still_pending = await loop.resume(
        "run-1",
        tool_context=ToolExecutionContext(),
    )
    completed = await loop.resume(
        "run-1",
        tool_context=ToolExecutionContext(
            approved_call_ids=frozenset({"write-1"})
        ),
    )

    assert still_pending.stop_reason == StopReason.NEEDS_APPROVAL
    assert completed.stop_reason == StopReason.COMPLETED
    assert calls == ["value"]
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_claimed_checkpoint_refuses_unsafe_duplicate_resume(tmp_path):
    calls = []

    def save(text: str) -> str:
        calls.append(text)
        return "saved"

    store = JsonlRunStore(tmp_path)
    loop, _ = _loop(
        [
            (
                (ToolCallContent("write-1", "save", '{"text":"value"}'),),
                FinishReason.TOOL_CALLS,
            )
        ],
        python_tool(save, side_effect=ToolSideEffect.WRITE),
        store=store,
    )
    await loop.run(AgentDefinition("writer"), _context())
    lazy = loop.resume_stream(
        "run-1",
        tool_context=ToolExecutionContext(
            approved_call_ids=frozenset({"write-1"})
        ),
    )

    checkpoint = await store.load_checkpoint("run-1")
    assert checkpoint is not None
    assert checkpoint.status.value == "pending-approval"
    await store.claim_checkpoint("run-1")

    with pytest.raises(RunResumeConflictError):
        async for _ in lazy:
            pass

    assert calls == []
