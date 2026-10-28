"""Versioned source spans, strict codecs and end-to-end offline sync acceptance."""

import asyncio
import hashlib
import json
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID

import pytest
import typer
from typer.testing import CliRunner

from w_agent.knowledge_archives import SQLiteKnowledgeRawArchive, archive_knowledge_sources
from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.knowledge_ingestion import Utf8KnowledgeTextSplitter, _json, prepare_knowledge_snapshot
from w_agent.knowledge_plan_actions import KnowledgeIndexHostBinding, KnowledgeIndexHostOptions
from w_agent.knowledge_provenance import TracedKnowledgeImport, prepare_traced_knowledge_import
from w_agent.knowledge_splitters import KnowledgeTextSpan, StructureKnowledgeSpanSplitter
from w_agent.knowledge_sync import KnowledgeSyncError, KnowledgeSyncIndex, knowledge_sync_point_ids
from w_agent.knowledge_sync_cli import register_knowledge_sync_commands
from w_agent.knowledge_sync_management import (
    KnowledgeSyncExecuteRequest, KnowledgeSyncImportRequest, KnowledgeSyncPrepareRequest,
    execute_local_knowledge_sync, import_local_knowledge_sync, prepare_local_knowledge_sync,
)
from w_agent.tools.http_adapter import HttpToolResponse
from w_agent.vector_indexing import QdrantVectorWriter
from w_agent.vector_retrieval import QdrantVectorSearch


async def imported(tmp_path, text="Repeated. Repeated.\n\n中文🙂重复。中文🙂重复。"):
    (tmp_path / "a.md").write_text(text, encoding="utf-8")
    return await LocalTextKnowledgeImporter(tmp_path).load(("a.md",), confirm_read=True)


def test_structural_preference_and_existing_split_protocol():
    text = "First paragraph.\n\nSecond sentence. Another sentence. Tail."
    splitter = StructureKnowledgeSpanSplitter(34, 2)
    spans = splitter.split_spans(text)
    assert text[:spans[0].char_end] == "First paragraph.\n\n"
    assert spans[1].char_start == spans[0].char_end - 2
    assert splitter.split(text) == tuple(text[item.char_start:item.char_end] for item in spans)


@pytest.mark.parametrize("text", ["🙂中文🙂中文🙂中文", "same same same same", "A. B. C. D. E.", "  \n\n  ", ""])
@pytest.mark.parametrize("size,overlap", [(4, 0), (8, 1), (16, 2), (64, 4)])
def test_unicode_offsets_progress_hard_bytes_and_coverage(text, size, overlap):
    spans = StructureKnowledgeSpanSplitter(size, overlap).split_spans(text)
    covered = set()
    last_start = last_end = -1
    for span in spans:
        assert span.char_start > last_start and span.char_end > last_end
        assert text.encode()[span.byte_start:span.byte_end].decode() == text[span.char_start:span.char_end]
        assert span.byte_end - span.byte_start <= size
        assert last_end - span.char_start <= overlap
        covered.update(range(span.char_start, span.char_end))
        last_start, last_end = span.char_start, span.char_end
    assert all(position in covered for position, char in enumerate(text) if not char.isspace())


@pytest.mark.parametrize("size,overlap", [(3, 0), (4, 1), (8, 2), (8192, 1025), (16, -1), (16, True)])
def test_invalid_or_extreme_overlap_rejected(size, overlap):
    with pytest.raises(ValueError):
        StructureKnowledgeSpanSplitter(size, overlap)


def test_output_chunk_explosion_bounded():
    with pytest.raises(ValueError, match="expansion"):
        StructureKnowledgeSpanSplitter(4).split_spans("x" * 4100)
    with pytest.raises(ValueError):
        KnowledgeTextSpan(0, 0, 0, 0)


