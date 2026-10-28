"""Explicit host-backed prepare/save and approved execution, shared by CLI/TUI."""

from __future__ import annotations

import importlib
import inspect
import json
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_context import _identity
from w_agent.knowledge_index_journal import SQLiteKnowledgeIndexJournal, _digest
from w_agent.knowledge_index_plans import execute_prepared_knowledge_plan, prepare_knowledge_index_plan
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_plan_sqlite import SQLiteKnowledgeIndexPlanStore
from w_agent.knowledge_build_recovery import SQLiteKnowledgePreparationStore, prepare_recoverable_knowledge_plan
from w_agent.knowledge_runtime import LocalKnowledgeConfig
from w_agent.knowledge_sqlite import SQLiteKnowledgeSnapshotStore
from w_agent.knowledge_vectors import KnowledgeVectorIndex
from w_agent.vector_indexing import QdrantVectorWriter
from w_agent.vector_retrieval import AsyncTextEmbedder, _integer, _reject_constant


class KnowledgePlanActionError(RuntimeError):
    """Fixed action/lifecycle errors; prior billing/writes may already have happened."""


@dataclass(frozen=True, slots=True)
class KnowledgeIndexHostOptions:
    entry: str = field(repr=False)
    binding: str
    confirm_code: bool = False

    def __post_init__(self) -> None:
        if (not isinstance(self.entry, str) or len(self.entry) > 512
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", self.entry, flags=re.ASCII)):
            raise ValueError("index host requires module:factory")
        LocalKnowledgeConfig(self.binding)
        if self.confirm_code is not True:
            raise ValueError("index host code requires explicit confirmation")


@dataclass(frozen=True, slots=True)
class KnowledgeIndexHostBinding:
    """Borrowed Qdrant template; execution-only hosts may omit the embedder.

    Factories own setup/cleanup. embedding_key is a host revision label, not an
    independently verified identity. Embedder may be a shared-budget wrapper.
    """

    writer: QdrantVectorWriter = field(repr=False)
    embedder: AsyncTextEmbedder | None = field(default=None, repr=False)
    embedding_key: str | None = field(default=None, repr=False)
    dimensions: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.writer, QdrantVectorWriter):
            raise ValueError("index host requires a Qdrant writer")
        if self.embedder is None:
            if self.embedding_key is not None or self.dimensions is not None:
                raise ValueError("embedding configuration requires an embedder")
        else:
            if not callable(getattr(self.embedder, "embed", None)):
                raise ValueError("index host embedder is invalid")
            _label(self.embedding_key)
            _integer(self.dimensions, 65536)


@asynccontextmanager
async def knowledge_index_host_scope(options: KnowledgeIndexHostOptions) -> AsyncIterator[KnowledgeIndexHostBinding]:
    """Load authorized trusted local code; never sandbox or suppress action errors."""
    if not isinstance(options, KnowledgeIndexHostOptions):
        raise ValueError("typed index host options required")
    try:
        module, name = options.entry.split(":")
        context = getattr(importlib.import_module(module), name)()
        if inspect.iscoroutine(context):
            context.close()
            raise ValueError
        if any(not callable(getattr(context, key, None)) for key in ("__aenter__", "__aexit__")):
            raise ValueError
        catalog = await context.__aenter__()
    except Exception:
        raise KnowledgePlanActionError("index-host-setup-failed; inspect state before retry") from None
    try:
        try:
            if not isinstance(catalog, Mapping) or not 1 <= len(catalog) <= 64:
                raise ValueError
            bindings = dict(catalog)
            for key, binding in bindings.items():
                LocalKnowledgeConfig(key)
                if not isinstance(binding, KnowledgeIndexHostBinding):
                    raise ValueError
            selected = bindings[options.binding]
        except Exception:
            raise KnowledgePlanActionError("index-host-catalog-invalid") from None
        yield selected
    except BaseException as error:
        try:
            await context.__aexit__(type(error), error, error.__traceback__)
        except Exception:
            error.add_note("Index host cleanup also failed; inspect state before retry.")
        raise
    else:
        try:
            await context.__aexit__(None, None, None)
        except Exception:
            raise KnowledgePlanActionError("index-host-cleanup-failed; inspect state before retry") from None


