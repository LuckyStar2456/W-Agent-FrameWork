# Full knowledge-index builds and per-batch continuation

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-builds.md)

2.0.0 Experimental: local core regression tests pass. Live services, billing and remote retrieval acceptance remain unverified; included in 2.0.0 and outside 2.0.0a9.

## Pin a complete prepared selection

`KnowledgeIndexBuild(name, version, manifest, plans)` pins a user-selected ordered tuple of `KnowledgeIndexPlanInfo`. It requires one exact manifest, 1–128 unique artifacts, disjoint batches and complete expected-point coverage. Missing/overlapping selections fail; no latest plan or replacement vectors are selected automatically. Names, versions, order, manifest and plan references all affect the build digest.

The build holds artifact/plan digests, point IDs and target manifest, not source bodies, vectors or credentials. `assemble_knowledge_build()` explicitly reads/verifies selected artifacts through a replaceable plan store before construction. Construction/save grant no execution approval or model/quality proof.

`knowledge_build_from_json()` validates the digest, exact fields, duplicate keys, format, canonical serialization and disjoint full coverage. Digests provide integrity, not signatures/provenance. Serialized targets/labels remain sensitive; summary views omit them.

## Persistence and local entry points

Replaceable `KnowledgeBuildStore.save/load` is separate from staging and observations. `SQLiteKnowledgeBuildStore` is a fourth dedicated store: **source snapshots, vector plans, build manifests and receipt journals must not share a database**. User-named versions are insert-only: identical content is idempotent, different content cannot overwrite a version and corruption fails rather than repairing. Bounds: 1 MiB per build, 1024 versions/64 MiB aggregate payload; not disk/process-memory quotas.

Construction has no I/O; creation and save have independent consent and parent directories must exist. No schema migration, collection creation, vector copying or deletion. Cancellation drains started SQLite workers and may follow a commit. Lost vector files are not reconstructed from a build.

```powershell
# Explicit full, disjoint selection; preview by default, without opening build DB
wagent knowledge-build-create --plan-database .wagent/knowledge-plans.sqlite3 --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --artifact-digest <first-artifact-digest> --artifact-digest <second-artifact-digest> --confirm-read
# Add --confirm-save to persist, and --confirm-create for a new build DB

wagent knowledge-build-inspect --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --confirm-read
# Add --journal-database .wagent/knowledge-index.sqlite3 for an existing journal's progress
```

Replace placeholders with real digests; repeat artifacts in desired order. `create_local_knowledge_build()` / `review_local_knowledge_build()` are shared local APIs. Preview/save is not a locked transaction, but immutable artifact identities with unchanged name/version/order produce a stable build identity.

Build inspection does not reread vectors and returns `artifact_availability_checked=False`; it cannot prove every plan remains available. Progress requires an explicitly supplied journal. Missing/corrupt/inaccessible journal databases fail, never inventing a fresh build. Only **an accessible supported journal explicitly reporting that manifest absent** denotes no attempts for it in that journal. Custom implementations must preserve that not-found meaning, never map I/O failure to absence.

## Continue individual batches, never auto-replay

Each batch's stable attempt ID derives from build/artifact digests. `knowledge_build_progress()` / `inspect_knowledge_build_progress()` derive original/effective observations, foreign unresolved overlaps and `can_request_first_execution`.

- No prior corresponding attempt and no overlapping foreign pending/acknowledged/unknown is required to request first execution; this is not approval.
- A matching attempt ID with a different plan/point order is an error, not evidence for this batch.
- Completed receipts or host-reconciled completed results count locally, unless foreign unresolved overlaps block completion.
- No outcome automatically retries. `retry_knowledge_build_batch()` explicitly permits only not-sent or independently reconciled not-applied, binding the latest predecessor and separately approved build/artifact digests. Stable successor IDs preserve history. Pending/acknowledged/unknown cannot directly retry.
- `all_batches_locally_completed` describes these exact local attempts only; `remote_state_verified=False` remains. Success from another build cannot stand in for this batch or prove current remote vectors.

```python
from w_agent import execute_knowledge_build_batch, inspect_knowledge_build_progress
from my_application import build, plans, writer, journal, selected_artifact, reviewed_build, reviewed_artifact

progress = await inspect_knowledge_build_progress(build, journal)
# After independent host/user review, explicitly execute one selected batch.
receipt = await execute_knowledge_build_batch(
    build, selected_artifact, plans, writer, journal,
    confirm_build_digest=reviewed_build,
    confirm_artifact_digest=reviewed_artifact,
    confirm_record=True,
)
```