@pytest.mark.asyncio
async def test_legacy_v1_serialization_and_point_ids_remain_exact(tmp_path):
    source = await imported(tmp_path)
    trace = prepare_traced_knowledge_import("manual", "v1", source, chunk_bytes=16)
    snapshot = prepare_knowledge_snapshot("manual", "v1", source.documents, splitter=Utf8KnowledgeTextSplitter(16))
    expected = _json({"format": "wagent-traced-knowledge-import-v1", "chunk_bytes": 16,
        "manifest": json.loads(source.to_manifest_json()),
        "sources": [{"id": item.document_id, "text": item.text, "source": item.source, "title": item.title} for item in source.documents],
        "snapshot": json.loads(snapshot.to_json()), "origins": [origin.to_dict() for origin in trace.origins]})
    assert trace.to_json() == expected and trace.snapshot == snapshot
    record = source.records[0]
    old_ids = tuple(str(UUID(bytes=hashlib.sha256(_json([
        "wagent-knowledge-sync-point-v1", "manual", source.parser_key, record.to_dict(), 16,
        origin.char_start, origin.char_end, origin.byte_start, origin.byte_end,
        chunk.text, chunk.source, chunk.title, "model-v1", 2,
    ]).encode()).digest()[:16])) for chunk, origin in zip(snapshot.documents, trace.origins))
    assert knowledge_sync_point_ids(trace, "model-v1", 2) == old_ids
    assert TracedKnowledgeImport.from_json(expected, expected_digest=hashlib.sha256(expected.encode()).hexdigest()) == trace


@pytest.mark.asyncio
async def test_v2_roundtrip_repeated_text_offsets_store_archive_and_identity(tmp_path):
    source = await imported(tmp_path)
    trace = prepare_traced_knowledge_import("manual", "v1", source, chunk_bytes=24, splitter="structure", overlap_chars=2)
    assert '"wagent-traced-knowledge-import-v2"' in trace.to_json()
    assert any(right.char_start < left.char_end for left, right in zip(trace.origins, trace.origins[1:]))
    assert TracedKnowledgeImport.from_json(trace.to_json(), expected_digest=trace.digest) == trace
    store = SQLiteKnowledgeImportStore(tmp_path / "trace.db")
    await store.initialize(confirm_create=True)
    await store.save(trace, confirm_write=True)
    assert await store.load("manual", "v1") == trace
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    receipt = await archive_knowledge_sources(trace, tmp_path, archive, expected_trace_digest=trace.digest, confirm_read=True, confirm_write=True)
    assert await archive.load(receipt.blob_digests[0], confirm_read=True) == (tmp_path / "a.md").read_bytes()
    newer = prepare_traced_knowledge_import("manual", "v2", source, chunk_bytes=24, splitter="structure", overlap_chars=2)
    assert knowledge_sync_point_ids(trace, "model-v1", 2) == knowledge_sync_point_ids(newer, "model-v1", 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["overlap", "algorithm", "offset", "extra", "v1", "chunk"])
async def test_v2_strict_self_validation_even_with_rehashed_envelope(tmp_path, tamper):
    trace = prepare_traced_knowledge_import("manual", "v1", await imported(tmp_path), chunk_bytes=24, splitter="structure", overlap_chars=2)
    value = json.loads(trace.to_json())
    if tamper == "overlap":
        value["splitting"]["overlap_chars"] = 1
    elif tamper == "algorithm":
        value["splitting"]["algorithm"] = "untrusted:factory"
    elif tamper == "offset":
        value["origins"][1]["char_start"] += 1
    elif tamper == "extra":
        value["splitting"]["unused"] = 1
    elif tamper == "chunk":
        value["splitting"]["chunk_bytes"] = 23
    else:
        value["format"] = "wagent-traced-knowledge-import-v1"
        del value["splitting"]
    payload = _json(value)
    with pytest.raises(ValueError, match="invalid traced"):
        TracedKnowledgeImport.from_json(payload, expected_digest=hashlib.sha256(payload.encode()).hexdigest())


@pytest.mark.asyncio
async def test_different_configuration_same_text_does_not_reuse_point_identity(tmp_path):
    source = await imported(tmp_path, "tiny")
    traces = [prepare_traced_knowledge_import("n", "v", source, chunk_bytes=32),
              prepare_traced_knowledge_import("n", "v", source, chunk_bytes=32, splitter="structure"),
              prepare_traced_knowledge_import("n", "v", source, chunk_bytes=32, splitter="structure", overlap_chars=1)]
    assert {trace.snapshot.documents[0].text for trace in traces} == {"tiny"}
    assert len({knowledge_sync_point_ids(trace, "model", 2)[0] for trace in traces}) == 3


