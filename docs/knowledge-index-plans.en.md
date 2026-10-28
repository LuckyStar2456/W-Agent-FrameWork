# Exact knowledge-vector plans and staging

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-index-plans.md)

2.0.0 Experimental: local regressions pass; included in 2.0.0 and outside 2.0.0a9. Live services, billing, quality and manual production UI acceptance remain outstanding.

## Separate preparation from execution

Preparation, review and execution must retain the same vector values and target. `PreparedKnowledgeIndexPlan` stores a full `KnowledgeIndexManifest` plus one exact batch of `QdrantUpsertPlan` vectors. Execution never rereads source bodies, re-embeds or expands the batch.

The artifact digest binds format, full manifest and vectors; the manifest digest binds all expected points/target; the plan digest binds the exact remote request. They are not interchangeable. Digests provide identity/integrity, not signatures, authority or embedding-quality proof. A full manifest may span multiple batches; one staged batch does not mean the whole index is prepared.

## Prepare, stage, review, execute

```python
from w_agent import (
    SQLiteKnowledgeIndexPlanStore, SQLiteKnowledgeIndexJournal,
    prepare_knowledge_index_plan, execute_prepared_knowledge_plan,
)
from my_application import index, embedder, writer, review_saved_artifact

# Confirmations represent actual host authorization; this example was not run.
artifact = await prepare_knowledge_index_plan(
    index, embedder, writer,
    document_ids=("document-1",), confirm_embedding=True,
)
plans = SQLiteKnowledgeIndexPlanStore("knowledge-plans.sqlite3")
await plans.initialize(confirm_create=True)
digest = await plans.save(artifact, confirm_write=True)

# Reopen later/in another process, without re-embedding.
saved = await plans.load(digest)
# Host reviews the exact artifact and target; never blindly copy untrusted input.
approved_digest = await review_saved_artifact(saved)
journal = SQLiteKnowledgeIndexJournal("knowledge-index-journal.sqlite3")
await journal.initialize(confirm_create=True)
receipt = await execute_prepared_knowledge_plan(
    saved, writer, journal, attempt_id="build-v1-batch-001",
    confirm_artifact_digest=approved_digest, confirm_record=True,
)
```

The host assembles `index`, `embedder` and `writer`. Preparation requires explicit body-embedding consent. `document_ids=None` selects the whole snapshot only when it fits one batch; empty batches are refused and larger snapshots require explicit subsets. Preparation never saves, creates collections or writes remotely. Hosts own borrowed resources and may wrap embeddings with shared budgets; preparation costs are not automatically attributed to an Agent Run.

Execution requires exact artifact approval plus journal-write consent. It rechecks the current Writer's target, vector name and request size, persists pending, sends once and records the receipt. Same-attempt-ID execution is refused. Different IDs/databases do not provide global deduplication; hosts must still review overwrite risks. The caller supplies externally reviewed `confirm_artifact_digest`; only then does the helper pass the enclosed plan digest to the existing Writer. Staging never implies authorization.

## Format and storage

- `to_json()` explicitly emits sensitive canonical JSON containing floats, not a routine log view. No source bodies, API keys or runtime objects are stored. Vectors, endpoints, labels and point IDs can still disclose business information.
- `prepared_knowledge_plan_from_json(payload, expected_digest=...)` checks the externally selected digest, format, exact fields, duplicate keys, finite numbers, dimensions, point membership, inner digests and canonical serialization. Invalid input never produces a partial plan. Hashing untrusted content yourself does not authenticate its origin.
- Each batch has 1–128 points; each manifest at most 1024. Dimensions are at most 65536, total coordinates at most 1,048,576, JSON at most 32 MiB. Preparation defaults to 1 MiB total input and a 30-second batch timeout.
- Writer request limits still apply and may be smaller. A post-embedding request-size failure can follow billed calls; partial vectors are not automatically saved or retried.
- Replaceable `KnowledgeIndexPlanStore` defines save/load. SQLite uses a **separate plan database**, not the source-snapshot or write-journal DB. Construction performs no I/O; creation and save have independent consent, and parent directories must exist.
- Digest-keyed inserts are idempotent for identical content. Corrupt existing rows fail instead of being silently overwritten. Reads use read-only connections and verify integrity; missing files are not created and unknown schemas are not migrated. Admission limits are 128 artifacts and 256 MiB aggregate payload, not disk/WAL/process-memory quotas.
- Cancellation drains started SQLite workers; commits may already have happened. Preparation, staging, pending registration, remote write and receipt persistence are distinct boundaries. Failure never implies rollback of earlier actions; inspect before retrying, without automatic re-embedding/replay.

## Read-only management

```powershell
wagent knowledge-plan-inspect --database .wagent/knowledge-plans.sqlite3 --artifact-digest <artifact-SHA256> --confirm-read
# Add --include-target to disclose target, embedding label and batch point IDs
```

Replace the placeholder with the real artifact digest. `inspect_stored_knowledge_plan()` is the shared local view API. Default summaries omit vectors and sensitive targets; target disclosure still omits vectors. `authorized=False` means the view grants no authority; `remote_state_verified=False` means no remote verification, not a verified absence.

TUI Index plans requires `READ PLAN`; `SHOW TARGET` additionally discloses target fields. Words are consumed, captured options lock fields, and cancellation is available. Mounting performs no reads/execution. Relative paths use the TUI workspace. Output escapes control characters and never interprets Rich markup. Headless TUI regressions pass; manual layout and production interaction acceptance has not run.

## Progress and remaining work

Local regressions pass for exact-plan codecs, replaceable staging/SQLite persistence, preparation/approved execution, CLI inspection and headless TUI capture, including tampering, consent and duplicate-attempt rejection.

[Host actions](./knowledge-plan-actions.en.md), [catalogs/batch advice](./knowledge-plan-catalog.en.md), [full builds and safe retries](./knowledge-builds.en.md), and [ready preparation recovery](./knowledge-build-recovery.en.md) are implemented with local regression coverage. Same-database conflict coordination is not a cross-database lease. Preparation/main-Run accounting, live index verification, other backends and production acceptance remain incomplete. Import extensions and hybrid/Workflow/evaluation APIs are documented in their own topics.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
