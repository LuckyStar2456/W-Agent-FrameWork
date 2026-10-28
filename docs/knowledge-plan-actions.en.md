# Knowledge-plan preparation, staging and authorized execution

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-plan-actions.md)

2.0.0 Experimental: local API/CLI and headless TUI regressions pass. Live services, billing and production visual acceptance remain unverified; included in 2.0.0 and outside 2.0.0a9.

## Host bindings and lifecycle

`KnowledgeIndexHostOptions(entry, binding, confirm_code=True)` selects `module:factory`. The zero-argument factory returns an async context manager yielding a catalog of 1–64 named `KnowledgeIndexHostBinding` values. Names follow named-knowledge binding constraints and must include the selected entry.

A binding contains `QdrantVectorWriter`. Preparation additionally needs `AsyncTextEmbedder`, a host-maintained `embedding_key` and exact dimensions; execution-only bindings can omit embeddings entirely. This management template targets Qdrant; underlying text/vector/budget/transport interfaces remain replaceable and other backend management templates remain planned. Hosts may wrap embeddings with shared budgets; preparation costs are not automatically merged into an Agent Run.

This is **explicitly authorized, non-isolated local development code**. `--confirm-code` / `LOAD INDEX HOST` authorizes import/setup/cleanup, not Python sandboxing. The framework cannot restrict side effects performed by arbitrary host code. Load only reviewed modules; hosts must provide separate OS isolation when required. This switch is not a sandbox.

Factories own resource creation/cleanup. After successful entry, invalid catalogs, body failures and cancellation attempt exit; a True exit result cannot suppress action errors. Simultaneous body/cleanup failure preserves the original error with a fixed cleanup note. Cleanup failure after success still reports failure even if billing, storage or a remote write already happened. Factories own cleanup during incomplete setup; repeated cancellation may interrupt cleanup. Never blindly retry.

See `examples/knowledge_index_host.py`, with prepare/execute bindings. It creates no collections, installs no models and reads no environment credentials. Its model name is a placeholder requiring user edits; dimensions/service availability are unverified. Loading the example does not establish a working model.

## CLI

```powershell
# Authorize preparation and staging; whole snapshot must fit one batch (<=128 docs)
wagent knowledge-plan-prepare --host-entry examples.knowledge_index_host:index_catalog --binding prepare --source-database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --plan-database .wagent/knowledge-plans.sqlite3 --confirm-code --confirm-read --confirm-embedding --confirm-save --confirm-create

# Inspect exact content identity/target and review independently
wagent knowledge-plan-inspect --database .wagent/knowledge-plans.sqlite3 --artifact-digest <artifact-digest> --confirm-read --include-target

# Only after review: provide the same separately approved digest, not an auto-pipeline
wagent knowledge-plan-execute --host-entry examples.knowledge_index_host:index_catalog --binding execute --plan-database .wagent/knowledge-plans.sqlite3 --artifact-digest <artifact-digest> --approved-digest <same-independently-approved-digest> --journal-database .wagent/knowledge-index.sqlite3 --attempt-id build-001 --confirm-code --confirm-read --confirm-remote-write --confirm-record --confirm-create-journal
```

Replace digest placeholders. Run the example from the repository root or use your own importable module. Database parent directories must exist. Optional `--document-ids` is a JSON array within 64 KiB, containing 1–128 unique string/integer source-document IDs, not vector point IDs. Empty arrays, booleans and unknown documents fail. Omission selects the entire snapshot only when it fits one batch. Chunked snapshots require their chunk-document IDs.

`KnowledgePlanPrepareRequest` requires independent read/embedding/save consent plus host-code consent; plan-DB creation additionally requires `--confirm-create`, target output `--include-target`. It loads the exact source snapshot and checks selection before creating/checking the plan store and entering host code. Existing-store preflight checks schema read-only, not capacity or future writability. Success returns a staging summary, never a remote write. Failure may follow billed embeddings or leave an authorized empty database.

`KnowledgePlanExecuteRequest` requires read/remote-overwrite/journal-record consent and a separately approved digest exactly matching the artifact; journal creation additionally requires `--confirm-create-journal`. All static options/consents validate before I/O/import. It then verifies saved vectors, loads the host, checks target/vector-name/request-size compatibility and only then may create a journal and execute. Framework orchestration never re-embeds, creates collections or retries; arbitrary host-factory behavior remains the user's review responsibility.

`prepare_local_knowledge_plan()` and `execute_local_knowledge_plan()` implement the separate actions. Preparation accepts no remote-write consent; execution accepts no body-embedding consent. CLI has no combined prepare-and-send command. completed/acknowledged receipts remain observations; `remote_state_verified=False` never becomes index acceptance.

## TUI

Index plans retains inspection and adds host/binding, source DB/namespace/version/document IDs, journal DB/attempt ID and a separately entered approval digest.

| Action | Required consent | Optional consent |
| --- | --- | --- |
| Inspect saved plan | `READ PLAN` | `SHOW TARGET` |
| Prepare and save | `READ SOURCE`, `LOAD INDEX HOST`, `EMBED DOCUMENTS`, `SAVE PLAN` | `CREATE PLAN STORE`, `SHOW TARGET` |
| Execute reviewed plan | `READ PLAN`, `LOAD INDEX HOST`, `WRITE INDEX`, `RECORD WRITE`, plus exact approved digest | `CREATE INDEX JOURNAL` |

Confirmation words are consumed even on capture failure. Unrelated action consent is rejected. Approval digests are never auto-filled from a read result. Requests are captured and fields locked before background work; later edits cannot replace in-flight options. Cancellation/unmount attempts factory cleanup and drains SQLite workers, but billing/commits/remote effects may already exist. Output is not Rich markup and omits underlying exception bodies. Inspect plans/journals before retrying. Headless TUI regressions pass; manual layout and production interaction remain unaccepted.

## Progress and remaining work

Local regressions cover host lifecycle and single-batch preparation/execution. [Build and receipt catalogs with explicit safe retries](./knowledge-builds.en.md) are implemented. Optional request fields `preparation_database` / `preparation_attempt_id` and equivalent hyphenated CLI flags enable [durable preparation checkpoints](./knowledge-build-recovery.en.md). Ready recovery needs no new embedding consent; pending needs independent review. Other backends, exact billing archives, remote verification and production acceptance remain unimplemented or unverified. See [exact plans](./knowledge-index-plans.en.md), [journals](./knowledge-index-journal.en.md) and the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). Live-service, billing, quality and manual production UI acceptance remain outstanding.
