# Durable import provenance and explicit incremental index synchronization

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-sync.md)

Later work adds [shared CLI management](./knowledge-sync-entries.en.md) and the [complete TUI main path](./knowledge-sync-tui.en.md). See [sync/accounting acceptance](./acceptance-2026-10-01-sync-usage.en.md) for 282 separately scoped checks; the initial underlying-module evidence remains below.

2.0.0 Experimental, included in 2.0.0. Authorized focused knowledge integration checks in the existing clean project environment returned **115 passed / 2 skipped, 117 collected, 4.78 seconds**, including 31 sync cases, 15 real-format parser cases, file/Writer/cross-module checks and exports. The two skips are Windows symlink/FIFO limitations, not missing parser dependencies. The previous 1811 tests are not evidence for these new behaviors; do not add overlapping package checks across groups. No live Qdrant/embedding calls, billing/quality acceptance or publication occurred. Construction and planning have no external effects.

## Trace persistence and cross-version vector caches

`KnowledgeImportStore` is a replaceable `save(trace, confirm_write=...)` / `load(namespace, version)` protocol. Explicitly initialize `SQLiteKnowledgeImportStore` to retain already-extracted originals, raw/parsed fingerprints, snapshots and offsets. Identical saves are idempotent; conflicting named versions never overwrite. Loads validate canonical JSON, digest, source mapping and regenerated chunks. No source file is automatically read/written; original binary archival is not provided.

```python
from w_agent import (
    SQLiteKnowledgeImportStore, LocalTextKnowledgeImporter,
    prepare_traced_knowledge_import, prepare_knowledge_sync_index,
    KnowledgeSyncPlan, SQLiteKnowledgeSyncJournal,
    QdrantKnowledgeSyncWriter, QdrantVectorWriter, QdrantVectorSearch,
    execute_knowledge_sync,
)

traces = SQLiteKnowledgeImportStore("imports.sqlite")
await traces.initialize(confirm_create=True)  # Parent directory must exist.
# On the first import previous_trace/previous_index are None.
# Later, explicitly load the prior trace and load_plan(completed_digest).current.
loaded = await LocalTextKnowledgeImporter(root).load(
    ("manual.md",), confirm_read=True,
    previous=previous_trace.imported if previous_trace is not None else None,
)
current_trace = prepare_traced_knowledge_import("manual", "v2", loaded)
await traces.save(current_trace, confirm_write=True)
current_index = await prepare_knowledge_sync_index(
    current_trace, "host-pinned-model-v1", 768, embedder,
    previous=previous_index, confirm_embedding=True,
    confirm_reuse_digest=previous_index.digest if previous_index is not None else None,
)
```

This host wiring example has not been executed against live services. The host reviews the prior cache before approving its exact digest; a model must not self-approve an object's digest. Model/preprocessing identity remains host-controlled: labels and digests do not authenticate actual model identity. Missing reuse approval fails before embedding when reusable points exist.

The separate `wagent-knowledge-sync-point-v1` identity binds namespace, parser_key, complete file records (path/raw/text hashes, lengths, source document ID), chunk configuration, character/byte slices, text/source/title, embedding_key and dimensions, **excluding snapshot version**. A version-only change reuses exact vectors and makes zero embedding calls. Only added/changed-file chunks are embedded. Any file/BOM/parser/chunk/model change may invalidate all chunks from that file: this is file-level incremental indexing, not semantic deduplication. Existing snapshot-bound IDs are never migrated implicitly.

`KnowledgeSyncIndex` contains at most 1024 points and 1048576 vector values. Full disclosed selection limits are checked before calls; failures may follow paid calls, without automatic retry/refund. Conflicting vectors for one stable ID are rejected. `KnowledgeSyncPlan` binds full previous/current caches; journal staging persists exact vectors and traces before sending. `load_plan(digest)` reopens prepared work without embedding again.

## Separate upsert and delete approval

```python
writer = QdrantKnowledgeSyncWriter(QdrantVectorWriter(
    QdrantVectorSearch("http://localhost:6333", "dedicated_knowledge")
))
journal = SQLiteKnowledgeSyncJournal("sync.sqlite")
await journal.initialize(confirm_create=True)
plan = KnowledgeSyncPlan(writer.endpoint, writer.vector_name, current_index, previous_index)
preview = plan.summary()  # No bodies/vectors; separate upsert/delete digests and counts.
# Review targets, changes and deletion scope; supply independently approved digests.
result = await execute_knowledge_sync(
    plan, writer, journal,
    confirm_plan_digest=approved_plan_digest,
    confirm_upsert_digest=approved_upsert_digest,
    confirm_delete_digest=approved_delete_digest,
    confirm_record=True,
)
```