def parse_knowledge_document_ids(value: str | None) -> tuple[str | int, ...] | None:
    """Bounded UI selection; None explicitly selects a whole single-batch snapshot."""
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value.encode("utf-8")) > 65536:
            raise ValueError
        parsed = json.loads(value, parse_constant=_reject_constant)
        if not isinstance(parsed, list):
            raise ValueError
        result = tuple(parsed)
        _selection(result)
        return result
    except Exception:
        raise ValueError("invalid document ID selection") from None


def _selection(value: tuple[str | int, ...] | None) -> None:
    if value is None:
        return
    if not isinstance(value, tuple) or not 1 <= len(value) <= 128:
        raise ValueError("selected IDs must be a nonempty bounded tuple")
    for identity in value:
        _identity(identity)
    if len(set(value)) != len(value):
        raise ValueError("selected IDs must be unique")


@dataclass(frozen=True, slots=True)
class KnowledgePlanPrepareRequest:
    host: KnowledgeIndexHostOptions
    source_database: Path = field(repr=False)
    namespace: str
    version: str
    plan_database: Path = field(repr=False)
    document_ids: tuple[str | int, ...] | None = field(default=None, repr=False)
    confirm_read: bool = False
    confirm_embedding: bool = False
    confirm_save: bool = False
    confirm_create: bool = False
    include_target: bool = False
    preparation_database: Path | None = field(default=None, repr=False)
    preparation_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.host, KnowledgeIndexHostOptions):
            raise ValueError("index host options required")
        if any(flag is not True for flag in (self.confirm_read, self.confirm_save)):
            raise ValueError("prepare requires separate read, embedding and save consent")
        if type(self.confirm_embedding) is not bool or (self.preparation_database is None and not self.confirm_embedding):
            raise ValueError("fresh preparation requires embedding consent")
        if any(type(flag) is not bool for flag in (self.confirm_create, self.include_target)):
            raise ValueError("plan switches must be booleans")
        _label(self.namespace)
        _label(self.version)
        _selection(self.document_ids)
        object.__setattr__(self, "source_database", SQLiteKnowledgeSnapshotStore(self.source_database).database_path)
        object.__setattr__(self, "plan_database", SQLiteKnowledgeIndexPlanStore(self.plan_database).database_path)
        if self.source_database == self.plan_database:
            raise ValueError("source and plan databases must differ")
        if self.preparation_database is not None:
            _label(self.preparation_attempt_id)
            object.__setattr__(self, "preparation_database", SQLiteKnowledgePreparationStore(self.preparation_database).database_path)
            if self.preparation_database in {self.source_database, self.plan_database}:
                raise ValueError("preparation, source and plan databases must differ")
        elif self.preparation_attempt_id is not None:
            raise ValueError("preparation attempt requires its checkpoint database")


@dataclass(frozen=True, slots=True)
class KnowledgePlanExecuteRequest:
    host: KnowledgeIndexHostOptions
    plan_database: Path = field(repr=False)
    artifact_digest: str
    approved_digest: str
    journal_database: Path = field(repr=False)
    attempt_id: str
    confirm_read: bool = False
    confirm_remote_write: bool = False
    confirm_record: bool = False
    confirm_create_journal: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.host, KnowledgeIndexHostOptions):
            raise ValueError("index host options required")
        if any(flag is not True for flag in (self.confirm_read, self.confirm_remote_write, self.confirm_record)):
            raise ValueError("execute requires separate read, remote write and record consent")
        if type(self.confirm_create_journal) is not bool:
            raise ValueError("journal creation switch must be boolean")
        _digest(self.artifact_digest)
        _digest(self.approved_digest)
        if self.artifact_digest != self.approved_digest:
            raise ValueError("exact artifact approval required")
        _label(self.attempt_id)
        object.__setattr__(self, "plan_database", SQLiteKnowledgeIndexPlanStore(self.plan_database).database_path)
        object.__setattr__(self, "journal_database", SQLiteKnowledgeIndexJournal(self.journal_database).database_path)
        if self.plan_database == self.journal_database:
            raise ValueError("plan and journal databases must differ")


