"""Cross-module local acceptance using real persistence and an offline provider."""

import json
from dataclasses import replace

import pytest

from w_agent import (
    BM25KnowledgeReranker, BM25KnowledgeRetriever, BlockEnd, BlockStart,
    DagWorkflowDefinition, EvaluationCase, ExactTextScorer, FinishEvent, FinishReason,
    HybridKnowledgeRetriever, InMemoryKnowledgeDocumentStore, JsonlWorkflowStore,
    KeywordKnowledgeRetriever, LocalEvaluationRunner, LocalKnowledgeBinding,
    LocalKnowledgeRequest, LocalWorkflowEngine, MessageRole, ModelCapability,
    ModelDescriptor, ProviderTemplate, ProviderTemplateRegistry, RerankedKnowledgeRetriever,
    SQLiteKnowledgeSnapshotStore, TextContent, TokenUsage, UsageEvent, WorkflowContext,
    WorkflowStopReason, agent_workflow_node, assemble_local_runtime,
    knowledge_evaluation_target, knowledge_workflow_messages, knowledge_workflow_node,
    local_runtime_config_from_mapping, manage_local_knowledge,
)


class EvidenceProvider:
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def list_models(self):
        return (await self.resolve("offline"),)

    async def resolve(self, model):
        return ModelDescriptor("offline", "offline", frozenset({
            ModelCapability.TEXT_INPUT, ModelCapability.TEXT_OUTPUT,
        }))

    async def stream(self, request, *, cancellation=None):
        self.calls += 1
        evidence = next(message for message in request.messages
                        if "untrusted reference" in getattr(message.content[0], "text", ""))
        assert evidence.role == MessageRole.USER
        payload = json.loads(evidence.content[0].text.split("\n", 1)[1])
        yield BlockStart(0, "text")
        yield BlockEnd(0, TextContent(payload["documents"][0]["text"]))
        yield UsageEvent(TokenUsage(3, 2))
        yield FinishEvent(FinishReason.STOP)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_import_persist_hybrid_workflow_agent_and_evaluation(tmp_path):
    text = "refund within seven days"
    (tmp_path / "policy.txt").write_text(text, encoding="utf-8")
    request = LocalKnowledgeRequest(
        "import", tmp_path / "knowledge.db", namespace="support", version="v1",
        root=tmp_path, paths=("policy.txt",), confirm_read=True,
    )
    preview = await manage_local_knowledge(request)
    saved = await manage_local_knowledge(replace(
        request, confirm_write=True, confirm_create=True,
        expected_preview_digest=preview["preview_digest"],
    ))
    assert saved["preview_locked"] and saved["digest"] == preview["digest"]
    snapshot = await SQLiteKnowledgeSnapshotStore(request.database).load("support", "v1")
    documents = InMemoryKnowledgeDocumentStore(snapshot.documents)
    retrieval = RerankedKnowledgeRetriever(
        HybridKnowledgeRetriever((BM25KnowledgeRetriever(documents), KeywordKnowledgeRetriever(documents))),
        BM25KnowledgeReranker(),
    )
    binding = LocalKnowledgeBinding(retrieval, limit=1)
    provider = EvidenceProvider()
    config = local_runtime_config_from_mapping({
        "provider": {"template": "offline", "name": "offline", "model": "offline"},
    })
    templates = ProviderTemplateRegistry((ProviderTemplate(
        "offline", "Offline acceptance", "offline", None, lambda **kwargs: provider,
    ),))
    async with assemble_local_runtime(config, tmp_path / "runtime", templates=templates) as runtime:
        workflow = DagWorkflowDefinition("support", (
            knowledge_workflow_node("retrieve", binding),
            agent_workflow_node("answer", runtime.loop, runtime.definition,
                                messages=knowledge_workflow_messages("retrieve", binding)),
        ), {"answer": ("retrieve",)})
        store = JsonlWorkflowStore(tmp_path / "workflow")
        result = await LocalWorkflowEngine(store).start(workflow, WorkflowContext("acceptance", input="refund"))
        assert result.stop_reason == WorkflowStopReason.COMPLETED
        assert result.outputs["answer"]["output"] == text
        report = await LocalEvaluationRunner().run(
            (EvaluationCase("support-case", "refund", text),),
            knowledge_evaluation_target(runtime.loop, runtime.definition, binding),
            scorers=(ExactTextScorer(),),
        )
        assert report.passed == 1 and report.errors == 0 and report.usage.total_tokens == 5
    assert provider.calls == 2 and provider.closed
