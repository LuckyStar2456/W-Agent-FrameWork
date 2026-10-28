"""Local build preview/save and journal-derived review; never auto-run batches."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_builds import (
    KnowledgeBuildError, assemble_knowledge_build, execute_knowledge_build_batch,
    inspect_knowledge_build_progress,
    retry_knowledge_build_batch, knowledge_build_retry_id,
)
from w_agent.knowledge_build_sqlite import SQLiteKnowledgeBuildStore
from w_agent.knowledge_index_journal import SQLiteKnowledgeIndexJournal, _digest
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions, knowledge_index_host_scope
from w_agent.knowledge_plan_catalog import KnowledgeIndexPlanInfo
from w_agent.knowledge_plan_sqlite import SQLiteKnowledgeIndexPlanStore


@dataclass(frozen=True, slots=True)
class KnowledgeBuildExecuteRequest:
    """One explicit batch, two reviewed digests, and independent side-effect gates."""

    host: KnowledgeIndexHostOptions = field(repr=False)
    build_database: str | Path = field(repr=False)
    name: str
    version: str
    plan_database: str | Path = field(repr=False)
    journal_database: str | Path = field(repr=False)
    artifact_digest: str
    approved_build_digest: str
    approved_artifact_digest: str
    confirm_read: bool = False
    confirm_remote_write: bool = False
    confirm_record: bool = False
    confirm_create_journal: bool = False
    previous_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.host, KnowledgeIndexHostOptions)
                or self.confirm_read is not True or self.confirm_remote_write is not True
                or self.confirm_record is not True or type(self.confirm_create_journal) is not bool):
            raise ValueError("build execution requires independent confirmations")
        _label(self.name)
        _label(self.version)
        if self.previous_attempt_id is not None:
            _label(self.previous_attempt_id)
        for digest in (self.artifact_digest, self.approved_build_digest, self.approved_artifact_digest):
            _digest(digest)
        if self.artifact_digest != self.approved_artifact_digest:
            raise ValueError("exact artifact approval required")
        for key, store in (("build_database", SQLiteKnowledgeBuildStore),
                           ("plan_database", SQLiteKnowledgeIndexPlanStore),
                           ("journal_database", SQLiteKnowledgeIndexJournal)):
            object.__setattr__(self, key, store(getattr(self, key)).database_path)
        if len({self.build_database, self.plan_database, self.journal_database}) != 3:
            raise ValueError("build, plan and journal databases must differ")


async def execute_local_knowledge_build_batch(request: KnowledgeBuildExecuteRequest) -> dict[str, object]:
    """Read and approve exact persisted inputs before importing trusted host code.

    An explicit predecessor requests a safe retry; omission means first execution.
    Host cleanup can fail after receipt persistence; inspect before further action.
    """
    if not isinstance(request, KnowledgeBuildExecuteRequest):
        raise ValueError("typed build execution request required")
    build = await SQLiteKnowledgeBuildStore(request.build_database).load(request.name, request.version)
    if build.digest != request.approved_build_digest:
        raise KnowledgeBuildError("knowledge-build-approval-mismatch")
    selected = build.select(request.artifact_digest)
    plans = SQLiteKnowledgeIndexPlanStore(request.plan_database)
    artifact = await plans.load(request.artifact_digest)
    if KnowledgeIndexPlanInfo.from_artifact(artifact) != selected:
        raise KnowledgeBuildError("knowledge-build-artifact-mismatch")
    async with knowledge_index_host_scope(request.host) as binding:
        if binding.writer.plan(artifact.plan.points) != artifact.plan:
            raise KnowledgeBuildError("knowledge-build-writer-mismatch")
        del artifact
        journal = SQLiteKnowledgeIndexJournal(request.journal_database)
        if request.confirm_create_journal:
            await journal.initialize(confirm_create=True)
        execute = retry_knowledge_build_batch if request.previous_attempt_id is not None else execute_knowledge_build_batch
        retry_options = {"previous_attempt_id": request.previous_attempt_id} if request.previous_attempt_id is not None else {}
        receipt = await execute(
            build, request.artifact_digest, plans, binding.writer, journal,
            confirm_build_digest=request.approved_build_digest,
            confirm_artifact_digest=request.approved_artifact_digest, confirm_record=True,
            **retry_options,
        )
        result = {
            "operation": "build-retry-batch" if retry_options else "build-execute-batch", "build_digest": build.digest,
            "artifact_digest": request.artifact_digest, "manifest_digest": build.manifest.digest,
            "plan_digest": receipt.plan_digest,
            "attempt_id": knowledge_build_retry_id(build, request.artifact_digest, request.previous_attempt_id)
            if retry_options else build.attempt_id(request.artifact_digest),
            "receipt_status": receipt.status, "point_count": receipt.point_count,
            "remote_state_verified": False,
        }
    return result


async def list_local_knowledge_builds(
    database: str | Path, *, confirm_read: bool = False,
) -> dict[str, object]:
    """Discover immutable builds without reading vector artifacts or remote state."""
    if confirm_read is not True:
        raise KnowledgeBuildError("knowledge-build-read-not-authorized")
    builds = await SQLiteKnowledgeBuildStore(database).list_builds()
    return {"operation": "build-list", "builds": [build.summary() for build in builds],
            "remote_state_verified": False}


async def create_local_knowledge_build(
    plan_database: str | Path, build_database: str | Path, name: str, version: str,
    artifact_digests: tuple[str, ...], *, confirm_read: bool = False,
    confirm_save: bool = False, confirm_create: bool = False,
) -> dict[str, object]:
    """Preview by default; saving/creation are independent confirmations."""
    if (confirm_read is not True or type(confirm_save) is not bool or type(confirm_create) is not bool
            or (confirm_create and not confirm_save)):
        raise KnowledgeBuildError("knowledge-build-management-confirmation-invalid")
    plans = SQLiteKnowledgeIndexPlanStore(plan_database)
    store = SQLiteKnowledgeBuildStore(build_database)
    if plans.database_path == store.database_path:
        raise ValueError("build and plan databases must differ")
    build = await assemble_knowledge_build(name, version, plans, artifact_digests, confirm_read=True)
    if confirm_save:
        if confirm_create:
            await store.initialize(confirm_create=True)
        await store.save(build, confirm_write=True)
    return {"operation": "build-create", "state": "saved" if confirm_save else "preview", **build.summary()}


async def review_local_knowledge_build(
    build_database: str | Path, name: str, version: str, *, confirm_read: bool = False,
    journal_database: str | Path | None = None,
) -> dict[str, object]:
    """Review named build, optionally deriving progress from an existing journal.

    No plan blobs are read here: availability is checked when explicitly executing
    a batch. Missing/unreadable journal DB fails, never invents unstarted state.
    """
    if confirm_read is not True:
        raise KnowledgeBuildError("knowledge-build-read-not-authorized")
    store = SQLiteKnowledgeBuildStore(build_database)
    journal = SQLiteKnowledgeIndexJournal(journal_database) if journal_database is not None else None
    if journal is not None and journal.database_path == store.database_path:
        raise ValueError("build and journal databases must differ")
    build = await store.load(name, version)
    result = {"operation": "build-review", "build": build.summary(), "artifact_availability_checked": False}
    if journal is not None:
        result["progress"] = await inspect_knowledge_build_progress(build, journal)
    return result