async def prepare_local_knowledge_plan(request: KnowledgePlanPrepareRequest) -> dict[str, object]:
    """Load an exact snapshot, prepare one batch and stage it, never execute it."""
    if not isinstance(request, KnowledgePlanPrepareRequest):
        raise ValueError("typed prepare request required")
    snapshot = await SQLiteKnowledgeSnapshotStore(request.source_database).load(request.namespace, request.version)
    # Fail selection mistakes before initializing storage or importing host code.
    selected = request.document_ids
    available = {item.document_id for item in snapshot.documents}
    if (selected is None and not 1 <= len(available) <= 128) or (selected is not None and not set(selected) <= available):
        raise KnowledgePlanActionError("index-prepare-selection-invalid")
    plans = SQLiteKnowledgeIndexPlanStore(request.plan_database)
    if request.confirm_create:
        await plans.initialize(confirm_create=True)
    else:
        await plans.validate_existing()
    checkpoints = SQLiteKnowledgePreparationStore(request.preparation_database) if request.preparation_database is not None else None
    if checkpoints is not None:
        if request.confirm_create:
            await checkpoints.initialize(confirm_create=True)
        else:
            await checkpoints.list_checkpoints()
    async with knowledge_index_host_scope(request.host) as binding:
        if binding.embedder is None:
            raise KnowledgePlanActionError("index-host-has-no-embedder")
        index = KnowledgeVectorIndex(snapshot, binding.embedding_key, binding.dimensions)
        if checkpoints is None:
            artifact = await prepare_knowledge_index_plan(
                index, binding.embedder, binding.writer, document_ids=selected, confirm_embedding=True,
            )
            await plans.save(artifact, confirm_write=True)
        else:
            artifact = await prepare_recoverable_knowledge_plan(
                index, binding.embedder, binding.writer, checkpoints, plans,
                attempt_id=request.preparation_attempt_id, document_ids=selected,
                confirm_embedding=request.confirm_embedding, confirm_write=True,
            )
        result = {"operation": "prepare-save", **artifact.summary(include_target=request.include_target)}
    return result


async def execute_local_knowledge_plan(request: KnowledgePlanExecuteRequest) -> dict[str, object]:
    """Load approved vectors, borrow a writer and persist one attempt; no re-embedding."""
    if not isinstance(request, KnowledgePlanExecuteRequest):
        raise ValueError("typed execute request required")
    artifact = await SQLiteKnowledgeIndexPlanStore(request.plan_database).load(request.artifact_digest)
    async with knowledge_index_host_scope(request.host) as binding:
        # Reject an incompatible target/size before authorized journal creation.
        if binding.writer.plan(artifact.plan.points) != artifact.plan:
            raise KnowledgePlanActionError("index-host-writer-mismatch")
        journal = SQLiteKnowledgeIndexJournal(request.journal_database)
        if request.confirm_create_journal:
            await journal.initialize(confirm_create=True)
        receipt = await execute_prepared_knowledge_plan(
            artifact, binding.writer, journal, attempt_id=request.attempt_id,
            confirm_artifact_digest=request.approved_digest, confirm_record=True,
        )
        result = {
            "operation": "execute", "artifact_digest": artifact.digest,
            "manifest_digest": artifact.manifest.digest, "plan_digest": receipt.plan_digest,
            "attempt_id": request.attempt_id, "receipt_status": receipt.status,
            "point_count": receipt.point_count, "remote_state_verified": False,
        }
    return result
