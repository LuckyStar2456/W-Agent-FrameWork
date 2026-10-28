"""Cross-entry acceptance; all service calls must use explicit offline doubles."""

import importlib
import json
import sys
import types
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

from w_agent.knowledge_plan_actions import (
    KnowledgeIndexHostBinding,
    KnowledgeIndexHostOptions,
    knowledge_index_host_scope,
)
from w_agent.knowledge_sync_qdrant import QdrantKnowledgeSyncWriter
from w_agent.tools.http_adapter import HttpToolResponse, HttpxToolTransport
from w_agent.vector_indexing import QdrantVectorWriter
from w_agent.vector_retrieval import QdrantVectorSearch


@pytest.mark.asyncio
async def test_editable_sync_host_import_and_both_bindings_perform_no_requests(monkeypatch):
    async def forbidden_send(*args, **kwargs):
        pytest.fail("host construction must not contact services")

    monkeypatch.setattr(HttpxToolTransport, "send", forbidden_send)
    example = importlib.import_module("examples.knowledge_sync_host")
    example = importlib.reload(example)
    entry = "examples.knowledge_sync_host:sync_catalog"
    async with knowledge_index_host_scope(KnowledgeIndexHostOptions(entry, "prepare", True)) as binding:
        assert binding.embedder.model == example.EMBEDDING_MODEL
        assert binding.dimensions == example.EMBEDDING_DIMENSIONS
        assert binding.embedding_key == example.EMBEDDING_REVISION
        endpoint = QdrantKnowledgeSyncWriter(binding.writer).endpoint
        assert endpoint == "http://localhost:6333/collections/dedicated_manual_sync/points"
    async with knowledge_index_host_scope(KnowledgeIndexHostOptions(entry, "execute", True)) as binding:
        assert binding.embedder is None
        assert QdrantKnowledgeSyncWriter(binding.writer).endpoint == endpoint


def test_registered_cli_full_sync_chain_reuses_persisted_vectors_and_separates_delete(monkeypatch, tmp_path):
    from w_agent.cli import app

    embeds, writes, lifecycle = [], [], []

    class Embedder:
        async def embed(self, text):
            embeds.append(text)
            return (1.0, 2.0)

    class Transport:
        async def send(self, request):
            writes.append(request)
            return HttpToolResponse(200, {}, b'{"status":"ok","result":{"status":"completed","operation_id":1}}')

    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "offline", transport=Transport()))

    @asynccontextmanager
    async def catalog():
        lifecycle.append("enter")
        try:
            yield {
                "prepare": KnowledgeIndexHostBinding(writer, Embedder(), "v1", 2),
                "execute": KnowledgeIndexHostBinding(writer),
            }
        finally:
            lifecycle.append("exit")

    module = types.ModuleType("sync_acceptance_host")
    module.catalog = catalog
    monkeypatch.setitem(sys.modules, module.__name__, module)
    runner = CliRunner()
    trace_db, journal = tmp_path / "trace.db", tmp_path / "sync.db"
    common = ["--journal-database", str(journal), "--confirm-read"]
    host = ["--host-entry", "sync_acceptance_host:catalog", "--confirm-code"]

    def invoke(command, *arguments):
        result = runner.invoke(app, [command, *arguments])
        assert result.exit_code == 0, result.output
        assert "PRIVATE_" not in result.output
        return json.loads(result.output)

    def prepare(version, previous=None):
        args = ["--trace-database", str(trace_db), "--root", str(tmp_path), "--path", "policy.md",
                "--namespace", "manual", "--version", version, "--confirm-read"]
        preview = invoke("knowledge-sync-import", *args)
        saved = invoke("knowledge-sync-import", *args, "--expected-preview-digest", preview["preview_digest"],
                       "--confirm-record", "--confirm-create")
        options = [] if previous is None else ["--previous-plan-digest", previous["plan_digest"],
                                               "--approved-reuse-digest", previous["current_index_digest"]]
        return invoke("knowledge-sync-prepare", *host, *common, "--binding", "prepare",
                      "--trace-database", str(trace_db), "--namespace", "manual", "--version", version,
                      "--expected-trace-digest", saved["trace_digest"], "--confirm-record", "--confirm-create",
                      "--confirm-embedding", *options)

    def execute_args(plan):
        return [*host, *common, "--binding", "execute", "--plan-digest", plan["plan_digest"],
                "--approved-plan-digest", plan["plan_digest"], "--approved-upsert-digest", plan["upsert_digest"],
                "--confirm-record"]

    (tmp_path / "policy.md").write_text("PRIVATE_POLICY first", encoding="utf-8")
    first = prepare("v1")
    assert len(embeds) == 1 and writes == []
    assert invoke("knowledge-sync-execute", *execute_args(first))["finished"]
    (tmp_path / "policy.md").write_text("PRIVATE_POLICY changed", encoding="utf-8")
    second = prepare("v2", first)
    assert len(embeds) == 2 and len(writes) == 1
    lifecycle_before = list(lifecycle)
    rejected = runner.invoke(app, ["knowledge-sync-execute", *execute_args(second)])
    assert rejected.exit_code == 2 and lifecycle == lifecycle_before and len(writes) == 1
    inspected = invoke("knowledge-sync-inspect", *common, "--plan-digest", second["plan_digest"])
    assert inspected["delete_points"] == 1 and lifecycle == lifecycle_before
    approved = [*execute_args(second), "--approved-delete-digest", second["delete_digest"]]
    assert invoke("knowledge-sync-execute", *approved)["finished"]
    assert len(writes) == 3 and writes[-1].url.endswith("/points/delete")
    assert invoke("knowledge-sync-execute", *approved)["finished"]
    assert len(writes) == 3 and len(embeds) == 2
    assert lifecycle == ["enter", "exit"] * (len(lifecycle) // 2)
