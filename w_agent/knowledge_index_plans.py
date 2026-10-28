"""Portable exact knowledge-vector plans, separated from approval and execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from w_agent.knowledge_index_journal import (
    KnowledgeIndexJournal, KnowledgeIndexManifest, _digest,
    journaled_knowledge_upsert, knowledge_index_manifest,
)
from w_agent.knowledge_ingestion import _json
from w_agent.knowledge_vectors import KnowledgeVectorIndex, prepare_knowledge_vectors
from w_agent.vector_indexing import DenseVectorPoint, QdrantUpsertPlan, QdrantVectorWriter, QdrantWriteResult
from w_agent.vector_retrieval import AsyncTextEmbedder, _reject_constant, _unique_object

MAX_KNOWLEDGE_PLAN_BYTES = 32 * 1024 * 1024
MAX_KNOWLEDGE_PLAN_VALUES = 1024 * 1024


class KnowledgeIndexPlanError(RuntimeError):
    """Fixed errors without vector values or target details; not proof of rollback."""


@dataclass(frozen=True, slots=True)
class PreparedKnowledgeIndexPlan:
    """One exact nonempty batch, retaining floats for execution without re-embedding.

    The full manifest may cover other batches. Neither digest nor construction
    grants permission, authenticates provenance or proves embedding correctness.
    Values and endpoint are sensitive even though no source bodies are retained.
    """

    manifest: KnowledgeIndexManifest = field(repr=False)
    plan: QdrantUpsertPlan = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, KnowledgeIndexManifest) or not isinstance(self.plan, QdrantUpsertPlan):
            raise KnowledgeIndexPlanError("knowledge-prepared-plan-invalid")
        self.manifest.validate_plan(self.plan)
        if sum(len(point.vector) for point in self.plan.points) > MAX_KNOWLEDGE_PLAN_VALUES:
            raise KnowledgeIndexPlanError("knowledge-prepared-plan-too-large")
        if len(self.to_json().encode("utf-8")) > MAX_KNOWLEDGE_PLAN_BYTES:
            raise KnowledgeIndexPlanError("knowledge-prepared-plan-too-large")

    def to_json(self) -> str:
        """Explicit sensitive serialization, not an ordinary log/preview view."""
        return _json({
            "format": "wagent-prepared-knowledge-plan-v1",
            "manifest": self.manifest.to_dict(), "manifest_digest": self.manifest.digest,
            "plan_digest": self.plan.digest,
            "points": [{"id": point.point_id, "vector": list(point.vector)} for point in self.plan.points],
        })

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def summary(self, *, include_target: bool = False) -> dict[str, object]:
        """No vector values; target/embedding label/point IDs require explicit opt-in."""
        if type(include_target) is not bool:
            raise ValueError("plan display option must be boolean")
        result: dict[str, object] = {
            "artifact_digest": self.digest, "manifest_digest": self.manifest.digest,
            "plan_digest": self.plan.digest, "snapshot_digest": self.manifest.snapshot_digest,
            "dimensions": self.manifest.dimensions, "batch_point_count": len(self.plan.points),
            "expected_point_count": len(self.manifest.point_ids), "remote_state_verified": False,
            "authorized": False,
        }
        if include_target:
            result.update(endpoint=self.manifest.endpoint, vector_name=self.manifest.vector_name,
                          embedding_key=self.manifest.embedding_key,
                          batch_point_ids=[point.point_id for point in self.plan.points])
        return result


def prepared_knowledge_plan_from_json(payload: str, *, expected_digest: str) -> PreparedKnowledgeIndexPlan:
    """Strict canonical decoding with externally selected artifact identity."""
    try:
        _digest(expected_digest)
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_KNOWLEDGE_PLAN_BYTES:
            raise ValueError
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected_digest:
            raise ValueError
        value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if (not isinstance(value, dict)
                or set(value) != {"format", "manifest", "manifest_digest", "plan_digest", "points"}
                or value["format"] != "wagent-prepared-knowledge-plan-v1"):
            raise ValueError
        raw = value["manifest"]
        if (not isinstance(raw, dict)
                or set(raw) != {"snapshot_digest", "embedding_key", "dimensions", "endpoint", "vector_name", "point_ids"}
                or not isinstance(raw["point_ids"], list) or not 1 <= len(raw["point_ids"]) <= 1024):
            raise ValueError
        manifest = KnowledgeIndexManifest(**{**raw, "point_ids": tuple(raw["point_ids"])})
        rows = value["points"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
            raise ValueError
        if len(rows) * manifest.dimensions > MAX_KNOWLEDGE_PLAN_VALUES:
            raise ValueError
        points = []
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"id", "vector"}
                    or not isinstance(row["vector"], list) or len(row["vector"]) != manifest.dimensions):
                raise ValueError
            points.append(DenseVectorPoint(row["id"], tuple(row["vector"])))
        artifact = PreparedKnowledgeIndexPlan(
            manifest, QdrantUpsertPlan(manifest.endpoint, manifest.vector_name, tuple(points)),
        )
        if (value["manifest_digest"] != manifest.digest or value["plan_digest"] != artifact.plan.digest
                or artifact.to_json() != payload):
            raise ValueError
        return artifact
    except Exception:
        raise KnowledgeIndexPlanError("knowledge-prepared-plan-decode-failed") from None


class KnowledgeIndexPlanStore(Protocol):
    """Replaceable content-addressed staging, independent of write-attempt journals."""

    async def save(self, artifact: PreparedKnowledgeIndexPlan, *, confirm_write: bool = False) -> str: ...

    async def load(self, artifact_digest: str) -> PreparedKnowledgeIndexPlan: ...


async def prepare_knowledge_index_plan(
    index: KnowledgeVectorIndex, embedder: AsyncTextEmbedder, writer: QdrantVectorWriter, *,
    document_ids: tuple[str | int, ...] | None = None, confirm_embedding: bool = False,
    max_input_bytes: int = 1024 * 1024, timeout: float = 30.0,
) -> PreparedKnowledgeIndexPlan:
    """Embed one bounded batch explicitly; never save or send the resulting plan.

    Hosts own the borrowed embedder/writer and budget wrappers. A late preparation
    or writer-size failure may follow billed calls; partial vectors are not saved.
    """
    if not isinstance(index, KnowledgeVectorIndex) or not isinstance(writer, QdrantVectorWriter):
        raise KnowledgeIndexPlanError("knowledge-plan-preparation-invalid")
    manifest = knowledge_index_manifest(index, writer)
    if document_ids == ():
        raise KnowledgeIndexPlanError("knowledge-plan-empty-batch")
    points = await prepare_knowledge_vectors(
        index, embedder, document_ids=document_ids, confirm_embedding=confirm_embedding,
        max_input_bytes=max_input_bytes, max_vector_values=MAX_KNOWLEDGE_PLAN_VALUES, timeout=timeout,
    )
    return PreparedKnowledgeIndexPlan(manifest, writer.plan(points))


async def execute_prepared_knowledge_plan(
    artifact: PreparedKnowledgeIndexPlan, writer: QdrantVectorWriter, journal: KnowledgeIndexJournal, *,
    attempt_id: str, confirm_artifact_digest: str, confirm_record: bool = False,
) -> QdrantWriteResult:
    """Execute exactly the separately reviewed artifact; no embedding or retry.

    Approval must come from the host, not be copied blindly from untrusted input.
    Journal attempt IDs prevent same-ID replay, not global duplicate writes.
    """
    if (not isinstance(artifact, PreparedKnowledgeIndexPlan) or not isinstance(writer, QdrantVectorWriter)
            or confirm_record is not True or not isinstance(confirm_artifact_digest, str)
            or confirm_artifact_digest != artifact.digest):
        raise KnowledgeIndexPlanError("knowledge-prepared-plan-confirmation-invalid")
    # Revalidate current writer target/limits before creating a pending record.
    if writer.plan(artifact.plan.points) != artifact.plan:
        raise KnowledgeIndexPlanError("knowledge-prepared-plan-writer-mismatch")
    return await journaled_knowledge_upsert(
        writer, artifact.plan, artifact.manifest, journal, attempt_id=attempt_id,
        confirm_digest=artifact.plan.digest, confirm_record=True,
    )
