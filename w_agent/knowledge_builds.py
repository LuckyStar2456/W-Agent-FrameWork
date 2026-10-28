"""Immutable full-build selection and explicitly approved per-batch continuation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from w_agent.knowledge_index_journal import (
    KnowledgeIndexJournal, KnowledgeIndexJournalError, KnowledgeIndexJournalSnapshot,
    KnowledgeIndexManifest, _digest,
)
from w_agent.knowledge_index_plans import (
    KnowledgeIndexPlanStore, PreparedKnowledgeIndexPlan, execute_prepared_knowledge_plan,
)
from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_plan_catalog import KnowledgeIndexPlanInfo, KnowledgePlanCoverage
from w_agent.vector_indexing import QdrantVectorWriter, QdrantWriteResult
from w_agent.vector_retrieval import _reject_constant, _unique_object

MAX_KNOWLEDGE_BUILD_BYTES = 1024 * 1024


class KnowledgeBuildError(RuntimeError):
    """Fixed build errors; failures do not imply remote rollback or safe replay."""


@dataclass(frozen=True, slots=True)
class KnowledgeIndexBuild:
    """User-named immutable ordered selection with disjoint full point coverage.

    References existing artifacts, not their vectors. Name/version/order affect
    identity. A saved build grants no authority, resource lease or remote proof.
    """

    name: str
    version: str
    manifest: KnowledgeIndexManifest = field(repr=False)
    plans: tuple[KnowledgeIndexPlanInfo, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _label(self.name)
        _label(self.version)
        coverage = KnowledgePlanCoverage(self.manifest, self.plans)
        if not self.plans or coverage.missing_point_ids or coverage.overlapping_point_ids:
            raise KnowledgeBuildError("knowledge-build-requires-disjoint-full-coverage")
        if len(self.to_json().encode("utf-8")) > MAX_KNOWLEDGE_BUILD_BYTES:
            raise KnowledgeBuildError("knowledge-build-too-large")

    def to_json(self) -> str:
        return _json({
            "format": "wagent-knowledge-build-v1", "name": self.name, "version": self.version,
            "manifest": self.manifest.to_dict(),
            "plans": [{"artifact_digest": item.artifact_digest, "plan_digest": item.plan_digest,
                       "point_ids": list(item.point_ids)} for item in self.plans],
        })

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def select(self, artifact_digest: str) -> KnowledgeIndexPlanInfo:
        _digest(artifact_digest)
        for item in self.plans:
            if item.artifact_digest == artifact_digest:
                return item
        raise KnowledgeBuildError("knowledge-build-artifact-not-selected")

    def attempt_id(self, artifact_digest: str) -> str:
        self.select(artifact_digest)
        digest = hashlib.sha256(_json([
            "wagent-knowledge-build-attempt-v1", self.digest, artifact_digest,
        ]).encode("utf-8")).hexdigest()
        return "build-" + digest

    def summary(self) -> dict[str, object]:
        return {
            "name": self.name, "version": self.version, "build_digest": self.digest,
            "manifest_digest": self.manifest.digest, "batch_count": len(self.plans),
            "expected_point_count": len(self.manifest.point_ids), "authorized": False,
            "remote_state_verified": False,
            "batches": [{"artifact_digest": item.artifact_digest, "plan_digest": item.plan_digest,
                         "point_count": len(item.point_ids), "attempt_id": self.attempt_id(item.artifact_digest)}
                        for item in self.plans],
        }


def knowledge_build_from_json(payload: str, *, expected_digest: str) -> KnowledgeIndexBuild:
    try:
        _digest(expected_digest)
        if (not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_KNOWLEDGE_BUILD_BYTES
                or hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected_digest):
            raise ValueError
        value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (not isinstance(value, dict) or set(value) != {"format", "name", "version", "manifest", "plans"}
                or value["format"] != "wagent-knowledge-build-v1"):
            raise ValueError
        raw = value["manifest"]
        if (not isinstance(raw, dict) or set(raw) != {"snapshot_digest", "embedding_key", "dimensions", "endpoint", "vector_name", "point_ids"}
                or not isinstance(raw["point_ids"], list)):
            raise ValueError
        manifest = KnowledgeIndexManifest(**{**raw, "point_ids": tuple(raw["point_ids"])})
        if not isinstance(value["plans"], list) or not 1 <= len(value["plans"]) <= 128:
            raise ValueError
        plans = []
        for item in value["plans"]:
            if not isinstance(item, dict) or set(item) != {"artifact_digest", "plan_digest", "point_ids"} or not isinstance(item["point_ids"], list):
                raise ValueError
            plans.append(KnowledgeIndexPlanInfo(item["artifact_digest"], item["plan_digest"], manifest, tuple(item["point_ids"])))
        build = KnowledgeIndexBuild(value["name"], value["version"], manifest, tuple(plans))
        if build.to_json() != payload:
            raise ValueError
        return build
    except Exception:
        raise KnowledgeBuildError("knowledge-build-decode-failed") from None


class KnowledgeBuildStore(Protocol):
    """Optional build persistence, separate from vector staging and observations."""

    async def save(self, build: KnowledgeIndexBuild, *, confirm_write: bool = False) -> str: ...

    async def load(self, name: str, version: str) -> KnowledgeIndexBuild: ...


class KnowledgeBuildCatalog(KnowledgeBuildStore, Protocol):
    async def list_builds(self) -> tuple[KnowledgeIndexBuild, ...]: ...


def knowledge_build_retry_id(build: KnowledgeIndexBuild, artifact_digest: str, previous_attempt_id: str) -> str:
    """Stable successor identity; approval remains separate from this pure hash."""
    build.select(artifact_digest)
    _label(previous_attempt_id)
    return "retry-" + hashlib.sha256(_json([
        "wagent-knowledge-build-retry-v1", build.digest, artifact_digest, previous_attempt_id,
    ]).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _CoordinatedJournal:
    journal: KnowledgeIndexJournal

    async def begin(self, manifest, attempt_id, plan, *, confirm_write=False):
        begin = getattr(self.journal, "begin_exclusive", None)
        if not callable(begin):
            raise KnowledgeBuildError("knowledge-build-coordinated-journal-required")
        return await begin(manifest, attempt_id, plan, confirm_write=confirm_write)

    async def record(self, *args, **kwargs):
        return await self.journal.record(*args, **kwargs)


async def assemble_knowledge_build(
    name: str, version: str, plans: KnowledgeIndexPlanStore, artifact_digests: tuple[str, ...], *,
    confirm_read: bool = False,
) -> KnowledgeIndexBuild:
    """Read exact selections in caller order; never auto-select overlaps or persist."""
    if confirm_read is not True:
        raise KnowledgeBuildError("knowledge-build-read-not-authorized")
    _label(name)
    _label(version)
    if not isinstance(artifact_digests, tuple) or not 1 <= len(artifact_digests) <= 128:
        raise ValueError("build requires bounded explicit artifact selection")
    for digest in artifact_digests:
        _digest(digest)
    if len(set(artifact_digests)) != len(artifact_digests) or not callable(getattr(plans, "load", None)):
        raise ValueError("invalid build selection/store")
    selected = []
    for digest in artifact_digests:
        artifact = await plans.load(digest)
        if not isinstance(artifact, PreparedKnowledgeIndexPlan) or artifact.digest != digest:
            raise KnowledgeBuildError("knowledge-build-artifact-mismatch")
        selected.append(KnowledgeIndexPlanInfo.from_artifact(artifact))
        del artifact
    return KnowledgeIndexBuild(name, version, selected[0].manifest, tuple(selected))


def knowledge_build_progress(build: KnowledgeIndexBuild, snapshot: KnowledgeIndexJournalSnapshot) -> dict[str, object]:
    """Derive batch observations, never infer an empty journal from a read error.

    Foreign unresolved attempts that overlap a batch block continuation/complete
    claims. Completed observations do not establish the current remote vectors.
    """
    if (not isinstance(build, KnowledgeIndexBuild) or not isinstance(snapshot, KnowledgeIndexJournalSnapshot)
            or snapshot.manifest != build.manifest):
        raise KnowledgeBuildError("knowledge-build-journal-mismatch")
    attempts = {item.attempt_id: item for item in snapshot.attempts}
    unresolved = set(snapshot.unresolved_attempt_ids)
    batches = []
    for item in build.plans:
        identity = build.attempt_id(item.artifact_digest)
        attempt = attempts.get(identity)
        history = []
        while attempt is not None:
            if attempt.plan_digest != item.plan_digest or attempt.point_ids != item.point_ids:
                raise KnowledgeBuildError("knowledge-build-attempt-mismatch")
            history.append(identity)
            successor = knowledge_build_retry_id(build, item.artifact_digest, identity)
            if successor not in attempts:
                break
            if snapshot.effective_outcome(identity) not in {"not-sent", "not-applied"}:
                raise KnowledgeBuildError("knowledge-build-invalid-retry-chain")
            identity, attempt = successor, attempts[successor]
        blockers = [other.attempt_id for other in snapshot.attempts
                    if other.attempt_id != identity and other.attempt_id in unresolved
                    and set(other.point_ids).intersection(item.point_ids)]
        status = snapshot.effective_outcome(identity) if attempt is not None else "not-started"
        batches.append({
            "artifact_digest": item.artifact_digest, "attempt_id": identity,
            "original_outcome": attempt.outcome if attempt is not None else None,
            "effective_outcome": status, "blocked_by_attempt_ids": blockers,
            "can_request_first_execution": attempt is None and not blockers,
            "attempt_history": history,
            "can_request_retry": status in {"not-sent", "not-applied"} and not blockers,
            "next_retry_attempt_id": knowledge_build_retry_id(build, item.artifact_digest, identity)
            if status in {"not-sent", "not-applied"} and not blockers else None,
        })
    return {
        "build_digest": build.digest, "manifest_digest": build.manifest.digest,
        "batches": batches,
        "all_batches_locally_completed": all(item["effective_outcome"] == "completed" and not item["blocked_by_attempt_ids"] for item in batches),
        "remote_state_verified": False, "advisory_only": True,
    }


async def inspect_knowledge_build_progress(build: KnowledgeIndexBuild, journal: KnowledgeIndexJournal) -> dict[str, object]:
    """Only explicit manifest-not-found denotes a fresh, existing journal DB."""
    if not isinstance(build, KnowledgeIndexBuild):
        raise ValueError("typed build required")
    try:
        snapshot = await journal.inspect(build.manifest.digest)
    except KnowledgeIndexJournalError as error:
        if str(error) != "knowledge-index-manifest-not-found":
            raise
        snapshot = KnowledgeIndexJournalSnapshot(build.manifest)
    return knowledge_build_progress(build, snapshot)


async def execute_knowledge_build_batch(
    build: KnowledgeIndexBuild, artifact_digest: str, plans: KnowledgeIndexPlanStore,
    writer: QdrantVectorWriter, journal: KnowledgeIndexJournal, *, confirm_build_digest: str,
    confirm_artifact_digest: str, confirm_record: bool = False,
) -> QdrantWriteResult:
    """Explicit first execution of one selected batch; never restart old attempts.

    Coordinated journal begin atomically refuses unresolved overlapping points.
    Hosts still coordinate other databases and external writers.
    """
    if (not isinstance(build, KnowledgeIndexBuild) or not isinstance(writer, QdrantVectorWriter)
            or not isinstance(confirm_build_digest, str) or confirm_build_digest != build.digest
            or not isinstance(confirm_artifact_digest, str) or confirm_artifact_digest != artifact_digest
            or confirm_record is not True):
        raise KnowledgeBuildError("knowledge-build-confirmation-invalid")
    selected = build.select(artifact_digest)
    artifact = await plans.load(artifact_digest)
    if not isinstance(artifact, PreparedKnowledgeIndexPlan) or KnowledgeIndexPlanInfo.from_artifact(artifact) != selected:
        raise KnowledgeBuildError("knowledge-build-artifact-mismatch")
    progress = await inspect_knowledge_build_progress(build, journal)
    batch = next(item for item in progress["batches"] if item["artifact_digest"] == artifact_digest)
    if not batch["can_request_first_execution"]:
        raise KnowledgeBuildError("knowledge-build-batch-already-attempted-or-blocked")
    return await execute_prepared_knowledge_plan(
        artifact, writer, _CoordinatedJournal(journal), attempt_id=build.attempt_id(artifact_digest),
        confirm_artifact_digest=confirm_artifact_digest, confirm_record=True,
    )


async def retry_knowledge_build_batch(
    build: KnowledgeIndexBuild, artifact_digest: str, plans: KnowledgeIndexPlanStore,
    writer: QdrantVectorWriter, journal: KnowledgeIndexJournal, *, previous_attempt_id: str,
    confirm_build_digest: str, confirm_artifact_digest: str, confirm_record: bool = False,
) -> QdrantWriteResult:
    """Explicit next attempt only after not-sent or reviewed not-applied evidence.

    Exact predecessor binding and stable successor IDs prevent simultaneous retry
    requests from sending twice. Unknown outcomes never authorize an automatic send.
    """
    if (not isinstance(build, KnowledgeIndexBuild) or confirm_build_digest != build.digest
            or confirm_artifact_digest != artifact_digest or confirm_record is not True):
        raise KnowledgeBuildError("knowledge-build-confirmation-invalid")
    selected = build.select(artifact_digest)
    artifact = await plans.load(artifact_digest)
    if not isinstance(artifact, PreparedKnowledgeIndexPlan) or KnowledgeIndexPlanInfo.from_artifact(artifact) != selected:
        raise KnowledgeBuildError("knowledge-build-artifact-mismatch")
    progress = await inspect_knowledge_build_progress(build, journal)
    batch = next(item for item in progress["batches"] if item["artifact_digest"] == artifact_digest)
    if not batch["can_request_retry"] or batch["attempt_id"] != previous_attempt_id:
        raise KnowledgeBuildError("knowledge-build-retry-not-safe-or-stale")
    return await execute_prepared_knowledge_plan(
        artifact, writer, _CoordinatedJournal(journal), attempt_id=batch["next_retry_attempt_id"],
        confirm_artifact_digest=confirm_artifact_digest, confirm_record=True,
    )
