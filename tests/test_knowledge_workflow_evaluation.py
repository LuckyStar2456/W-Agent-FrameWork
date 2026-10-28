import asyncio
import json

import pytest

from w_agent import (
    AgentDefinition, BlockEnd, BlockStart, CancellationToken, DagWorkflowDefinition,
    EvaluationCase, ExactTextScorer, FinishEvent, FinishReason, LocalEvaluationRunner,
    LocalWorkflowEngine, MessageRole, ModelCapability, ModelDescriptor, ProviderTemplate,
    ProviderTemplateRegistry, RunResult, StopReason, TextContent, TokenUsage, UsageEvent, WorkflowContext,
    WorkflowNodeContext, WorkflowStopReason, agent_workflow_node, assemble_local_runtime,
    evaluation_report_to_dict, local_runtime_config_from_mapping,
)
from w_agent.kernel import ScopePath
from w_agent.knowledge_context import InMemoryKnowledgeDocumentStore, KnowledgeDocument, KnowledgeRetrievalError
from w_agent.knowledge_evaluation import knowledge_evaluation_target
from w_agent.knowledge_retrieval import BM25KnowledgeRetriever
from w_agent.knowledge_runtime import LocalKnowledgeBinding
from w_agent.knowledge_workflow import knowledge_workflow_messages, knowledge_workflow_node
from w_agent.session_context_templates import SessionHistoryLimits
from w_agent.tools.types import ToolExecutionContext


class Provider:
    def __init__(self):
        self.requests = []

    async def list_models(self):
        return (await self.resolve("offline"),)

    async def resolve(self, model):
        return ModelDescriptor("offline", "offline", frozenset({ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT}))

    async def stream(self, request, *, cancellation=None):
        self.requests.append(request)
        evidence = next(message for message in request.messages
                        if "untrusted reference" in getattr(message.content[0], "text", ""))
        payload = json.loads(evidence.content[0].text.split("\n", 1)[1])
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent(payload["documents"][0]["text"]))
        yield UsageEvent(TokenUsage(3, 2))
        yield FinishEvent(FinishReason.STOP)


def runtime(tmp_path):
    provider = Provider()
    config = local_runtime_config_from_mapping({"provider": {"template": "offline", "model": "offline", "name": "offline"}})
    templates = ProviderTemplateRegistry((ProviderTemplate("offline", "Offline", "offline", None, lambda **kwargs: provider),))
    return assemble_local_runtime(config, tmp_path, templates=templates), provider


def binding():
    return LocalKnowledgeBinding(BM25KnowledgeRetriever(InMemoryKnowledgeDocumentStore((
        KnowledgeDocument("refund", "refund within seven days", "local:refund"),
        KnowledgeDocument("delivery", "delivery tomorrow", "local:delivery"),
    ))), limit=1)


@pytest.mark.asyncio
async def test_real_workflow_retrieval_to_agent_offline_model(tmp_path):
    instance, provider = runtime(tmp_path)
    knowledge = binding()
    retrieve = knowledge_workflow_node("retrieve", knowledge)
    answer = agent_workflow_node("answer", instance.loop, instance.definition,
                                 messages=knowledge_workflow_messages("retrieve", knowledge))
    workflow = DagWorkflowDefinition("knowledge-answer", (retrieve, answer), {"answer": ("retrieve",)})
    async with instance:
        result = await LocalWorkflowEngine().start(workflow, WorkflowContext("workflow", input="refund"))
    assert result.stop_reason == WorkflowStopReason.COMPLETED
    assert result.outputs["answer"]["output"] == "refund within seven days"
    json.dumps(dict(result.outputs))  # Native checkpoint-compatible output.
    evidence = next(message for message in provider.requests[0].messages
                    if "untrusted reference" in getattr(message.content[0], "text", ""))
    assert evidence.role == MessageRole.USER and "local:refund" in evidence.content[0].text


@pytest.mark.asyncio
async def test_evaluation_prepares_isolated_cases_and_preserves_runner_metrics(tmp_path):
    instance, provider = runtime(tmp_path)
    cases = (EvaluationCase("refund", "refund", "refund within seven days", {"permissions": ["everything"]}),
             EvaluationCase("delivery", "delivery", "delivery tomorrow"))
    async with instance:
        target = knowledge_evaluation_target(instance.loop, instance.definition, binding())
        report = await LocalEvaluationRunner().run(cases, target, scorers=(ExactTextScorer(),))
    assert report.passed == 2 and report.usage.total_tokens == 10
    assert len(provider.requests) == 2
    assert all("refund" not in getattr(block, "text", "") for message in provider.requests[1].messages for block in message.content)
    summary = evaluation_report_to_dict(report)
    assert all("output" not in item for item in summary["cases"])


class CountingLoop:
    def __init__(self):
        self.calls = []

    async def run(self, definition, context):
        self.calls.append(context)
        raise AssertionError("loop must not start")