Upserts are current points absent from previous; deletions are strictly previous-owned IDs absent from current. Approval binds the full plan and exact batches; upsert approval cannot authorize deletion. Batches contain at most 128 points, all upserts precede deletion, and empty/version-only plans still require plan/record consent before advancing the local head without network calls.

`KnowledgeSyncWriter` is replaceable. The Qdrant adapter borrows existing upserts and uses the [official ID deletion API](https://api.qdrant.tech/api-reference/points/delete-points): `POST /collections/{collection}/points/delete?wait=true` with exact IDs, no filters or collection drops. Deletion removes entire points including all named vectors/payload. Use a dedicated host-owned collection. Older versions can lose remote retrieval when stale points are deleted, although archived extracted originals remain; use separate collections or the existing snapshot-bound indexing model when all historical versions must stay remotely retrievable.

`SyncVectorKnowledgeRetriever` maps sync IDs to current local snapshot documents and restricts candidates; it never trusts remote text payloads. Completion does not prove retrieval quality or durable remote existence.

## Journaling, restart and safe retry

`KnowledgeSyncJournal` is replaceable. SQLite atomically maintains a collection endpoint's head and active plan. New plans must follow a completed predecessor; unresolved work blocks branches/new genesis and named-vector changes cannot reuse a head. Every batch commits `ready → pending` before transport entry. Resume skips completed batches and continues ready batches. Pending/unknown/acknowledged outcomes never replay, advance later batches or advance the head. Receipt-persistence failure leaves a pending barrier; cancellation may follow a send/commit.

Definite pre-transport `not-sent` supports separately approved retries:

```python
from w_agent import knowledge_sync_retry_digest

# inspect_observations exposes raw outcome, generation, operation ID and evidence.
# After reviewing not-sent, approve this exact plan/batch/generation retry digest.
await journal.retry_not_sent(
    plan.digest, batch=0, generation=0, retry_id="manual-retry-1",
    confirm_retry_digest=approved_retry_digest, confirm_write=True,
)
# execute still requires plan/action approvals and never re-embeds.
```

`knowledge_sync_retry_digest(plan.digest, batch, generation)` computes the digest to present for approval. One transaction inserts the immutable prior not-sent generation in `sync_retries`, then sets the next generation ready. Stale generations, duplicate retry IDs and uncertain outcomes fail. At most 64 explicit retries are retained per plan. `inspect_retries()` exposes old generations; `inspect_observations()` exposes current raw receipts/evidence. Reconciliation preserves original acknowledged/unknown observations.

`reconcile_completed()` accepts only independently host-verified application with no late effects, explicit write consent and a bounded evidence reference. It does not query Qdrant or authenticate evidence. Unknown/not-applied retry/abandonment is not implemented; unknown work stays blocked rather than replaying. Never falsely declare completion to unlock a target.

Endpoints must use canonical spelling: lowercase hostname; no explicit default ports, trailing/double slashes, dot/encoded ambiguous path segments, credentials/query/fragment. Plans and adapters reject other spellings. Different DNS aliases, reverse proxies, other databases and bypassing writers remain host-coordinated; this is not a remote or cross-database lease.

## Storage and validation boundaries

Trace and sync stores use separate application IDs and dedicated `user_version=1` schemas. The initial sync schema has targets/plans/batches/retries tables; earlier experimental schemas are rejected, not migrated. Other knowledge stores remain unchanged. Construction performs no I/O; reads cannot create a missing database; initialization never creates parents. Stored text/vectors/references are plaintext. Defaults admit 1024 records/plans and 512 MiB payload, bounded to 96 MiB per trace and 256 MiB per plan; these are not physical disk/memory quotas. Directories/databases must be trusted. Cancellation drains started workers without promising rollback.

All 31 new `tests/test_knowledge_sync.py` cases pass, covering real temporary SQLite reopen, incremental cache/source/model binding, exact deletion, separate consent, unknown/cancel/ack barriers, concurrent claims, two-batch resume, empty plans, canonical endpoints, corruption and not-sent retry generations. All four new modules pass compileall. Network operations use injected transports, not live Qdrant. The root's focused knowledge integration result is 115 passed / 2 skipped; the earlier 1811 tests are not proof of this increment.
