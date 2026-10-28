# Plan catalogs, preparation coverage and missing-batch advice

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-plan-catalog.md)

2.0.0 Experimental: local regressions pass; included in 2.0.0 and outside 2.0.0a9. Live services, billing, quality and manual production UI acceptance remain outstanding.

## Optional catalog and consistent reads

`KnowledgeIndexPlanCatalog.list_plans()` is optional, leaving existing `KnowledgeIndexPlanStore.save/load` plugins unchanged. Immutable `KnowledgeIndexPlanInfo` contains artifact/plan digests, full manifest and batch point IDs, not floats. Hosts constructing metadata themselves own its accuracy; typed validation does not prove vectors were read correctly.

SQLite sorts by artifact digest in one read-only transaction. It checks schema and 128-artifact/256-MiB-total-payload bounds, then strictly decodes each artifact, validating inner/outer digests and canonical JSON. Each row is at most 32 MiB. Vectors are discarded between rows; only identity metadata remains. Any corrupt/oversized/unsupported content fails the whole read, never returning partial success. Manifest filtering does not hide corrupt unrelated rows.

There is no DB creation, host-code loading, embedding, remote write or journal mutation. The transaction gives one catalog snapshot, not a lease, frozen database or process-memory quota. SQLite timeout governs lock waits, not total decoding time. Cancellation drains the started read worker.

## Coverage analysis

`KnowledgePlanCoverage(manifest, plans)` requires one **exactly matching manifest**, unique artifact digests and at most 128 plans. An empty tuple represents a known manifest with nothing staged yet.

- `prepared_point_ids`: union of staged point IDs in manifest order.
- `missing_point_ids`: expected points covered by no staged plan.
- `overlapping_point_ids`: points appearing in multiple artifacts; no winner is selected.
- `all_points_prepared` means complete union coverage, possibly with overlaps.
- `batches_disjoint` only describes overlap. Overlap does not prove differing vectors; disjointness does not prove the correct model.
- `execution_selected=False` and `remote_state_verified=False` explicitly deny execution selection/remote verification. Prepared does not mean executed, accounted or retrieval-accepted.

Discovery covers **manifests referenced by existing staged artifacts**, not all write-journal manifests. A requested manifest with no artifact is not-found, never mistaken for having no missing points. A full query of an empty catalog returns empty lists.

## CLI and TUI catalog

```powershell
wagent knowledge-plan-list --database .wagent/knowledge-plans.sqlite3 --confirm-read
wagent knowledge-plan-list --database .wagent/knowledge-plans.sqlite3 --manifest-digest <manifest-SHA256> --confirm-read --include-target
```

Replace placeholders with real digests. `review_knowledge_plan_catalog()` is the shared local API. Default output has digests, counts and preparation/overlap indicators. `--include-target` additionally discloses targets, embedding labels, batch IDs and missing/overlapping point IDs. No floats or source bodies are displayed. `artifacts_integrity_verified=True` reports internal artifact consistency only, not source authentication; labels/digests can also be sensitive.

TUI Index plans adds List plans and coverage plus an optional manifest filter. Enter `READ PLAN`, additionally `SHOW TARGET` for target/point-ID details. No artifact digest is needed. Approval digests are never auto-filled and no host factory runs. Confirmation is consumed and captured fields lock. Results grant no write permission. Layout/interaction remains unaccepted.

## Missing-batch advice

Pure `plan_missing_knowledge_batches(index, coverage)` requires matching snapshot digest, embedding label, dimensions and full expected point sequence. It greedily partitions missing points in stable snapshot-document order. Defaults: 128 documents, 1 MiB of exact embedding JSON input and 1,048,576 vector values per batch. API callers may adjust bounds but must match the eventual preparation configuration.

Each `KnowledgePreparationBatch` retains manifest digest, document/point IDs, input bytes and a stable advisory digest, not bodies/vectors. An oversized missing document fails the entire planning call; no missing points returns an empty tuple. Existing points are skipped because they are staged, not quality-verified. Bytes are not tokens, prices or reservations. Writer request size still requires checking after float generation.

```powershell
wagent knowledge-plan-batches --plan-database .wagent/knowledge-plans.sqlite3 --source-database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --manifest-digest <manifest-SHA256> --confirm-read --include-ids
```

Shared `review_missing_knowledge_batches()` reads the catalog and exact body snapshot, checks identities and returns advice. `--include-ids` discloses document IDs suitable for a later explicit `knowledge-plan-prepare --document-ids`. Bodies are read only to count input bytes, never sent to a service. Two database reads are not an atomic cross-store snapshot or capacity reservation; concurrent staging may stale the advice, so reread before acting when needed.

The management entry requires at least one existing artifact for that manifest. New manifests can use the pure API with empty `KnowledgePlanCoverage`, or explicitly prepare the first batch. Batch advice has API/CLI/TUI entries with passing local and headless TUI regressions. There is no automatic suggestion persistence, paid backfill, attempt-ID generation, batch execution approval or unknown-receipt handling.

The local API and CLI also accept `max_documents` / `--max-documents` (1–128), `max_input_bytes` / `--max-input-bytes` (1–33,554,432) and `max_vector_values` / `--max-vector-values` (1–1,048,576). Bounds and database-path separation are validated before reads. Returned `limits` echo the planning configuration. These are partition bounds, not execution settings or cost budgets. The current local prepare entry still uses a fixed 1-MiB input bound; larger advice does not automatically raise it.

### TUI missing-batch advice

In `Index plans`, enter plan/source databases, exact namespace/version and a **required** manifest digest (shared with the catalog filter). Adjust the batch bounds and enter the distinct `READ BATCH INPUTS` confirmation before pressing `Suggest missing batches`. It reads the complete plan catalog and selected body snapshot only to analyze missing points/input bytes. Document/point IDs default to hidden; disclose them separately with `SHOW BATCH IDS`. Bodies and vector values are never displayed.

No host binding is needed. `READ PLAN` and `READ SOURCE` cannot replace the action-specific consent; target disclosure, embedding, save and execution consent are rejected as unrelated. Confirmations are consumed on capture, including failed submissions. Frozen requests lock fields while running; cancellation/unmount drains the task. Results do not auto-fill document selection or approval fields. Preparation remains a separately configured/authorized action. Headless TUI cancellation/interaction regressions pass; manual layout and production interaction acceptance remain outstanding.

## Progress and remaining work

Local regressions pass for discovery, strict SQLite catalog reads, coverage/overlap analysis, CLI/headless TUI catalogs and adjustable missing-batch advice.

[Build and receipt catalogs, explicit safe retries](./knowledge-builds.en.md), same-database conflict coordination and [ready preparation recovery](./knowledge-build-recovery.en.md) are implemented with local regression coverage. Automatic paid backfill, pending replay, cross-store leases, preparation/main-Run accounting, remote verification and production acceptance remain outside this implementation.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
