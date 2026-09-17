from __future__ import annotations

import pytest

from w_agent import (
    BaseAgent,
    CancellationToken,
    LegacyAgentAdapter,
    LegacyAgentAdapterError,
    LocalWorkflowEngine,
    PythonWorkflowDefinition,
    WorkflowContext,
    WorkflowNodeContext,
    WorkflowStopReason,
    legacy_agent_workflow_node,
)


class EchoLegacyAgent(BaseAgent):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def arun(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"legacy:{prompt}"


@pytest.mark.asyncio
async def test_legacy_agent_runs_as_workflow_node_without_claiming_new_features():
    agent = EchoLegacyAgent()
    node = legacy_agent_workflow_node("legacy", agent)
    engine = LocalWorkflowEngine()

    result = await engine.start(
        PythonWorkflowDefinition("compat", node.handler),
        WorkflowContext("workflow-legacy-1", input="hello"),
    )

    assert result.stop_reason is WorkflowStopReason.COMPLETED
    assert result.output == "legacy:hello"
    assert agent.prompts == ["hello"]


@pytest.mark.asyncio
async def test_legacy_adapter_requires_text_unless_mapper_is_explicit():
    agent = EchoLegacyAgent()
    strict = LegacyAgentAdapter(agent).workflow_node("strict")
    mapped = LegacyAgentAdapter(
        agent,
        prompt_mapper=lambda context: str(context.input["prompt"]),
        result_mapper=lambda output, context: {
            "output": output,
            "workflow": context.run_id,
        },
    ).workflow_node("mapped")
    engine = LocalWorkflowEngine()

    rejected = await engine.start(
        PythonWorkflowDefinition("strict", strict.handler),
        WorkflowContext("workflow-legacy-2", input={"prompt": "hello"}),
    )
    accepted = await engine.start(
        PythonWorkflowDefinition("mapped", mapped.handler),
        WorkflowContext("workflow-legacy-3", input={"prompt": "hello"}),
    )

    assert rejected.stop_reason is WorkflowStopReason.FAILED
    assert agent.prompts == ["hello"]
    assert accepted.output == {
        "output": "legacy:hello",
        "workflow": "workflow-legacy-3",
    }


@pytest.mark.asyncio
async def test_legacy_adapter_honors_pre_call_cancellation():
    agent = EchoLegacyAgent()
    token = CancellationToken()
    token.cancel()
    node = LegacyAgentAdapter(agent).workflow_node("cancelled")
    engine = LocalWorkflowEngine()

    result = await engine.start(
        PythonWorkflowDefinition("cancelled", node.handler),
        WorkflowContext("workflow-legacy-4", input="hello", cancellation=token),
    )

    assert result.stop_reason is WorkflowStopReason.CANCELLED
    assert agent.prompts == []


@pytest.mark.asyncio
async def test_legacy_adapter_rejects_non_text_output():
    class InvalidLegacyAgent(BaseAgent):
        async def arun(self, prompt: str) -> str:
            return {"prompt": prompt}  # type: ignore[return-value]

    adapter = LegacyAgentAdapter(InvalidLegacyAgent())
    context = WorkflowContext("unused", input="hello")
    node_context = WorkflowNodeContext(
        context.run_id,
        "legacy",
        context.input,
        {},
        {},
        context.scope,
        context.cancellation,
    )

    with pytest.raises(LegacyAgentAdapterError, match="must return text"):
        await adapter.invoke(node_context)
