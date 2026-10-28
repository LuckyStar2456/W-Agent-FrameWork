"""Modern, network-free support/coding starter. Copy this file into your project.

The deterministic provider demonstrates wiring, not language-model intelligence.
Nothing runs at import. Tools read only host-supplied sample data; no file edit,
command execution, real business policy, model download or network is implied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import ExitStack
from uuid import uuid4

from w_agent import (
    AgentDefinition, BlockEnd, BlockStart, FinishEvent, FinishReason,
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KeywordKnowledgeRetriever,
    MessageRole, ModelCapability, ModelDescriptor, ModelExecutor, ModelMessage,
    ModelProvider, ModelRegistry, ModelRouter, ReactAgentLoop, RunContext, RunResult,
    TextContent, TokenUsage, ToolBinding, ToolCallContent, ToolExecutionContext,
    ToolExecutor, ToolRegistry, ToolResultContent, ToolSideEffect, UsageEvent,
    coding_agent, customer_support_agent, knowledge_search_tool, python_tool,
)


def support_tools() -> tuple[ToolBinding, ...]:
    """Project factory: replace sample data with your authorized local retriever."""
    documents = InMemoryKnowledgeDocumentStore((KnowledgeDocument(
        "sample-policy", "Sample only: returns within seven days.", "sample:returns", "Demo policy",
    ),))
    return (knowledge_search_tool(KeywordKnowledgeRetriever(documents), side_effect=ToolSideEffect.READ),)


def coding_tools(source: str = "def add(left, right):\n    return left + right\n") -> tuple[ToolBinding, ...]:
    """Read host-supplied text, not arbitrary files or an implicit IDE toolset."""
    if not isinstance(source, str) or len(source.encode("utf-8")) > 65536:
        raise ValueError("sample source must be bounded text")

    def read_sample_module() -> dict:
        return {"name": "sample.py", "source": source}

    return (python_tool(read_sample_module, side_effect=ToolSideEffect.READ,
                        required_permissions=frozenset({"workspace.read"})),)


class OfflineToolModel:
    """Two-turn fixture deriving the answer from the actual returned tool data."""

    def __init__(self, mode: str) -> None:
        if mode not in {"support", "coding"}:
            raise ValueError("unknown demo mode")
        self.mode = mode
        self.requests = []
        self.closed = False
        self.close_calls = 0

    async def list_models(self):
        return (await self.resolve("demo"),)

    async def resolve(self, model):
        if model != "demo":
            raise ValueError("unknown demo model")
        return ModelDescriptor("offline", "demo", frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT, ModelCapability.TOOL_CALLING,
        }))

    async def stream(self, request, *, cancellation=None):
        if self.closed:
            raise RuntimeError("demo provider is closed")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        self.requests.append(request)
        results = [block for message in request.messages for block in message.content if isinstance(block, ToolResultContent)]
        if not results:
            name = "knowledge_search" if self.mode == "support" else "read_sample_module"
            arguments = '{"query":"returns"}' if self.mode == "support" else "{}"
            block = ToolCallContent("demo-read-1", name, arguments)
            reason = FinishReason.TOOL_CALLS
        else:
            result = results[-1]
            if result.is_error:
                answer = "The read was denied or failed; no sample evidence was available."
            else:
                payload = json.loads(result.content)
                if self.mode == "support":
                    item = payload["documents"][0]
                    answer = f"{item['text']} [source: {item['source']}]"
                else:
                    answer = "Read-only sample source (not executed or modified):\n" + payload["source"]
            block, reason = TextContent(answer), FinishReason.STOP
        yield BlockStart(0, block.type)
        yield BlockEnd(0, block)
        yield UsageEvent(TokenUsage(10, 5))  # Synthetic fixture counts, not measured billing.
        yield FinishEvent(reason)

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


async def run_with_provider(
    provider: ModelProvider, definition: AgentDefinition, bindings: tuple[ToolBinding, ...],
    prompt: str, permissions: frozenset[str], *, provider_name: str = "offline",
) -> RunResult:
    """Own this provider until return; authorize only supplied permissions.

    A real provider may bill or disclose inputs: call only after separate host
    authorization. This helper never approves WRITE/EXTERNAL tool calls.
    """
    try:
        models, tools = ModelRegistry(), ToolRegistry()
        with ExitStack() as registrations:
            registrations.enter_context(models.register(provider_name, provider))
            for binding in bindings:
                registrations.enter_context(tools.register_binding(binding))
            loop = ReactAgentLoop(ModelExecutor(models, ModelRouter(models)), tools, ToolExecutor(tools))
            return await loop.run(definition, RunContext(
                "demo-" + uuid4().hex,
                (ModelMessage.text(MessageRole.USER, prompt),),
                tool_context=ToolExecutionContext(permissions=permissions),
            ))
    finally:
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()


async def run_demo(mode: str) -> RunResult:
    if mode == "support":
        return await run_with_provider(OfflineToolModel(mode), customer_support_agent(model="demo"),
            support_tools(), "What is the sample returns rule?", frozenset({"knowledge.read"}))
    if mode == "coding":
        return await run_with_provider(OfflineToolModel(mode), coding_agent(model="demo"),
            coding_tools(), "Read the host-supplied sample module.", frozenset({"workspace.read"}))
    raise ValueError("unknown demo mode")


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline modern W-Agent development starter")
    parser.add_argument("mode", choices=("support", "coding"))
    arguments = parser.parse_args()
    result = asyncio.run(run_demo(arguments.mode))
    print(json.dumps({"mode": arguments.mode, "offline": True, "stop_reason": result.stop_reason.value,
                      "steps": result.steps, "tool_calls": result.tool_calls, "output": result.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
