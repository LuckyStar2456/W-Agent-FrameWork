"""Draft knowledge-tool regressions; execution requires separate authorization."""

import asyncio
import json

import pytest

from w_agent import (
    BlockEnd, BlockStart, CancellationToken, FinishEvent, FinishReason,
    KnowledgeDocument, KnowledgeRetrievalError, ModelCapability, ModelDescriptor,
    ProviderTemplate, ProviderTemplateRegistry, TextContent, TokenUsage,
    ToolCall, ToolCallContent, ToolExecutionContext, ToolExecutor, ToolOutcome,
    ToolRegistry, ToolResultContent, ToolSideEffect, UsageEvent,
    assemble_local_runtime, knowledge_search_tool, local_runtime_config_from_mapping,
)


class Retriever:
    def __init__(self, documents=()):
        self.documents = documents
        self.calls = []

    async def retrieve(self, query, *, limit):
        self.calls.append((query, limit))
        return self.documents


def executor_for(binding):
    registry = ToolRegistry()
    registry.register_binding(binding)
    return ToolExecutor(registry)


def authority(*, approved=False, cancellation=None):
    return ToolExecutionContext(
        permissions=frozenset({"knowledge.read"}),
        approved_call_ids=frozenset({"call-1"}) if approved else frozenset(),
        cancellation=cancellation,
    )


@pytest.mark.asyncio
async def test_default_permission_and_approval_precede_retrieval():
    document = KnowledgeDocument("id", "PRIVATE_BODY", "manual:v1", "Title")
    retriever = Retriever((document,))
    binding = knowledge_search_tool(retriever)
    executor = executor_for(binding)
    assert not retriever.calls
    assert binding.side_effect == ToolSideEffect.EXTERNAL
    call = ToolCall("call-1", "knowledge_search", {"query": "PRIVATE_QUERY"})
    assert (await executor.execute(call)).outcome == ToolOutcome.DENIED
    assert (await executor.execute(call, authority())).outcome == ToolOutcome.NEEDS_APPROVAL
    assert not retriever.calls
    result = await executor.execute(call, authority(approved=True))
    assert result.outcome == ToolOutcome.SUCCEEDED
    assert retriever.calls == [("PRIVATE_QUERY", 4)]
    assert result.data == json.loads(result.content)
    assert result.data["documents"] == [
        {"id": "id", "source": "manual:v1", "title": "Title", "text": "PRIVATE_BODY"},
    ]
    assert "untrusted" in result.data["notice"].lower()
    assert "PRIVATE" not in repr(executor.audit.records)
    assert "PRIVATE" not in repr(binding.metadata)


@pytest.mark.asyncio
async def test_local_read_still_needs_permission_and_no_match_is_success():
    retriever = Retriever()
    executor = executor_for(knowledge_search_tool(retriever, side_effect=ToolSideEffect.READ))
    call = ToolCall("call-1", "knowledge_search", {"query": "q", "limit": 1})
    assert (await executor.execute(call)).outcome == ToolOutcome.DENIED
    result = await executor.execute(call, authority())
    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.data["documents"] == []
    assert retriever.calls == [("q", 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {}, {"query": ""}, {"query": " "}, {"query": 1}, {"query": "中" * 1366},
    {"query": "q", "limit": 0}, {"query": "q", "limit": True},
    {"query": "q", "limit": 5}, {"query": "q", "limit": 1.0},
    {"query": "q", "endpoint": "http://other"}, {"query": "q", "point_ids": []},
])
async def test_bad_arguments_fail_before_callback_even_if_generic_schema_is_mutated(arguments):
    retriever = Retriever()
    binding = knowledge_search_tool(retriever)
    with pytest.raises(KnowledgeRetrievalError):
        await binding.handler(arguments, authority(approved=True))
    assert not retriever.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("documents", [
    [KnowledgeDocument(1, "body")], (object(),),
    (KnowledgeDocument(1, "body"), KnowledgeDocument(1, "duplicate")),
    tuple(KnowledgeDocument(index, "body") for index in range(5)),
])
async def test_invalid_result_shape_duplicate_or_excess_results_fail(documents):
    executor = executor_for(knowledge_search_tool(Retriever(documents)))
    result = await executor.execute(ToolCall("call-1", "knowledge_search", {"query": "q"}), authority(approved=True))
    assert result.outcome == ToolOutcome.FAILED
    assert result.data is None