Execution checks separate approval, exact artifacts and journal state, then uses pending → one remote write → final observation. Builds require `CoordinatedKnowledgeIndexJournal.begin_exclusive()`. SQLite checks unresolved overlapping points across manifests sharing the exact endpoint/vector_name and reserves pending in one `BEGIN IMMEDIATE` transaction. Stable duplicate IDs and unresolved overlaps fail; reservations never expire automatically. Hosts coordinate other databases, URL aliases and writers using low-level begin or bypassing the journal. Progress is manifest-local; execution performs the additional atomic cross-manifest check.

Artifacts, builds and journals are separate storage boundaries. Reinspect after cancellation/receipt persistence failure and reconcile unknowns only with independent evidence. Renaming a build cannot bypass unresolved overlaps on the same target in the shared journal. Separate databases do not share coordination.

## Explicit execution entry and TUI

Frozen `KnowledgeBuildExecuteRequest` and `execute_local_knowledge_build_batch()` form the shared local CLI/TUI entry. Reading, remote overwrite and journal writes require separate consent; `KnowledgeIndexHostOptions` independently approves trusted unisolated host code. Names/versions, three database paths, digests and consent values receive pure preflight validation. Loaded build approval, artifact membership and exact plan references are checked before importing the host; writer target/request-size mismatch fails before journal creation.

```powershell
wagent knowledge-build-execute --host examples.knowledge_index_host:index_catalog --binding execute --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --plan-database .wagent/knowledge-plans.sqlite3 --journal-database .wagent/knowledge-index.sqlite3 --artifact-digest <selected-artifact> --approved-build-digest <independently-reviewed-build> --approved-artifact-digest <independently-reviewed-same-artifact> --confirm-code --confirm-read --confirm-remote-write --confirm-record
# Add --confirm-create-journal only to explicitly initialize a journal. No build creation or re-embedding.
```

Developers own the host factory and cleanup; execution-only bindings need no embedder. Trusted factory code may have its own side effects; consent is not isolation. The scope exits before returning. Cleanup failure can follow a successful write and saved receipt: reinspect, never resend merely because an error occurred. Other unattempted batches require independent selection; there is no execute-all action.

The new `Knowledge builds` TUI tab provides:

- Create: enter name/version, plan/build databases and an ordered JSON artifact-digest array. `READ BUILD INPUTS` previews; add `SAVE BUILD` to persist and `CREATE BUILD STORE` for a new store.
- Inspect: enter exact name/version/build DB and `READ BUILD INPUTS`. Leave journal blank for build-only inspection, or supply it for local progress. This does not automatically reread vectors.
- Execute: enter one artifact digest, independently reviewed build/artifact digests, named host binding and three database paths. Independently enter `READ BUILD INPUTS`, `LOAD INDEX HOST`, `WRITE INDEX`, `RECORD WRITE`, plus `CREATE INDEX JOURNAL` only for explicit journal initialization.

Approval fields are never auto-filled. All consent words are consumed on capture, including invalid submissions; unrelated action consent is rejected. Frozen requests run in the background with locked inputs. Cancellation/unmount drains the active task. Displays use fixed errors and escaped summaries, not exception bodies or credentials. Cancellation is not rollback; headless TUI regressions pass; manual layout and production interaction remain unverified.

## Catalogs, explicit retries and preparation recovery

`SQLiteKnowledgeBuildStore.list_builds()` and `SQLiteKnowledgeIndexJournal.list_journals()` verify bounded catalogs in read transactions. Missing/corrupt stores fail instead of appearing empty. Use `knowledge-build-list --database <build-db> --confirm-read` or `knowledge-index-list --database <journal-db> --confirm-read`. TUI List saved builds / List journal manifests do not require a known name or digest.

`knowledge-build-execute --previous-attempt-id <latest-safe-failed-attempt>` requests an explicit retry; the TUI exposes the same predecessor input. Other approvals remain required. Progress includes `attempt_history`, `can_request_retry` and `next_retry_attempt_id`. Stale predecessors, completed and uncertain attempts do not send; first execution never implicitly becomes retry.

Optional [durable preparation checkpoints](./knowledge-build-recovery.en.md) resume completed batches across processes while blocking uncertain embedding replays. Distributed leases, per-document checkpoints, exact billing archives and live remote acceptance remain outside this implementation. See the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
