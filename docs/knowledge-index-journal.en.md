# Knowledge-index manifests and durable write receipts

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-index-journal.md)

Full vectors can separately use [exact-plan staging](./knowledge-index-plans.en.md), then execute the same approved plan without re-embedding. Staging is distinct from this receipt journal, not completion or authority.

Related entries include [index journal management API/CLI/TUI](./knowledge-index-management.en.md) for review/explicit reconciliation and [plan prepare-save/approved-execute actions](./knowledge-plan-actions.en.md). Remote verification remains planned.

Status: 2.0.0 `Experimental`, included in 2.0.0 and outside `2.0.0a9`. Local SQLite/fake-transport and headless UI regressions pass. No live remote calls, dependency installation or publication ran.

## What is recorded, not proven

`knowledge_index_manifest(index, writer)` purely builds `KnowledgeIndexManifest` from [snapshot-vector identity](./knowledge-vectors.en.md) and an existing Writer. It contains snapshot digest, host embedding label/dimension, exact endpoint/vector_name and every expected point ID. Its digest binds these fields and format version, excluding document bodies, vector values and API keys.

A manifest is not write permission, a signature, an execution lease or a quality guarantee. Endpoints/labels/IDs may still be sensitive: protect storage and do not put secrets in these fields. Credentials are not bound by the digest; account/key changes require renewed host review. Direct manifest construction leaves expected-set completeness to the host; the factory uses the entire nonempty `KnowledgeVectorIndex`.

`KnowledgeIndexAttempt` records an attempt ID, exact plan digest, point subset, outcome and optional remote operation ID. It stores no vector values, cannot reconstruct a write plan and never executes one automatically.

## Separate commit boundaries

```python
from w_agent import (
    SQLiteKnowledgeIndexJournal, knowledge_index_manifest, journaled_knowledge_upsert,
)
from my_application import review_exact_upsert

# Host prepares index/writer/points using the snapshot-vector guide.
manifest = knowledge_index_manifest(index, writer)
journal = SQLiteKnowledgeIndexJournal("knowledge-index-journal.sqlite")
await journal.initialize(confirm_create=True)  # Existing parent; dedicated database.
plan = writer.plan(points)
reviewed_digest = await review_exact_upsert(plan)
receipt = await journaled_knowledge_upsert(
    writer, plan, manifest, journal,
    attempt_id="build-v1-batch-001", confirm_digest=reviewed_digest, confirm_record=True,
)
state = await journal.inspect(manifest.digest)
print(state.all_points_confirmed, state.unresolved_attempt_ids)
```

This example was not executed. Hosts separately authorize body embedding, remote overwrites and local journal creation/writes. `journaled_knowledge_upsert()` validates target, point subset, dimension and exact-plan confirmation, persists pending, sends at most once, then persists the receipt. It does not send without a confirmed pending record. Reusing an attempt ID within a manifest is rejected even for the identical plan, never triggering automatic replay.

Pending commit, remote upsert and final local receipt commit are three independent actions, not a cross-store transaction. A crash between any two can leave pending for an unsent request or a successful unrecorded write. This is not an automatically executable recovery queue.

## Outcomes and coverage

- `pending`: registered locally without a final observation. Unresolved, never proof that nothing was sent.
- `completed`: a typed `QdrantWriteResult(status="completed")` matching plan digest/point count was recorded. This is receipt evidence, not proof of present remote existence.
- `acknowledged`: received but unconfirmed; unresolved and excluded from completion.
- `unknown`: transport was entered or its outcome is uncertain; unresolved with no automatic retry.
- `not-sent`: Writer explicitly reported that transport had not been entered. Adds no completion coverage and does not invalidate earlier completed observations.

`confirmed_point_ids` includes points with an effective completed outcome that are not covered by any unreconciled pending/acknowledged/unknown attempt. Effective completion comes from an original receipt or a host-confirmed decision below. `all_points_confirmed` is True only when all expected points qualify. New unresolved attempts remove overlapping points while retaining unrelated completed points. Even a later successful retry cannot hide an older unresolved write until sufficient evidence supports explicit host reconciliation.

`unresolved_attempt_ids` lists uncertain attempts. These properties inspect local records only, not remote existence, correct model, relevance, retention or later service mutations. Do not display them as successful end-to-end acceptance. Empty indexes do not create this nonempty manifest and need no fabricated empty write.

## Replaceable protocol and persistence

`KnowledgeIndexJournal` defines async `begin()` / `record()` / `inspect()`. `SQLiteKnowledgeIndexJournal` is the local template and `KnowledgeIndexJournalSnapshot` its immutable read model. Construction performs no I/O; `initialize(confirm_create=True)` creates/checks a separate database, without modifying body snapshots, creating parent directories or migrating foreign databases.

Hosts can manually `begin(manifest, attempt_id, plan, confirm_write=True)`, run their own workflow, then `record(..., outcome=..., receipt=..., confirm_write=True)`. Trusted hosts must associate real evidence with the corresponding call, not reuse another attempt/process's receipt. The protocol authenticates neither remote receipts nor active-call ownership.

