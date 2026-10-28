# Knowledge preparation recovery and coordination boundaries

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-build-recovery.md)

2.0.0 Experimental, included in 2.0.0. Local SQLite, fake embedding/HTTP and CLI/TUI regressions exercise recovery boundaries; they do not establish real billing, remote index state or production acceptance.

## Recoverable batch preparation

`prepare_recoverable_knowledge_plan()` uses the replaceable `KnowledgePreparationStore` capability, implemented by `SQLiteKnowledgePreparationStore`. Batch identity binds the exact manifest, document order, point IDs and input byte count. The manifest binds snapshot digest, embedding revision/dimensions and target. A different identity cannot reuse a checkpoint.

The sequence is: reserve pending in a transaction → embed one batch → persist ready with the exact vector artifact → idempotently stage that artifact. Construction has no I/O; initialize requires explicit consent and an existing parent directory. The checkpoint database must be separate from source, plan, build and receipt databases.

| Persisted state | Next call |
| --- | --- |
| No record | Requires explicit `confirm_embedding=True` to reserve and embed |
| pending | Refuses replay; work may be running or already billed before interruption |
| ready | Verifies snapshot/target/point order/artifact and stages identical vectors without embedding |
| abandoned | Retains evidence and the old attempt; a new ID plus renewed embedding consent can prepare again |

A failed plan save leaves a ready checkpoint recoverable after restart. A crash between the provider result and ready commit leaves pending: missing local results cannot prove no billing. Checkpoints are per batch; individual partial vectors inside a failed batch are not retained. Hosts can partition smaller batches with `plan_missing_knowledge_batches()` and explicitly call preparation for each selected batch.

```powershell
wagent knowledge-plan-prepare --host-entry examples.knowledge_index_host:index_catalog --binding prepare --source-database .wagent/knowledge.sqlite3 --namespace support --version v1 --plan-database .wagent/knowledge-plans.sqlite3 --document-ids '["doc-a"]' --preparation-database .wagent/knowledge-preparation.sqlite3 --preparation-attempt-id prepare-001 --confirm-code --confirm-read --confirm-embedding --confirm-save --confirm-create

wagent knowledge-preparation-list --database .wagent/knowledge-preparation.sqlite3 --confirm-read
```

When a preparation database is supplied, `--confirm-create` permits initialization of both plan and checkpoint stores. Recovery still requires code/read/save consent. For ready recovery, omit `--confirm-embedding`: absence of a ready checkpoint then fails without new embedding. The host must still provide matching model labels, dimensions and writer configuration; loading trusted host code can have host-defined side effects.

## Explicit uncertain-attempt retirement

Hosts first stop/drain the worker and inspect independent evidence. Inactivity confirmation on `abandon()` is a host assertion, not a remote probe or billing refund. Pending never expires automatically. Late complete calls from retired attempts fail.

```powershell
wagent knowledge-preparation-abandon --database .wagent/knowledge-preparation.sqlite3 --batch-digest <catalog-batch-digest> --attempt-id prepare-001 --evidence-ref <host-shutdown-review-reference> --confirm-inactive --confirm-write
# To prepare again, use a new attempt ID and explicit --confirm-embedding.
```

Retirement does not embed, send remote writes or automatically retry. Concurrent begin calls in the same database allow only one active attempt. Ready also prevents new preparation; recover it instead. Bounds are 1024 attempts and 256 MiB aggregate artifact payload, with the existing 32 MiB artifact/value limits per artifact; these are not disk/process-memory quotas. Checkpoints retain sensitive vectors and plaintext evidence references, not credentials, source bodies or an exact billing ledger. Hosts protect the database and directory.

## Builds and remote writes

Assemble complete disjoint staged batches into `KnowledgeIndexBuild`, then explicitly authorize batches through the [build entry](./knowledge-builds.en.md). Build and journal catalogs discover names, versions and manifests. Stable retry chains allow only not-sent or independently reconciled not-applied. Exclusive begin in a shared journal blocks unresolved overlaps on the same target.

Coordination covers callers using these entries and the same SQLite file and exact target strings. Other databases, URL aliases and external services need host coordination. Local completion continues to report `remote_state_verified=False`.

Local checks: `py -3.11 -m pytest tests/test_knowledge_build_lifecycle.py tests/test_knowledge_builds.py tests/test_knowledge_plan_actions.py -q`. Regressions cover cross-connection races, uncertain no-replay, reviewed retries, zero-embedding recovery after staging failure, explicit retirement and rejected late commits. No paid service is called.
