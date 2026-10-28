# Index journal management API, CLI and TUI

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-index-management.md)

Related entries include [exact plans/staging](./knowledge-index-plans.en.md) and [host factories with CLI/TUI prepare-save/approved-execute actions](./knowledge-plan-actions.en.md).

2.0.0 Experimental: local core and headless TUI regressions pass; included in 2.0.0 and outside `2.0.0a9`. This entry manages existing local journals. It never verifies remote state, creates databases, embeds documents, resends upserts or fetches evidence.

## API

`KnowledgeIndexReviewRequest` captures database path, exact manifest digest, optional `KnowledgeIndexReconciliation` and independent confirmations. `review_local_knowledge_index(request)` reuses SQLite `inspect()` / `reconcile()`. Pure `knowledge_index_review_view(snapshot)` also supports snapshots read by custom host journals. Underlying journal/reconciler protocols remain replaceable; the local convenience entry selects SQLite.

Default output includes manifest/snapshot digests, dimensions, expected/locally confirmed point counts, unresolved attempt IDs and per-attempt plan digest, original/effective outcome, point count and reconciliation ID. `all_points_locally_confirmed` describes local receipts/host decisions only; **`remote_state_verified` always remains False**. Inactivity, cancellation or missing search hits are not sufficient proof of non-application.

`include_details=True` additionally discloses endpoint, embedding label, vector name, point IDs, remote operation IDs and evidence/actor references. Default labels/digests can also be sensitive. Omitting bodies is not anonymization; hidden display fields remain in the database. This is neither encryption nor identity/evidence authentication.

## CLI

```powershell
wagent knowledge-index-inspect --database .wagent/knowledge-index.sqlite3 --manifest-digest <64-character-manifest-digest> --confirm-read

# Only after independent review and draining every possible late effect:
wagent knowledge-index-reconcile --database .wagent/knowledge-index.sqlite3 --manifest-digest <64-character-manifest-digest> --attempt-id build-v1-batch-001 --plan-digest <64-character-plan-digest> --expected-outcome unknown --outcome completed --reconciliation-id review-001 --evidence-ref audit-001 --actor-ref local-developer --confirm-read --confirm-write --confirm-inactive
```

Replace digest placeholders with exact real SHA-256 values from the journal; placeholders are not literal command arguments. Both commands default to the summary view; `--include-details` opts into sensitive fields. Options are validated before journal I/O. Missing read/write/inactivity consent rejects the request. Reads never create a missing database; management has no implicit initialization.

Original outcomes must be pending/acknowledged/unknown; decisions must be completed/not-applied. Decisions bind manifest, plan, attempt, expected original observation and evidence references. Transactional matching rejects stale state or a different existing decision. Identical decisions are idempotent; originals remain intact. `not-applied` asserts no effect and no late effect from this attempt, not absence of those points remotely. See [journal semantics](./knowledge-index-journal.en.md).

Confirmation is neither an execution lease nor an independently verified fact. Hosts must stop/drain relevant local and remote work and review independent evidence covering the entire exact plan. Keep uncertainty when evidence is incomplete; never reconcile merely to improve the coverage indicator. CLI arguments may enter shell history: use references without credentials or evidence bodies.

## TUI

Index journal provides existing journal path, manifest digest, attempt/plan identities, original outcome, decision outcome, reconciliation ID, evidence reference and actor reference.

- Inspect: enter `READ INDEX`, then Inspect local journal.
- Save a reviewed decision: additionally enter `WRITE DECISION` and `NO LATE EFFECTS`, then Save reviewed decision.
- Disclose sensitive details: additionally enter `SHOW INDEX DETAILS`.

Words are consumed per attempt. Incorrect words or write consent on a read-only inspection reject the request. Immutable captured options lock fields; later edits cannot change in-flight work. Relative database paths use the TUI workspace. Mounting performs no reads, discovers no manifests, selects no latest outcome and invents no evidence. Headless TUI regressions pass; manual layout and production interaction acceptance has not run.

Cancellation/unmount drains started SQLite threads. A decision may already be committed: inspect before retrying an identical decision. Errors omit underlying database exceptions/evidence; output escapes control characters and is not Rich markup. No remote write is requested, so local failure must never become an automatic remote resend.

## Progress and remaining work

Local request/view/API, CLI and TUI regressions pass for consent, state conflicts, retained observations, capture and cancellation.

`list_local_knowledge_journals()`, `knowledge-index-list --database <journal-db> --confirm-read` and TUI List journal manifests discover manifests and unresolved attempts without a known digest. Catalogs verify every entry; missing/corrupt data fails instead of appearing empty, and sensitive details require opt-in. See [builds and safe retries](./knowledge-builds.en.md) and [preparation recovery](./knowledge-build-recovery.en.md). Remote point verification, erroneous-decision revision, cleanup/difference synchronization, unified accounting and live model/vector-service acceptance remain unimplemented or unverified. See the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
