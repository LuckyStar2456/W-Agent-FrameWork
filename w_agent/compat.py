"""Minimal, explicit bridges from W-Agent 1.x APIs to current contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from w_agent.core.agent import BaseAgent
from w_agent.workflows import WorkflowNode, WorkflowNodeContext

LegacyPromptMapper = Callable[[WorkflowNodeContext], str]
LegacyResultMapper = Callable[[str, WorkflowNodeContext], Any]


class LegacyAgentAdapterError(RuntimeError):
    """A legacy agent cannot be represented by the minimal compatibility bridge."""


class LegacyAgentAdapter:
    """Expose one 1.x ``BaseAgent`` as an ordinary workflow-node handler.

    The bridge intentionally carries only a text prompt and final text result.
    It does not claim model metadata, tool calls, streaming, token usage, or
    checkpoint support that the legacy contract cannot provide.
    """

    def __init__(
        self,
        agent: BaseAgent,
        *,
        prompt_mapper: LegacyPromptMapper | None = None,
        result_mapper: LegacyResultMapper | None = None,
    ) -> None:
        if not callable(getattr(agent, "arun", None)):
            raise TypeError("legacy agent must provide async arun(prompt)")
        self.agent = agent
        self.prompt_mapper = prompt_mapper or _text_input
        self.result_mapper = result_mapper or _text_output

    async def invoke(self, context: WorkflowNodeContext) -> Any:
        """Invoke the legacy agent once through a workflow node context."""

        if context.cancellation is not None:
            context.cancellation.raise_if_cancelled()
        prompt = self.prompt_mapper(context)
        if not isinstance(prompt, str):
            raise LegacyAgentAdapterError("legacy prompt mapper must return text")
        output = await self.agent.arun(prompt)
        if not isinstance(output, str):
            raise LegacyAgentAdapterError("legacy agent arun() must return text")
        if context.cancellation is not None:
            context.cancellation.raise_if_cancelled()
        return self.result_mapper(output, context)

    def workflow_node(self, name: str) -> WorkflowNode:
        """Create a workflow node backed by this explicit adapter."""

        return WorkflowNode(name, self.invoke)


def legacy_agent_workflow_node(
    name: str,
    agent: BaseAgent,
    *,
    prompt_mapper: LegacyPromptMapper | None = None,
    result_mapper: LegacyResultMapper | None = None,
) -> WorkflowNode:
    """Create the minimal workflow bridge for one legacy agent."""

    return LegacyAgentAdapter(
        agent,
        prompt_mapper=prompt_mapper,
        result_mapper=result_mapper,
    ).workflow_node(name)


def _text_input(context: WorkflowNodeContext) -> str:
    if not isinstance(context.input, str):
        raise LegacyAgentAdapterError(
            "legacy agent input must be text or use a prompt_mapper"
        )
    return context.input


def _text_output(output: str, context: WorkflowNodeContext) -> str:
    del context
    return output
