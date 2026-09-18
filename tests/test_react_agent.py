import pytest

from w_agent import (
    AgentDefinition,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    InvocationPolicy,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelError,
    ModelExecutor,
    ModelFailure,
    ModelFailureKind,
    ModelMessage,
    ModelRegistry,
    ModelRouter,
    JsonlRunStore,
    CostBudget,
    ModelPrice,
    PriceTable,
    PricingCatalog,
    ReactAgentLoop,
    RunResumeConflictError,
    RunContext,
    RunEventType,
    StopReason,
    TextContent,
    TextDelta,
    TokenBudget,
    TokenUsage,
    ToolCallContent,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolResultContent,
    ToolSideEffect,
    UsageEvent,
    WeightedRoutingPolicy,
    python_tool,
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
            yield BlockEnd(index, block)
        if len(response) == 3:
            yield UsageEvent(response[2])
        yield FinishEvent(reason)


def _loop(responses, binding, *, store=None, policy=None, pricing=None):
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
    ), provider


def _context(**kwargs):
    return RunContext(
        "run-1",
        (ModelMessage.text(MessageRole.USER, "calculate"),),
        **kwargs,
    )


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
    )

    result = await loop.run(AgentDefinition("writer"), _context())
    checkpoint = await JsonlRunStore(tmp_path).load_checkpoint("run-1")
    persisted = (tmp_path / "runs" / "run-1" / "checkpoint.json").read_text(
        encoding="utf-8"
    )

    assert result.stop_reason is StopReason.NEEDS_APPROVAL
    assert checkpoint is not None
    assert len(checkpoint.attempts) == 2
    assert checkpoint.attempts[0].failure is not None
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
        cost_budget=CostBudget("100", "prices-v1", "USD"),
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