@pytest.mark.asyncio
async def test_exact_serialized_output_bound_includes_json_escaping():
    document = KnowledgeDocument(1, '中"\n' * 20)
    retriever = Retriever((document,))
    context = authority(approved=True)
    call = ToolCall("call-1", "knowledge_search", {"query": "q"})
    baseline = await executor_for(knowledge_search_tool(retriever)).execute(call, context)
    size = len(baseline.content.encode("utf-8"))
    exact = await executor_for(knowledge_search_tool(retriever, max_output_bytes=size)).execute(call, context)
    short = await executor_for(knowledge_search_tool(retriever, max_output_bytes=size - 1)).execute(call, context)
    assert exact.outcome == ToolOutcome.SUCCEEDED
    assert short.outcome == ToolOutcome.FAILED
    raw = await executor_for(knowledge_search_tool(retriever, max_document_bytes=1)).execute(call, context)
    assert raw.outcome == ToolOutcome.FAILED


@pytest.mark.asyncio
async def test_failure_does_not_echo_remote_error_or_retry():
    class Broken:
        calls = 0

        async def retrieve(self, query, *, limit):
            self.calls += 1
            raise RuntimeError("PRIVATE_SECRET")

    retriever = Broken()
    result = await executor_for(knowledge_search_tool(retriever)).execute(
        ToolCall("call-1", "knowledge_search", {"query": "PRIVATE_QUERY"}), authority(approved=True),
    )
    assert result.outcome == ToolOutcome.FAILED and retriever.calls == 1
    assert "PRIVATE" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_cooperative_cancellation_and_timeout_use_executor_outcomes(cancel):
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow:
        async def retrieve(self, query, *, limit):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    token = CancellationToken()
    executor = executor_for(knowledge_search_tool(Slow(), timeout=30 if cancel else 0.01))
    task = asyncio.create_task(executor.execute(
        ToolCall("call-1", "knowledge_search", {"query": "q"}),
        authority(approved=True, cancellation=token),
    ))
    await started.wait()
    if cancel:
        token.cancel()
    result = await task
    assert result.outcome == (ToolOutcome.CANCELLED if cancel else ToolOutcome.TIMED_OUT)
    assert closed.is_set()


@pytest.mark.parametrize("options", [
    {"name": "bad name"}, {"name": "x" * 65}, {"description": ""},
    {"max_results": True}, {"max_results": 129}, {"max_query_bytes": 4097},
    {"max_document_bytes": 0}, {"max_output_bytes": -1},
    {"timeout": float("nan")}, {"side_effect": "read"},
    {"required_permissions": ["knowledge.read"]}, {"required_permissions": frozenset({1})},
])
def test_configuration_is_validated_without_retrieval(options):
    retriever = Retriever()
    with pytest.raises(ValueError):
        knowledge_search_tool(retriever, **options)
    assert not retriever.calls


class ScriptedProvider:
    def __init__(self):
        self.requests = []
        self.closed = False

    async def list_models(self):
        return (ModelDescriptor("fake", "test", frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT, ModelCapability.TOOL_CALLING,
        })),)

    async def resolve(self, model):
        return (await self.list_models())[0]

    async def stream(self, request, *, cancellation=None):
        self.requests.append(request)
        first = len(self.requests) == 1
        block = ToolCallContent("call-1", "knowledge_search", '{"query":"refund"}') if first else TextContent("answer")
        yield BlockStart(0, block.type)
        yield BlockEnd(0, block)
        yield UsageEvent(TokenUsage(2, 1))
        yield FinishEvent(FinishReason.TOOL_CALLS if first else FinishReason.STOP)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_named_runtime_binding_approval_resume_and_tool_result_reaches_model(tmp_path):
    provider = ScriptedProvider()
    retriever = Retriever((KnowledgeDocument("faq-v1", "seven days", "manual:refund"),))
    config = local_runtime_config_from_mapping({
        "provider": {"template": "fake", "name": "fake", "model": "test"},
        "tools": {"enabled": ["knowledge_search"]},
        "agent": {"max_tool_calls": 2},
    })
    runtime = assemble_local_runtime(
        config, tmp_path,
        templates=ProviderTemplateRegistry((ProviderTemplate("fake", "Fake", "test", None, lambda **kwargs: provider),)),
        tool_bindings={"knowledge_search": knowledge_search_tool(retriever)},
    )
    try:
        pending = await runtime.run("refund?", permissions=frozenset({"knowledge.read"}))
        assert pending.result.stop_reason.value == "needs-approval"
        assert not retriever.calls
        done = await runtime.resume(pending.session.session_id, pending.result.run_id,
            permissions=frozenset({"knowledge.read"}), approved_call_ids=frozenset({"call-1"}))
        assert done.result.stop_reason.value == "completed"
        assert retriever.calls == [("refund", 4)]
        results = [block for message in provider.requests[-1].messages for block in message.content
                   if isinstance(block, ToolResultContent)]
        assert len(results) == 1 and not results[0].is_error
        assert json.loads(results[0].content)["documents"][0]["source"] == "manual:refund"
    finally:
        await runtime.aclose()
    assert provider.closed
