"""Vector-free plan discovery and local preparation coverage, not execution state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from w_agent.knowledge_index_journal import KnowledgeIndexManifest, _digest, _ids
from w_agent.knowledge_index_plans import KnowledgeIndexPlanError, PreparedKnowledgeIndexPlan


@dataclass(frozen=True, slots=True)
class KnowledgeIndexPlanInfo:
    """Manifest and batch identities without floats; integrity depends on the reader.

    SQLite's catalog builds these only after decoding the full artifact. Custom
    hosts constructing metadata themselves remain responsible for its accuracy.
    """

    artifact_digest: str
    plan_digest: str
    manifest: KnowledgeIndexManifest = field(repr=False)
    point_ids: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _digest(self.artifact_digest)
        _digest(self.plan_digest)
        if not isinstance(self.manifest, KnowledgeIndexManifest):
            raise ValueError("plan info requires a manifest")
        _ids(self.point_ids, 128)
        if not set(self.point_ids) <= set(self.manifest.point_ids):
            raise ValueError("plan info points must belong to manifest")

    @classmethod
    def from_artifact(cls, artifact: PreparedKnowledgeIndexPlan) -> KnowledgeIndexPlanInfo:
        if not isinstance(artifact, PreparedKnowledgeIndexPlan):
            raise ValueError("typed prepared plan required")
        return cls(artifact.digest, artifact.plan.digest, artifact.manifest,
                   tuple(point.point_id for point in artifact.plan.points))

    def summary(self, *, include_target: bool = False) -> dict[str, object]:
        if type(include_target) is not bool:
            raise ValueError("target display switch must be boolean")
        result: dict[str, object] = {
            "artifact_digest": self.artifact_digest, "plan_digest": self.plan_digest,
            "manifest_digest": self.manifest.digest, "snapshot_digest": self.manifest.snapshot_digest,
            "dimensions": self.manifest.dimensions, "batch_point_count": len(self.point_ids),
            "expected_point_count": len(self.manifest.point_ids),
        }
        if include_target:
            result.update(endpoint=self.manifest.endpoint, vector_name=self.manifest.vector_name,
                          embedding_key=self.manifest.embedding_key, batch_point_ids=list(self.point_ids))
        return result


class KnowledgeIndexPlanCatalog(Protocol):
    """Optional discovery capability; existing save/load plugins need not change."""

    async def list_plans(self) -> tuple[KnowledgeIndexPlanInfo, ...]: ...


@dataclass(frozen=True, slots=True)
class KnowledgePlanCoverage:
    """Exact-manifest preparation coverage only; never select/replay batches.

    Overlap is not proof of different vectors, and full union coverage is not a
    disjoint execution plan, approval, remote-write receipt or retrieval proof.
    """

    manifest: KnowledgeIndexManifest = field(repr=False)
    plans: tuple[KnowledgeIndexPlanInfo, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.manifest, KnowledgeIndexManifest) or not isinstance(self.plans, tuple)
                or len(self.plans) > 128):
            raise ValueError("invalid preparation coverage input")
        seen = set()
        for item in self.plans:
            if (not isinstance(item, KnowledgeIndexPlanInfo) or item.manifest != self.manifest
                    or item.artifact_digest in seen):
                raise ValueError("coverage requires unique plans for one exact manifest")
            seen.add(item.artifact_digest)

    @property
    def prepared_point_ids(self) -> tuple[str, ...]:
        selected = {point for item in self.plans for point in item.point_ids}
        return tuple(point for point in self.manifest.point_ids if point in selected)

    @property
    def missing_point_ids(self) -> tuple[str, ...]:
        selected = set(self.prepared_point_ids)
        return tuple(point for point in self.manifest.point_ids if point not in selected)

    @property
    def overlapping_point_ids(self) -> tuple[str, ...]:
        counts: dict[str, int] = {}
        for item in self.plans:
            for point in item.point_ids:
                counts[point] = counts.get(point, 0) + 1
        return tuple(point for point in self.manifest.point_ids if counts.get(point, 0) > 1)

    def summary(self, *, include_target: bool = False) -> dict[str, object]:
        if type(include_target) is not bool:
            raise ValueError("target display switch must be boolean")
        prepared, missing, overlaps = self.prepared_point_ids, self.missing_point_ids, self.overlapping_point_ids
        result: dict[str, object] = {
            "manifest_digest": self.manifest.digest, "plan_count": len(self.plans),
            "expected_point_count": len(self.manifest.point_ids), "prepared_point_count": len(prepared),
            "missing_point_count": len(missing), "overlapping_point_count": len(overlaps),
            "all_points_prepared": not missing, "batches_disjoint": not overlaps,
            "remote_state_verified": False, "execution_selected": False,
        }
        if include_target:
            result.update(missing_point_ids=list(missing), overlapping_point_ids=list(overlaps),
                          endpoint=self.manifest.endpoint, embedding_key=self.manifest.embedding_key,
                          vector_name=self.manifest.vector_name)
        return result


async def review_knowledge_plan_catalog(
    database: str | Path, *, manifest_digest: str | None = None,
    confirm_read: bool = False, include_target: bool = False,
) -> dict[str, object]:
    """Scan a bounded existing SQLite catalog; filtering never hides corrupt rows.

    No factories, embedding, mutation, journal inference or remote access. The
    single read transaction supplies a catalog snapshot, not an execution lease.
    """
    if confirm_read is not True or type(include_target) is not bool:
        raise KnowledgeIndexPlanError("knowledge-plan-catalog-read-not-authorized")
    if manifest_digest is not None:
        _digest(manifest_digest)
    from w_agent.knowledge_plan_sqlite import SQLiteKnowledgeIndexPlanStore

    entries = await SQLiteKnowledgeIndexPlanStore(database).list_plans()
    selected = tuple(item for item in entries if manifest_digest is None or item.manifest.digest == manifest_digest)
    if manifest_digest is not None and not selected:
        raise KnowledgeIndexPlanError("knowledge-plan-catalog-manifest-not-found")
    grouped: dict[str, list[KnowledgeIndexPlanInfo]] = {}
    for item in selected:
        grouped.setdefault(item.manifest.digest, []).append(item)
    return {
        "operation": "plan-catalog", "artifacts_integrity_verified": True,
        "remote_state_verified": False, "target_included": include_target,
        "scanned_plan_count": len(entries),
        "plans": [item.summary(include_target=include_target) for item in selected],
        "coverage": [KnowledgePlanCoverage(grouped[key][0].manifest, tuple(grouped[key])).summary(
            include_target=include_target) for key in sorted(grouped)],
    }