- Begin transactionally rejects duplicate attempt IDs. Target/vector_name, point subset and dimension must match the manifest. Batches may overlap; coverage deduplicates by point ID.
- Record transitions only pending to a final observation. Completed/acknowledged require typed receipts matching status, plan digest and count; unknown/not-sent accept no remote receipt.
- Identical final observations can be saved again to resolve uncertainty about local persistence. Different observations cannot overwrite stored outcomes. Reconciliation saves separate decisions without promoting or erasing original acknowledged/unknown records; a reconciled pending observation also rejects late record changes.
- `BEGIN IMMEDIATE` serializes same-database write checks. Independent connections cannot register the same attempt ID twice. This is not deduplication across manifests/databases and does not prevent explicitly creating another attempt ID.
- Each manifest supports at most 1024 attempts, each covering 1–128 points, against at most 1024 expected points. The database supports at most 1024 manifests, 8 MiB canonical JSON per record and 128 MiB total payload. These are not physical disk/journal/process-memory quotas; replace the implementation for larger workloads.
- Read-only connections bound payload bytes and validate canonical JSON, duplicate keys, format/digests, manifest identity, point membership and unique attempts. Corruption fails without partial state. Stored outcomes are logically immutable after finalization; this is not a one-row-per-event append log.
- Default `timeout=5` controls SQLite lock waiting, not total operation duration. Cancellation drains started worker operations and closes their connections before propagating; a commit may already have happened. Connections are per-operation, not persistent.
- Files/parent directories must be trusted. Content digests are not authentication and cannot prevent simultaneous content/digest tampering. Stored endpoints/embedding labels/IDs/operation IDs are not assumed public or anonymous.

## Host reconciliation against independent evidence

Optional `KnowledgeIndexReconciler` defines `reconcile()` without requiring existing `KnowledgeIndexJournal` plugins to implement it. The SQLite template implements both. `KnowledgeIndexReconciliation` binds a decision ID, manifest digest, attempt ID, exact plan digest, expected original outcome, decision outcome, evidence reference and actor reference.

Hosts must first stop/drain relevant work, establish that the exact local/remote call cannot produce late effects, and review independent evidence tied to that attempt and target. Cancelling a local coroutine, finding no search hit or seeing matching point IDs is insufficient. If late effects remain possible or evidence covers only part of the attempt, keep it unresolved rather than deciding the entire attempt.

```python
from w_agent import KnowledgeIndexReconciliation

# host_review is the host's completed independent review, not framework output.
# journal/manifest identify existing records; this example never resends a plan.
decision = KnowledgeIndexReconciliation(
    reconciliation_id=host_review.id,
    manifest_digest=manifest.digest,
    attempt_id=host_review.attempt_id,
    plan_digest=host_review.plan_digest,
    expected_outcome=host_review.original_outcome,
    outcome=host_review.outcome,
    evidence_ref=host_review.evidence_ref,
    actor_ref=host_review.actor_ref,
)
state = await journal.reconcile(
    decision, confirm_inactive=True, confirm_write=True,
)
print(state.effective_outcome(decision.attempt_id))
```

Unexecuted example; both confirmations must be literal True. `confirm_inactive` is a host assertion, not a lease or remotely verified fact. The library does not fetch evidence, authenticate actors, query remote services or execute/replay writes.

- Only original pending/acknowledged/unknown observations qualify. `completed` asserts that the entire exact plan completed; `not-applied` asserts no effect from this attempt and no possible late effect, not that those points currently do not exist remotely.
- `attempts` preserves original outcomes/operation IDs; `reconciliations` stores separate decisions. `effective_outcome(attempt_id)` returns the derived outcome. Not-applied removes this attempt's uncertainty without inventing completion; coverage from other completed attempts may become effective again.
- Decision IDs are unique per manifest, with at most one decision per attempt. Exact resubmission is idempotent; changing outcome, evidence, actor or ID cannot overwrite it. Transactions match the original outcome and plan before saving; conflicts do not persist changes. This does not authenticate evidence. Correcting an erroneous decision is not yet supported.
- References are nonblank host labels, at most 128 UTF-8 bytes without ASCII control characters. Default repr hides evidence/actor references, but JSON/database serialization stores them in plaintext. Never store credentials or evidence bodies here. References may point to host-retained evidence, without guaranteeing resolution, durability or trust.
- Journals without decisions retain canonical v1 JSON. First explicit reconciliation writes v2 JSON with decisions, leaving the SQLite table, application ID and user_version unchanged. Read-only inspect never rewrites v1. Older v1-only readers cannot read v2; do not blindly downgrade. At most 1024 decisions per manifest remain subject to existing payload limits.
- Cancellation or a failed local return does not prove the decision was uncommitted. Inspect first and, if necessary, resubmit the identical decision, never replay the remote write. All-point confirmation still requires separate real retrieval acceptance.

## Write failures and next steps

On remote errors/cancellation, the helper tries to record unknown, or not-sent when Writer explicitly reports no transport entry. If that local update fails, persisted pending remains conservative; the original remote exception is preserved without claiming successful recording. If a returned remote receipt cannot be persisted, fixed error `knowledge-index-receipt-persistence-failed` does not authorize remote replay: inspect local state and reconcile independent host evidence first. Repeated cancellation may interrupt local receipt persistence too; reread afterward.

The journal stores neither embedding usage nor vector values. It does not replace preparation accounting, vector-version artifacts or body snapshots. Hosts still manage budgets/resources/evidence and actual retrieval acceptance before publishing a queryable version.

## Progress and remaining work

Local journal/reconciliation regressions pass without live remote calls. `list_journals()` and `knowledge-index-list --database <journal-db> --confirm-read` expose verified receipt catalogs, also available as TUI List journal manifests. Optional `CoordinatedKnowledgeIndexJournal.begin_exclusive()` atomically rejects same-target unresolved point overlaps across manifests in one database. [Build execution and explicit retries](./knowledge-builds.en.md) require this capability; legacy low-level `begin()` preserves its original semantics. Hosts coordinate other databases, URL aliases and bypassing writers. Remote evidence collection, erroneous-decision revision, cleanup/difference synchronization, unified accounting and live-service acceptance remain unimplemented or unverified. See [preparation recovery](./knowledge-build-recovery.en.md) and the [roadmap](./roadmap.en.md).
