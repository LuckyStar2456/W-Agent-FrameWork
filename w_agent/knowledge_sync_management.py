"""Explicit local trace/plan management shared by CLI and TUI.

No factory is imported for inspection or local recovery. Preparation persists
an exact plan and reserves its target; it never sends vector writes. A failed
preparation may already have incurred embedding charges, and is not replay-safe.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_files import LocalTextKnowledgeImporter, _digest, _relative
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.knowledge_ingestion import Utf8KnowledgeTextSplitter, _json, _label
from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions, knowledge_index_host_scope
from w_agent.knowledge_parsers import OptionalDocumentKnowledgeParser
from w_agent.knowledge_provenance import prepare_traced_knowledge_import
from w_agent.knowledge_sync import (
    KnowledgeSyncError, KnowledgeSyncPlan, KnowledgeSyncStatus, execute_knowledge_sync,
    knowledge_sync_retry_digest, prepare_knowledge_sync_index,
)
from w_agent.knowledge_sync_qdrant import QdrantKnowledgeSyncWriter
from w_agent.knowledge_sync_store import SQLiteKnowledgeSyncJournal
from w_agent.knowledge_splitters import StructureKnowledgeSpanSplitter
from w_agent.knowledge_sqlite import _worker


def _flags(request: object, *required: str) -> None:
    for name in request.__dataclass_fields__:
        if name.startswith("confirm_") and type(getattr(request, name)) is not bool:
            raise ValueError("sync confirmations must be boolean")
    if any(getattr(request, name) is not True for name in required):
        raise ValueError("sync operation requires explicit confirmation")


def _host(value: KnowledgeIndexHostOptions) -> None:
    if not isinstance(value, KnowledgeIndexHostOptions):
        raise ValueError("typed sync host options required")


@dataclass(frozen=True, slots=True)
class KnowledgeSyncImportRequest:
    trace_database: Path = field(repr=False)
    root: Path = field(repr=False)
    paths: tuple[str, ...] = field(repr=False)
    namespace: str
    version: str
    chunk_bytes: int = 4096
    recursive: bool = False
    expected_preview_digest: str | None = None
    confirm_read: bool = False
    confirm_record: bool = False
    confirm_create: bool = False
    document_formats: bool = False
    splitter: str = "utf8"
    overlap_chars: int = 0

    def __post_init__(self) -> None:
        _flags(self, "confirm_read")
        if type(self.document_formats) is not bool:
            raise ValueError("document format selection must be boolean")
        _label(self.namespace)
        _label(self.version)
        SQLiteKnowledgeImportStore(self.trace_database)
        LocalTextKnowledgeImporter(self.root, recursive=self.recursive)
        Utf8KnowledgeTextSplitter(self.chunk_bytes)
        if self.splitter == "structure":
            StructureKnowledgeSpanSplitter(self.chunk_bytes, self.overlap_chars)
        elif self.splitter != "utf8" or type(self.overlap_chars) is not int or self.overlap_chars != 0:
            raise ValueError("invalid sync splitting configuration")
        if not isinstance(self.paths, tuple) or len(self.paths) > 1024 or len(set(self.paths)) != len(self.paths):
            raise ValueError("invalid sync import selection")
        for path in self.paths:
            _relative(path, allow_root=True)
        if self.expected_preview_digest is not None:
            _digest(self.expected_preview_digest)
        if self.confirm_create and not self.confirm_record:
            raise ValueError("sync import creation requires recording")
        if self.confirm_record and self.expected_preview_digest is None:
            raise ValueError("sync import recording requires exact preview approval")


@dataclass(frozen=True, slots=True)
class KnowledgeSyncPrepareRequest:
    host: KnowledgeIndexHostOptions = field(repr=False)
    trace_database: Path = field(repr=False)
    namespace: str
    version: str
    journal_database: Path = field(repr=False)
    expected_trace_digest: str
    previous_plan_digest: str | None = None
    approved_reuse_digest: str | None = None
    confirm_read: bool = False
    confirm_embedding: bool = False
    confirm_record: bool = False
    confirm_create: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_record")
        _host(self.host)
        _label(self.namespace)
        _label(self.version)
        _digest(self.expected_trace_digest)
        for value in (self.previous_plan_digest, self.approved_reuse_digest):
            if value is not None:
                _digest(value)
        if self.previous_plan_digest is None and self.approved_reuse_digest is not None:
            raise ValueError("sync reuse requires a previous plan")
        source = SQLiteKnowledgeImportStore(self.trace_database).database_path
        target = SQLiteKnowledgeSyncJournal(self.journal_database).database_path
        if source.resolve() == target.resolve():
            raise ValueError("sync trace and journal databases must differ")


@dataclass(frozen=True, slots=True)
class KnowledgeSyncInspectRequest:
    journal_database: Path = field(repr=False)
    plan_digest: str
    confirm_read: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read")
        SQLiteKnowledgeSyncJournal(self.journal_database)
        _digest(self.plan_digest)


@dataclass(frozen=True, slots=True)
class KnowledgeSyncExecuteRequest:
    host: KnowledgeIndexHostOptions = field(repr=False)
    journal_database: Path = field(repr=False)
    plan_digest: str
    approved_plan_digest: str
    approved_upsert_digest: str | None = None
    approved_delete_digest: str | None = None
    confirm_read: bool = False
    confirm_record: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_record")
        _host(self.host)
        SQLiteKnowledgeSyncJournal(self.journal_database)
        _digest(self.plan_digest)
        _digest(self.approved_plan_digest)
        if self.plan_digest != self.approved_plan_digest:
            raise ValueError("sync plan approval mismatch")
        for value in (self.approved_upsert_digest, self.approved_delete_digest):
            if value is not None:
                _digest(value)


@dataclass(frozen=True, slots=True)
class KnowledgeSyncRetryRequest:
    journal_database: Path = field(repr=False)
    plan_digest: str
    batch: int
    generation: int
    retry_id: str = field(repr=False)
    approved_retry_digest: str
    confirm_read: bool = False
    confirm_record: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_record")
        SQLiteKnowledgeSyncJournal(self.journal_database)
        _label(self.retry_id)
        if self.approved_retry_digest != knowledge_sync_retry_digest(self.plan_digest, self.batch, self.generation):
            raise ValueError("sync retry approval mismatch")


@dataclass(frozen=True, slots=True)
class KnowledgeSyncReconcileRequest:
    journal_database: Path = field(repr=False)
    plan_digest: str
    batch: int
    evidence_ref: str = field(repr=False)
    approved_plan_digest: str
    confirm_read: bool = False
    confirm_record: bool = False
    confirm_applied: bool = False
    confirm_inactive: bool = False

    def __post_init__(self) -> None:
        _flags(self, "confirm_read", "confirm_record", "confirm_applied", "confirm_inactive")
        SQLiteKnowledgeSyncJournal(self.journal_database)
        _digest(self.plan_digest)
        if self.approved_plan_digest != self.plan_digest:
            raise ValueError("sync reconciliation approval mismatch")
        if type(self.batch) is not int or not 0 <= self.batch < 16:
            raise ValueError("sync batch invalid")
        _label(self.evidence_ref)


def knowledge_sync_summary(plan: KnowledgeSyncPlan, status: KnowledgeSyncStatus) -> dict:
    """Pure body/vector/path/endpoint/evidence-free projection of validated data."""
    if (not isinstance(plan, KnowledgeSyncPlan) or not isinstance(status, KnowledgeSyncStatus)
            or status.plan_digest != plan.digest or len(status.outcomes) != len(plan.batches)):
        raise ValueError("sync summary requires matching plan/status")
    result = plan.summary()
    result.update(finished=status.finished, outcomes=list(status.outcomes),
                  trace_digest=plan.current.trace.digest, target_digest=plan.target_key)
    result["batches"] = [
        {"batch": number, "operation": "upsert" if number < (len(plan.upsert_points) + 127) // 128 else "delete",
         "digest": batch.digest, "outcome": status.outcomes[number]}
        for number, batch in enumerate(plan.batches)
    ]
    return result


async def import_local_knowledge_sync(request: KnowledgeSyncImportRequest) -> dict:
    if not isinstance(request, KnowledgeSyncImportRequest):
        raise ValueError("typed sync import request required")
    parser_options = {}
    parser_config = {"selection": "utf8"}
    if request.document_formats:
        parser = OptionalDocumentKnowledgeParser()
        parser_options = {"parser": parser, "suffixes": parser.suffixes}
        parser_config = {"selection": "optional-documents", "parser_key": parser.parser_key,
                         "max_text_bytes": parser.max_text_bytes, "max_zip_bytes": parser.max_zip_bytes,
                         "max_zip_entries": parser.max_zip_entries, "suffixes": list(parser.suffixes)}
    imported = await LocalTextKnowledgeImporter(request.root, recursive=request.recursive, **parser_options).load(request.paths, confirm_read=True)
    trace = await _worker(lambda: prepare_traced_knowledge_import(
        request.namespace, request.version, imported, chunk_bytes=request.chunk_bytes,
        splitter=request.splitter, overlap_chars=request.overlap_chars,
    ))
    # Digest binds exact content/configuration AND local source/destination choices.
    preview_fields = {"format": "wagent-sync-import-preview-v1", "trace": trace.digest,
                                   "root": str(Path(request.root).resolve()), "paths": list(request.paths),
                                   "recursive": request.recursive,
                                   "parser": parser_config,
                                   "database": str(Path(request.trace_database).resolve())}
    if request.splitter == "structure":
        preview_fields["splitting"] = trace.splitting_config
    preview = hashlib.sha256(_json(preview_fields).encode()).hexdigest()
    if request.expected_preview_digest is not None and request.expected_preview_digest != preview:
        raise KnowledgeSyncError("knowledge-sync-import-preview-changed")
    if request.confirm_record:
        store = SQLiteKnowledgeImportStore(request.trace_database)
        if request.confirm_create:
            await store.initialize(confirm_create=True)
        await store.save(trace, confirm_write=True)
    return {"preview_digest": preview, "trace_digest": trace.digest, "namespace": request.namespace,
            "version": request.version, "files": len(imported.records), "chunks": len(trace.snapshot.documents),
            "recorded": request.confirm_record, "remote_verified": False}


async def prepare_local_knowledge_sync(request: KnowledgeSyncPrepareRequest) -> dict:
    if not isinstance(request, KnowledgeSyncPrepareRequest):
        raise ValueError("typed sync prepare request required")
    trace = await SQLiteKnowledgeImportStore(request.trace_database).load(request.namespace, request.version)
    if trace.digest != request.expected_trace_digest:
        raise KnowledgeSyncError("knowledge-sync-trace-approval-mismatch")
    journal = SQLiteKnowledgeSyncJournal(request.journal_database)
    if request.confirm_create:
        await journal.initialize(confirm_create=True)
    else:
        await journal.validate_existing()
    previous_plan = None
    if request.previous_plan_digest is not None:
        previous_plan = await journal.load_plan(request.previous_plan_digest)
        status = await journal.inspect(request.previous_plan_digest)
        if not status.finished or request.approved_reuse_digest != previous_plan.current.digest:
            raise KnowledgeSyncError("knowledge-sync-predecessor-not-approved")
    async with knowledge_index_host_scope(request.host) as binding:
        adapter = QdrantKnowledgeSyncWriter(binding.writer)
        if binding.embedder is None:
            raise KnowledgeSyncError("knowledge-sync-prepare-requires-embedding-binding")
        if previous_plan is not None and (adapter.endpoint, adapter.vector_name) != (previous_plan.endpoint, previous_plan.vector_name):
            raise KnowledgeSyncError("knowledge-sync-predecessor-target-mismatch")
        await journal.preflight_target(adapter.endpoint, adapter.vector_name,
                                       previous_plan.current.digest if previous_plan is not None else None)
        current = await prepare_knowledge_sync_index(
            trace, binding.embedding_key, binding.dimensions, binding.embedder,
            previous=previous_plan.current if previous_plan is not None else None,
            confirm_embedding=request.confirm_embedding, confirm_reuse_digest=request.approved_reuse_digest,
        )
        plan = KnowledgeSyncPlan(adapter.endpoint, adapter.vector_name, current,
                                 previous_plan.current if previous_plan is not None else None)
        status = await journal.stage(plan, confirm_write=True)
        result = knowledge_sync_summary(plan, status)
    return result


async def inspect_local_knowledge_sync(request: KnowledgeSyncInspectRequest) -> dict:
    if not isinstance(request, KnowledgeSyncInspectRequest):
        raise ValueError("typed sync inspect request required")
    journal = SQLiteKnowledgeSyncJournal(request.journal_database)
    plan = await journal.load_plan(request.plan_digest)
    status = await journal.inspect(request.plan_digest)
    retries = await journal.inspect_retries(request.plan_digest)
    result = knowledge_sync_summary(plan, status)
    result["retry_count"] = len(retries)
    result["retry_exhausted"] = len(retries) >= 64
    # Offer approvals only for definite not-sent; never offer uncertain replay.
    result["retry_candidates"] = []
    for batch, outcome in enumerate(status.outcomes):
        if outcome == "not-sent" and len(retries) < 64:
            generation = sum(item.batch == batch for item in retries)
            result["retry_candidates"].append({"batch": batch, "generation": generation,
                "retry_digest": knowledge_sync_retry_digest(plan.digest, batch, generation)})
    return result


async def execute_local_knowledge_sync(request: KnowledgeSyncExecuteRequest) -> dict:
    if not isinstance(request, KnowledgeSyncExecuteRequest):
        raise ValueError("typed sync execute request required")
    journal = SQLiteKnowledgeSyncJournal(request.journal_database)
    plan = await journal.load_plan(request.plan_digest)
    if ((plan.upsert_points and request.approved_upsert_digest != plan.upsert_digest)
            or (plan.delete_ids and request.approved_delete_digest != plan.delete_digest)):
        raise KnowledgeSyncError("knowledge-sync-action-approval-mismatch")
    status = await journal.inspect(plan.digest)
    if any(outcome not in {"ready", "completed"} for outcome in status.outcomes):
        raise KnowledgeSyncError("knowledge-sync-unresolved-no-replay")
    async with knowledge_index_host_scope(request.host) as binding:
        status = await execute_knowledge_sync(
            plan, QdrantKnowledgeSyncWriter(binding.writer), journal,
            confirm_plan_digest=request.approved_plan_digest,
            confirm_upsert_digest=request.approved_upsert_digest,
            confirm_delete_digest=request.approved_delete_digest, confirm_record=True,
        )
        result = knowledge_sync_summary(plan, status)
    return result


async def retry_local_knowledge_sync(request: KnowledgeSyncRetryRequest) -> dict:
    if not isinstance(request, KnowledgeSyncRetryRequest):
        raise ValueError("typed sync retry request required")
    journal = SQLiteKnowledgeSyncJournal(request.journal_database)
    plan = await journal.load_plan(request.plan_digest)
    status = await journal.retry_not_sent(plan.digest, request.batch, generation=request.generation,
        retry_id=request.retry_id, confirm_retry_digest=request.approved_retry_digest, confirm_write=True)
    return knowledge_sync_summary(plan, status)


async def reconcile_local_knowledge_sync(request: KnowledgeSyncReconcileRequest) -> dict:
    if not isinstance(request, KnowledgeSyncReconcileRequest):
        raise ValueError("typed sync reconcile request required")
    journal = SQLiteKnowledgeSyncJournal(request.journal_database)
    plan = await journal.load_plan(request.plan_digest)
    status = await journal.reconcile_completed(plan.digest, request.batch, evidence_ref=request.evidence_ref,
        confirm_applied=True, confirm_inactive=True, confirm_write=True)
    return knowledge_sync_summary(plan, status)