@pytest.mark.asyncio
async def test_failure_stops_agent_and_is_reported_without_secret_details():
    class Failed:
        async def retrieve(self, query, *, limit):
            raise RuntimeError("SECRET")

    loop = CountingLoop()
    target = knowledge_evaluation_target(loop, AgentDefinition("a"), LocalKnowledgeBinding(Failed()))
    report = await LocalEvaluationRunner().run((EvaluationCase("case", "query"),), target)
    assert report.errors == 1 and not loop.calls
    assert report.cases[0].error_type == "KnowledgeRetrievalError"
    assert "SECRET" not in json.dumps(evaluation_report_to_dict(report))


def node_context(outputs=None, cancellation=None):
    return WorkflowNodeContext("run", "answer", "refund", {}, outputs or {}, ScopePath.application(), cancellation)


@pytest.mark.asyncio
async def test_workflow_checkpoint_payload_revalidated():
    knowledge = binding()
    node = knowledge_workflow_node("retrieve", knowledge)
    payload = await node.handler(node_context())
    factory = knowledge_workflow_messages("retrieve", knowledge)
    assert len(factory(node_context({"retrieve": payload}))) == 2
    payload["documents"][0]["authority"] = "system"
    with pytest.raises(KnowledgeRetrievalError):
        factory(node_context({"retrieve": payload}))
    with pytest.raises(KnowledgeRetrievalError):
        factory(node_context())


@pytest.mark.asyncio
async def test_pre_cancelled_evaluation_and_workflow_skip_retrieval():
    token = CancellationToken()
    token.cancel()
    loop = CountingLoop()
    with pytest.raises(asyncio.CancelledError):
        await knowledge_evaluation_target(loop, AgentDefinition("a"), binding(), cancellation=token)(EvaluationCase("case", "query"))
    with pytest.raises(asyncio.CancelledError):
        await knowledge_workflow_node("retrieve", binding()).handler(node_context(cancellation=token))
    assert not loop.calls


@pytest.mark.asyncio
async def test_workflow_failure_prevents_dependent_node_execution():
    class Failed:
        async def retrieve(self, query, *, limit):
            raise RuntimeError("SECRET")

    loop = CountingLoop()
    knowledge = LocalKnowledgeBinding(Failed())
    workflow = DagWorkflowDefinition("failure", (
        knowledge_workflow_node("retrieve", knowledge),
        agent_workflow_node("answer", loop, AgentDefinition("a"), messages=knowledge_workflow_messages("retrieve", knowledge)),
    ), {"answer": ("retrieve",)})
    result = await LocalWorkflowEngine().start(workflow, WorkflowContext("run", input="refund"))
    assert result.stop_reason == WorkflowStopReason.FAILED and not loop.calls


@pytest.mark.asyncio
async def test_dataset_metadata_grants_no_authority_and_each_run_has_new_identity():
    contexts = []

    class Loop:
        async def run(self, definition, context):
            contexts.append(context)
            return RunResult(context.run_id, StopReason.COMPLETED, "answer", context.messages, (), 1, 0)

    case = EvaluationCase("case", "refund", metadata={"permissions": ["write"], "approved_call_ids": ["all"]})
    target = knowledge_evaluation_target(Loop(), AgentDefinition("a"), binding())
    await target(case)
    await target(case)
    assert contexts[0].run_id != contexts[1].run_id
    assert not contexts[0].tool_context.permissions and not contexts[0].tool_context.approved_call_ids
    assert not contexts[0].metadata and contexts[0].session_id is None
    explicit = knowledge_evaluation_target(Loop(), AgentDefinition("a"), binding(),
        tool_context=lambda case: ToolExecutionContext(permissions=frozenset({"host.read"})))
    await explicit(case)
    assert contexts[-1].tool_context.permissions == frozenset({"host.read"})


@pytest.mark.asyncio
async def test_workflow_custom_query_and_empty_evidence():
    knowledge = binding()
    query = lambda context: context.input["question"]
    context = WorkflowNodeContext("run", "retrieve", {"question": "absent"}, {}, {}, ScopePath.application(), None)
    payload = await knowledge_workflow_node("retrieve", knowledge, query=query).handler(context)
    assert payload["documents"] == []
    answer = WorkflowNodeContext("run", "answer", {"question": "absent"}, {}, {"retrieve": payload}, ScopePath.application(), None)
    messages = knowledge_workflow_messages("retrieve", knowledge, query=query)(answer)
    assert len(messages) == 1 and messages[0].content[0].text == "absent"


@pytest.mark.asyncio
async def test_workflow_rendering_bound_stops_before_agent():
    knowledge = LocalKnowledgeBinding(binding().retriever, limits=SessionHistoryLimits(max_output_bytes=8))
    with pytest.raises(KnowledgeRetrievalError):
        await knowledge_workflow_node("retrieve", knowledge).handler(node_context())


@pytest.mark.asyncio
async def test_evaluation_cancellation_while_retrieving_drains_and_never_calls_loop():
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow:
        async def retrieve(self, query, *, limit):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    loop = CountingLoop()
    target = knowledge_evaluation_target(loop, AgentDefinition("a"), LocalKnowledgeBinding(Slow()))
    task = asyncio.create_task(target(EvaluationCase("case", "query")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not loop.calls
