"""Local index observation/reconciliation management, never a remote verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_index_journal import (
    KnowledgeIndexJournalSnapshot,
    KnowledgeIndexReconciliation,
    SQLiteKnowledgeIndexJournal,
    _digest,
)


@dataclass(frozen=True, slots=True)
class KnowledgeIndexReviewRequest:
    """A pinned journal identity and optional independently reviewed decision.

    No filesystem access at construction. Read/display/write/inactivity consent
    are separate. Inactivity is the host's assertion, not a lease or probe.
    """

    database: Path = field(repr=False)
    manifest_digest: str
    decision: KnowledgeIndexReconciliation | None = field(default=None, repr=False)
    confirm_read: bool = False
    include_details: bool = False
    confirm_write: bool = False
    confirm_inactive: bool = False

    def __post_init__(self) -> None:
        _digest(self.manifest_digest)
        for flag in (self.confirm_read, self.include_details, self.confirm_write, self.confirm_inactive):
            if type(flag) is not bool:
                raise ValueError("knowledge index confirmations must be booleans")
        if not self.confirm_read:
            raise ValueError("knowledge index read confirmation is required")
        if self.decision is None:
            if self.confirm_write or self.confirm_inactive:
                raise ValueError("inspection does not accept write confirmations")
        elif (not isinstance(self.decision, KnowledgeIndexReconciliation)
              or self.decision.manifest_digest != self.manifest_digest
              or not self.confirm_write or not self.confirm_inactive):
            raise ValueError("reconciliation requires matching identity, write and inactivity consent")
        journal = SQLiteKnowledgeIndexJournal(self.database)
        object.__setattr__(self, "database", journal.database_path)


def knowledge_index_review_view(
    snapshot: KnowledgeIndexJournalSnapshot, *, include_details: bool = False,
) -> dict[str, object]:
    """Pure bounded summary; sensitive target/evidence fields are opt-in.

    Even the default view includes host labels/digests, not anonymous data.
    Original observations and effective decisions remain distinguishable.
    """
    if not isinstance(snapshot, KnowledgeIndexJournalSnapshot) or type(include_details) is not bool:
        raise ValueError("knowledge index view options are invalid")
    decisions = {item.attempt_id: item for item in snapshot.reconciliations}
    attempts: list[dict[str, object]] = []
    for item in snapshot.attempts:
        decision = decisions.get(item.attempt_id)
        row: dict[str, object] = {
            "attempt_id": item.attempt_id, "plan_digest": item.plan_digest,
            "point_count": len(item.point_ids), "original_outcome": item.outcome,
            "effective_outcome": decision.outcome if decision else item.outcome,
            "reconciliation_id": decision.reconciliation_id if decision else None,
        }
        if include_details:
            row.update(point_ids=list(item.point_ids), operation_id=item.operation_id,
                       reconciliation=decision.to_dict() if decision else None)
        attempts.append(row)
    confirmed_count = len(snapshot.confirmed_point_ids)
    result: dict[str, object] = {
        "manifest_digest": snapshot.manifest.digest,
        "snapshot_digest": snapshot.manifest.snapshot_digest,
        "dimensions": snapshot.manifest.dimensions,
        "expected_point_count": len(snapshot.manifest.point_ids),
        "locally_confirmed_point_count": confirmed_count,
        "all_points_locally_confirmed": confirmed_count == len(snapshot.manifest.point_ids),
        "unresolved_attempt_ids": list(snapshot.unresolved_attempt_ids),
        "remote_state_verified": False,
        "details_included": include_details,
        "attempts": attempts,
    }
    if include_details:
        result["manifest"] = snapshot.manifest.to_dict()
    return result


async def review_local_knowledge_index(request: KnowledgeIndexReviewRequest) -> dict[str, object]:
    """Inspect an existing journal or record a host-reviewed local decision.

    No creation, migration, evidence fetching, credentials, embedding, remote
    operation, retry or deletion. An error/cancel may follow a committed decision;
    inspect before retrying and never infer remote non-application from failure.
    """
    if not isinstance(request, KnowledgeIndexReviewRequest):
        raise TypeError("a KnowledgeIndexReviewRequest is required")
    journal = SQLiteKnowledgeIndexJournal(request.database)
    if request.decision is None:
        snapshot = await journal.inspect(request.manifest_digest)
    else:
        snapshot = await journal.reconcile(request.decision, confirm_inactive=True, confirm_write=True)
    result = knowledge_index_review_view(snapshot, include_details=request.include_details)
    result["operation"] = "reconcile" if request.decision is not None else "inspect"
    return result


async def list_local_knowledge_journals(
    database: str | Path, *, confirm_read: bool = False, include_details: bool = False,
) -> dict[str, object]:
    """Discover receipt manifests and unresolved attempts from an existing DB."""
    if confirm_read is not True or type(include_details) is not bool:
        raise ValueError("knowledge journal catalog requires read confirmation")
    snapshots = await SQLiteKnowledgeIndexJournal(database).list_journals()
    return {"operation": "index-list", "remote_state_verified": False,
            "journals": [knowledge_index_review_view(item, include_details=include_details) for item in snapshots]}