@pytest.mark.asyncio
async def test_management_preview_lock_parameters_and_worker_cancel_no_save(tmp_path, monkeypatch):
    await imported(tmp_path)
    request = KnowledgeSyncImportRequest(tmp_path / "trace.db", tmp_path, ("a.md",), "n", "v", chunk_bytes=24,
                                        confirm_read=True, splitter="structure", overlap_chars=2)
    preview = await import_local_knowledge_sync(request)
    with pytest.raises(KnowledgeSyncError, match="preview-changed"):
        await import_local_knowledge_sync(replace(request, overlap_chars=1, confirm_record=True, confirm_create=True,
            expected_preview_digest=preview["preview_digest"]))
    import w_agent.knowledge_sync_management as management
    original = management.prepare_traced_knowledge_import
    entered, released = threading.Event(), threading.Event()
    def blocking(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(management, "prepare_traced_knowledge_import", blocking)
    task = asyncio.create_task(import_local_knowledge_sync(replace(request, confirm_record=True, confirm_create=True,
        expected_preview_digest=preview["preview_digest"])))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
    finally:
        released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not request.trace_database.exists()


@pytest.mark.asyncio
async def test_management_v2_prepare_execute_and_version_only_cache_reuse(tmp_path, monkeypatch):
    import w_agent.knowledge_sync_management as management
    await imported(tmp_path)
    embeddings, sends = [], []
    class Embedder:
        async def embed(self, text):
            embeddings.append(text)
            return (1.0, 2.0)
    class Transport:
        async def send(self, request):
            sends.append(request)
            return HttpToolResponse(200, {}, b'{"status":"ok","result":{"status":"completed","operation_id":1}}')
    @asynccontextmanager
    async def host(options):
        yield KnowledgeIndexHostBinding(QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "dedicated", transport=Transport())), Embedder(), "model", 2)
    monkeypatch.setattr(management, "knowledge_index_host_scope", host)
    previous = None
    for version in ("v1", "v2"):
        request = KnowledgeSyncImportRequest(tmp_path / "trace.db", tmp_path, ("a.md",), "n", version, chunk_bytes=24,
                                            confirm_read=True, splitter="structure", overlap_chars=2)
        preview = await import_local_knowledge_sync(request)
        await import_local_knowledge_sync(replace(request, confirm_record=True, confirm_create=True, expected_preview_digest=preview["preview_digest"]))
        plan = await prepare_local_knowledge_sync(KnowledgeSyncPrepareRequest(KnowledgeIndexHostOptions("trusted:factory", "index", True),
            request.trace_database, "n", version, tmp_path / "sync.db", preview["trace_digest"],
            previous_plan_digest=previous["plan_digest"] if previous else None,
            approved_reuse_digest=previous["current_index_digest"] if previous else None,
            confirm_read=True, confirm_record=True, confirm_create=True, confirm_embedding=previous is None))
        if previous is None:
            first_count = len(embeddings)
            result = await execute_local_knowledge_sync(KnowledgeSyncExecuteRequest(KnowledgeIndexHostOptions("trusted:factory", "index", True),
                tmp_path / "sync.db", plan["plan_digest"], plan["plan_digest"], plan["upsert_digest"], confirm_read=True, confirm_record=True))
            assert result["finished"] and len(sends) == 1
        else:
            assert plan["finished"] and plan["upsert_points"] == 0 and len(embeddings) == first_count and len(sends) == 1
        previous = plan


def test_cli_structural_preview_locked_save(tmp_path):
    (tmp_path / "a.md").write_text("Repeated. Repeated. 中文🙂重复。", encoding="utf-8")
    app = typer.Typer()
    register_knowledge_sync_commands(app)
    args = ["knowledge-sync-import", "--root", str(tmp_path), "--trace-database", str(tmp_path / "trace.db"),
            "--path", "a.md", "--namespace", "n", "--version", "v", "--chunk-bytes", "24", "--splitter", "structure",
            "--overlap-chars", "2", "--confirm-read"]
    preview = CliRunner().invoke(app, args)
    assert preview.exit_code == 0, preview.output
    saved = CliRunner().invoke(app, args + ["--expected-preview-digest", json.loads(preview.output)["preview_digest"], "--confirm-record", "--confirm-create"])
    assert saved.exit_code == 0, saved.output
    trace = asyncio.run(SQLiteKnowledgeImportStore(tmp_path / "trace.db").load("n", "v"))
    assert trace.splitter == "structure" and trace.overlap_chars == 2
