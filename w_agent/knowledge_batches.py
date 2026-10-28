"""Pure missing-point batch suggestions; no embedding, persistence or execution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_context import _identity
from w_agent.knowledge_index_journal import _digest, _ids
from w_agent.knowledge_index_plans import KnowledgeIndexPlanError
from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_plan_catalog import KnowledgePlanCoverage
from w_agent.knowledge_plan_sqlite import SQLiteKnowledgeIndexPlanStore
from w_agent.knowledge_sqlite import SQLiteKnowledgeSnapshotStore
from w_agent.knowledge_vectors import KnowledgeVectorIndex, knowledge_document_embedding_text
from w_agent.vector_retrieval import _integer


@dataclass(frozen=True, slots=True)
class KnowledgePreparationBatch:
    """Stable advisory identity; IDs are not execution authorization or a lease."""

    manifest_digest: str
    document_ids: tuple[str | int, ...] = field(repr=False)
    point_ids: tuple[str, ...] = field(repr=False)
    input_bytes: int

    def __post_init__(self) -> None:
        _digest(self.manifest_digest)
        _ids(self.point_ids, 128)
        if not isinstance(self.document_ids, tuple) or len(self.document_ids) != len(self.point_ids):
            raise ValueError("batch document and point counts must match")
        for identity in self.document_ids:
            _identity(identity)
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("batch documents must be unique")
        _integer(self.input_bytes, 32 * 1024 * 1024)

    @property
    def digest(self) -> str:
        return hashlib.sha256(_json({
            "format": "wagent-knowledge-preparation-batch-v1", "manifest_digest": self.manifest_digest,
            "document_ids": list(self.document_ids), "point_ids": list(self.point_ids),
            "input_bytes": self.input_bytes,
        }).encode("utf-8")).hexdigest()

    def summary(self, *, include_ids: bool = False) -> dict[str, object]:
        if type(include_ids) is not bool:
            raise ValueError("batch ID display switch must be boolean")
        result: dict[str, object] = {
            "batch_digest": self.digest, "manifest_digest": self.manifest_digest,
            "document_count": len(self.document_ids), "input_bytes": self.input_bytes,
        }
        if include_ids:
            result.update(document_ids=list(self.document_ids), point_ids=list(self.point_ids))
        return result


def plan_missing_knowledge_batches(
    index: KnowledgeVectorIndex, coverage: KnowledgePlanCoverage, *, max_documents: int = 128,
    max_input_bytes: int = 1024 * 1024, max_vector_values: int = 1024 * 1024,
) -> tuple[KnowledgePreparationBatch, ...]:
    """Greedy stable snapshot-order partition; all limits checked before returning.

    Already staged points are omitted, not certified correct. Overlapping saved
    plans remain visible in coverage; no plan wins automatically. Writer request
    byte limits depend on generated floats and cannot be proved before embedding.
    """
    if not isinstance(index, KnowledgeVectorIndex) or not isinstance(coverage, KnowledgePlanCoverage):
        raise ValueError("typed index and coverage required")
    _integer(max_documents, 128)
    _integer(max_input_bytes, 32 * 1024 * 1024)
    _integer(max_vector_values, 1024 * 1024)
    manifest = coverage.manifest
    if (index.snapshot_digest != manifest.snapshot_digest or index.embedding_key != manifest.embedding_key
            or index.dimensions != manifest.dimensions or index.point_ids != manifest.point_ids):
        raise ValueError("batch planning requires the exact manifest snapshot and embedding identity")
    missing = set(coverage.missing_point_ids)
    batches = []
    documents: list[str | int] = []
    points: list[str] = []
    size = 0
    for document, point in zip(index.snapshot.documents, index.point_ids, strict=True):
        if point not in missing:
            continue
        width = len(knowledge_document_embedding_text(document).encode("utf-8"))
        if width > max_input_bytes or index.dimensions > max_vector_values:
            raise ValueError("one knowledge document exceeds preparation bounds")
        if documents and (len(documents) >= max_documents or size + width > max_input_bytes
                          or (len(documents) + 1) * index.dimensions > max_vector_values):
            batches.append(KnowledgePreparationBatch(manifest.digest, tuple(documents), tuple(points), size))
            documents, points, size = [], [], 0
        documents.append(document.document_id)
        points.append(point)
        size += width
    if documents:
        batches.append(KnowledgePreparationBatch(manifest.digest, tuple(documents), tuple(points), size))
    return tuple(batches)


async def review_missing_knowledge_batches(
    plan_database: str | Path, source_database: str | Path, namespace: str, version: str,
    manifest_digest: str, *, confirm_read: bool = False, include_ids: bool = False,
    max_documents: int = 128, max_input_bytes: int = 1024 * 1024,
    max_vector_values: int = 1024 * 1024,
) -> dict[str, object]:
    """Read-only local advice for a manifest already represented in the plan store.

    Reads source bodies to count the exact embedding-input bytes; never discloses
    them to services. Two databases are not an atomic snapshot or a reservation.
    """
    if confirm_read is not True or type(include_ids) is not bool:
        raise KnowledgeIndexPlanError("knowledge-batch-review-not-authorized")
    _label(namespace)
    _label(version)
    _digest(manifest_digest)
    _integer(max_documents, 128)
    _integer(max_input_bytes, 32 * 1024 * 1024)
    _integer(max_vector_values, 1024 * 1024)
    plans = SQLiteKnowledgeIndexPlanStore(plan_database)
    source = SQLiteKnowledgeSnapshotStore(source_database)
    if plans.database_path == source.database_path:
        raise ValueError("plan and source databases must differ")
    entries = tuple(item for item in await plans.list_plans() if item.manifest.digest == manifest_digest)
    if not entries:
        raise KnowledgeIndexPlanError("knowledge-plan-catalog-manifest-not-found")
    snapshot = await source.load(namespace, version)
    coverage = KnowledgePlanCoverage(entries[0].manifest, entries)
    index = KnowledgeVectorIndex(snapshot, coverage.manifest.embedding_key, coverage.manifest.dimensions)
    batches = plan_missing_knowledge_batches(
        index, coverage, max_documents=max_documents, max_input_bytes=max_input_bytes,
        max_vector_values=max_vector_values,
    )
    return {
        "operation": "missing-batches", "manifest_digest": manifest_digest,
        "advisory_only": True, "remote_state_verified": False,
        "source_bodies_included": False, "ids_included": include_ids,
        "limits": {"max_documents": max_documents, "max_input_bytes": max_input_bytes,
                   "max_vector_values": max_vector_values},
        "coverage": coverage.summary(), "batches": [item.summary(include_ids=include_ids) for item in batches],
    }
