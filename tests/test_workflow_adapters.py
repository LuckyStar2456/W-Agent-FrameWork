from __future__ import annotations

import pytest

from w_agent import (
    AgentDefinition,
    AgentWorkflowAdapterError,
    LocalWorkflowEngine,
    MessageRole,
    ModelMessage,
    PythonWorkflowDefinition,
    RunResult,
    ScopePath,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolOutcome,
    ToolRegistry,
    WorkflowContext,
    WorkflowNodeContext,
    WorkflowNodeResult,
    WorkflowStopReason,
    agent_workflow_node,
    workflow_resume_tool,
    workflow_start_tool,
)


class StubAgentLoop:
    def __init__(self, stop_reason: StopReason = StopReason.COMPLETED) -> None:
        self.stop_reason = stop_reason
        self.contexts = []

    async def run(self, definition, context):
        self.contexts.append((definition, context))
        return RunResult(
            context.run_id,
            self.stop_reason,
            "agent answer",
            context.messages,
            (),
            1,
            0,
            usage=TokenUsage(7, 3),
            model_calls=1,
            reported_usage_calls=1,
        )

    def stream(self, definition, context):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_agent_workflow_node_maps_public_context_and_result():
    loop = StubAgentLoop()
    node = agent_workflow_node(
        "answer",
        loop,
        AgentDefinition("support"),
    )
    scope = ScopePath.application().child("project", "demo")

    result = await LocalWorkflowEngine().start(
        PythonWorkflowDefinition("agent-step", node.handler),
        WorkflowContext("workflow-1", input={"question": "hello"}, scope=scope),
    )

    assert result.stop_reason == WorkflowStopReason.COMPLETED
    assert result.output["output"] == "agent answer"
    assert result.output["usage"] == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "cached_input_tokens": 0,
        "complete": True,
    }
    _, context = loop.contexts[0]
    assert context.scope == scope
    assert context.metadata["workflow_run_id"] == "workflow-1"
    assert context.messages == (
        ModelMessage.text(MessageRole.USER, '{"question":"hello"}'),
    )


@pytest.mark.asyncio
async def test_agent_workflow_node_rejects_unaccepted_stop_reason():
    loop = StubAgentLoop(StopReason.TOKEN_BUDGET)
    node = agent_workflow_node(
        "answer",
        loop,
        AgentDefinition("bounded"),
    )

    with pytest.raises(AgentWorkflowAdapterError, match="token-budget"):
        await node.handler(
            WorkflowNodeContext(
                "workflow-2",
                "answer",
                "hello",
                {},
                {},
                ScopePath.application(),
                None,
            )
        )


@pytest.mark.asyncio
async def test_workflow_start_and_resume_tools_use_tool_governance():
    def handler(context):
        if context.resume_count == 0:
            return WorkflowNodeResult(output="waiting", pause=True)
        return "done"

    definition = PythonWorkflowDefinition("review", handler)
    engine = LocalWorkflowEngine()
    registry = ToolRegistry()
    registry.register_binding(workflow_start_tool(engine, definition))
    registry.register_binding(workflow_resume_tool(engine, definition))
    executor = ToolExecutor(registry)

    denied = await executor.execute(
        ToolCall("start-denied", "run_review", {"input": "draft"}),
        ToolExecutionContext(),
    )
    assert denied.outcome == ToolOutcome.DENIED

    started = await executor.execute(
        ToolCall("start-1", "run_review", {"input": "draft"}),
        ToolExecutionContext(
            permissions=frozenset({"workflow.execute"}),
            approved_call_ids=frozenset({"start-1"}),
        ),
    )

    assert started.outcome == ToolOutcome.SUCCEEDED
    assert started.data["stop_reason"] == "paused"
    assert started.data["checkpoint_id"] == started.data["run_id"]

    resumed = await executor.execute(
        ToolCall(
            "resume-1",
            "resume_review",
            {"run_id": started.data["run_id"]},
        ),
        ToolExecutionContext(
            permissions=frozenset({"workflow.execute"}),
            approved_call_ids=frozenset({"resume-1"}),
        ),
    )

    assert resumed.outcome == ToolOutcome.SUCCEEDED
    assert resumed.data["stop_reason"] == "completed"
    assert resumed.data["output"] == "done"
