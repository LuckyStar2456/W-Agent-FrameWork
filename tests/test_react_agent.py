import pytest

from w_agent import (
    AgentDefinition,
    BlockEnd,
    BlockStart,
    FinishEvent,
    FinishReason,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelExecutor,
    ModelMessage,
    ModelRegistry,
    ModelRouter,
    ReactAgentLoop,
    RunContext,
    RunEventType,
    StopReason,
    TextContent,
    TextDelta,
    ToolCallContent,
    ToolExecutionContext,
    ToolExecutor,
    ToolRegistry,
    ToolResultContent,
    ToolSideEffect,
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
        blocks, reason = self.responses.pop(0)
        for index, block in enumerate(blocks):
            yield BlockStart(index, block.type)
            if isinstance(block, TextContent):
                yield TextDelta(index, block.text)
            yield BlockEnd(index, block)
        yield FinishEvent(reason)


def _loop(responses, binding):
    provider = AgentProvider(responses)
    models = ModelRegistry()
    models.register("fake", provider)
    router = ModelRouter(
        models,
        WeightedRoutingPolicy(preferred_providers=("fake",)),
    )
    model_executor = ModelExecutor(models, router)
    tools = ToolRegistry()
    tools.register_binding(binding)
    tool_executor = ToolExecutor(tools)
    return ReactAgentLoop(model_executor, tools, tool_executor), provider


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
