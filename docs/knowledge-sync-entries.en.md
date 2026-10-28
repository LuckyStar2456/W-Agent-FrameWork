# Shared knowledge-sync CLI / TUI entries

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](knowledge-sync-entries.md) · [Core synchronization and persistence](knowledge-sync.en.md)

`knowledge_sync_management` supplies immutable requests and async services shared by CLI and TUI. The usable chain is UTF-8 file preview, digest-locked trace persistence, incremental embedding and durable exact-plan preparation, inspection, and independently approved execution. Preparation never upserts/deletes; inspection never imports host code.

## Runnable path

Run `python -m w_agent.cli` from the repository, or installed `wagent`. Create and protect your data directory yourself; parents are not created automatically. Replace digest placeholders with actual reviewed output. Trace and journal databases are separate dedicated stores, not existing snapshot databases.

```text
python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v1 --trace-database ./data/traces.db --confirm-read

python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v1 --trace-database ./data/traces.db --confirm-read --expected-preview-digest PREVIEW_DIGEST --confirm-record --confirm-create

python -m w_agent.cli knowledge-sync-prepare --host-entry examples.knowledge_sync_host:sync_catalog --binding prepare --trace-database ./data/traces.db --namespace manual --version v1 --expected-trace-digest TRACE_DIGEST --journal-database ./data/sync.db --confirm-code --confirm-read --confirm-embedding --confirm-record --confirm-create

python -m w_agent.cli knowledge-sync-inspect --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --confirm-read

python -m w_agent.cli knowledge-sync-execute --host-entry examples.knowledge_sync_host:sync_catalog --binding execute --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --approved-plan-digest PLAN_DIGEST --approved-upsert-digest UPSERT_DIGEST --confirm-code --confirm-read --confirm-record
```

Review and configure `examples/knowledge_sync_host.py`, a local Ollama/Qdrant assembly template. Replace its model placeholder, dimensions and preprocessing revision with actual configuration. The collection must already exist and be exclusive to this sync lineage. Importing the example does not start services, download models or create collections; these commands are not evidence of live-service acceptance.

The default remains existing UTF-8 text suffixes. Explicit `--document-formats` selects the existing `OptionalDocumentKnowledgeParser`, adding PDF/DOCX/XLSX/PPTX. The TUI has an equivalent initially unchecked option. Dependencies load only for the selected format; missing dependencies fail without installation or binary-as-text fallback. No macros, formula evaluation, OCR or remote-link execution; parsing is in-process and intended for trusted files. Parser selection, key, limits and suffixes enter the preview digest: changing them requires a new review. The updated digest invalidates old transient previews, not persisted traces/plans.

Directory scanning is nonrecursive unless `--recursive` is supplied; repeat `--path` for multiple selections. No path explicitly selects an empty manifest, useful for removing all previous owned points; it does not scan the working directory. Traces retain extracted text/offsets. Original binaries use the separately authorized [raw-source archive API](knowledge-archives.en.md); import/sync entries do not archive automatically.

The preview digest binds exact trace content, namespace/version/chunking, root, selected paths, recursion and destination. Saving re-reads files and rejects a changed digest before creating/writing storage. The resulting `trace_digest` must be supplied explicitly for preparation.

For the next version, import again and add `--previous-plan-digest PREVIOUS_PLAN_DIGEST --approved-reuse-digest PREVIOUS_CURRENT_INDEX_DIGEST` to prepare. The previous plan must be complete. Stable source identity and matching embedding configuration reuse vectors; version-only changes do not re-embed everything. Fully cached preparation may omit `--confirm-embedding`, but still needs authorized host loading and exact cache-reuse approval. Deletion includes only IDs owned by the preceding manifest.

## Independent approvals and durable state

| Operation | Required approval | Effects |
| --- | --- | --- |
| Import preview | read | Reads selected files |
| Import save | read, record, exact preview digest; create separately | Persists plaintext local trace |
| Prepare | code, read, record, exact trace digest; embedding for new vectors, create separately | May incur embedding charges; persists/reserves exact plan |
| Inspect | read | Read-only, no host import |
| Execute | code, read, record, exact plan digest; separate upsert/delete digests where needed | Sends saved vectors/exact deleted IDs with durable per-batch receipts |
| Retry-not-sent | read, record, exact retry digest | Preserves failed generation; admits a new ready generation without sending |
| Reconcile | read, record, exact plan digest, applied, inactive, evidence reference | Records host-attested completion; no remote query/reset/replay |

`--approved-upsert-digest` and `--approved-delete-digest` are themselves separate exact remote-action approvals. Add `--approved-delete-digest DELETE_DIGEST` when deletion is present; overall plan approval is insufficient. Deletes remove the whole point, including all named vectors/payload. Never share the collection. An empty plan advances the local head during explicitly approved prepare/record, without sending. `finished` describes local plan completion, not independent remote verification.

Preparation validates the trace, database and predecessor before loading the factory, then checks the target head before embedding. Known conflicts cannot re-bill embedding. This read-only check is not a lease: another caller may win the final stage CAS after embedding has already incurred charges. Failed/canceled preparation has no automatic embedding-checkpoint recovery; do not blindly repeat it. Continue an already staged plan with inspect/execute, not prepare. Plans, traces and vectors are plaintext. UI Clear clears presentation only; deleting a plan to unlock its target is unsafe.

## Explicit recovery

Inspect offers `retry_candidates` only for definite `not-sent`, including batch, failed generation (initially 0), and `retry_digest`. After review, supply those values manually:

```text
python -m w_agent.cli knowledge-sync-retry-not-sent --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --batch 0 --generation 0 --retry-id retry-1 --approved-retry-digest RETRY_DIGEST --confirm-read --confirm-record
```

Executing afterwards still requires all separate approvals. Old generations are preserved, retry IDs cannot repeat, and the whole plan permits at most 64 retries. Exhaustion does not break inspection: it returns `retry_exhausted: true`. Pending/unknown/acknowledged states never produce retry candidates, replay on repeated execute, or advance the head.

Only after independent host verification that effects were applied and the original operation is inactive with late effects drained may you use `knowledge-sync-reconcile --journal-database ... --plan-digest ... --approved-plan-digest ... --batch ... --evidence-ref ... --confirm-read --confirm-record --confirm-applied --confirm-inactive`. This records a host statement, not authenticated evidence. Never falsely claim completion to unlock a target. Unknown-but-not-applied reset/abandonment remains unsupported.

## Management API and lifecycle

`KnowledgeSyncImportRequest/PrepareRequest/InspectRequest/ExecuteRequest/RetryRequest/ReconcileRequest` map to `import/prepare/inspect/execute/retry/reconcile_local_knowledge_sync`. Pure `knowledge_sync_summary(plan,status)` exposes digests, namespace/version, counts and batch actions/status; never bodies, vectors, source paths, URLs, model keys, operation IDs or evidence references.

Hosts reuse `KnowledgeIndexHostOptions`, `KnowledgeIndexHostBinding`, and `knowledge_index_host_scope`. Explicit `confirm_code` permits importing `module:factory`; the factory returns an async context with named bindings. Preparation requires an embedder/revision/dimensions binding; execution may borrow a writer-only binding. The factory owns cleanup. Cleanup never suppresses cancellation/action failures, and cleanup failure can follow a successful remote write; inspect durable receipts first. Trusted host code is not sandboxed; arbitrary factory side effects remain the operator's responsibility.

TUI delegates to these same services, consuming one-time confirmation phrases and manually supplied approval digests rather than automatically approving preview output. Recovery is initially exposed through CLI; there is no automatic retry. Every participant must share one journal. Canonical endpoints do not identify actual DNS aliases/proxy equivalence or constrain unrelated writers; this is not a global/remote lock.

## Evidence and remaining boundaries

On 2026-10-01, existing clean Python 3.11 environment, `python -m pytest -q tests/test_knowledge_sync_management.py tests/test_knowledge_sync_cli.py tests/test_knowledge_sync.py`: **55 passed** (management 16, CLI 8, core 31). Real temporary SQLite and injected transports cover preview locks, the incremental chain, independent deletion approval, duplicate-prepare preflight, generation-0 retry/64-retry exhaustion, unknown/ack barriers, cancellation cleanup, target mismatch, and receipts surviving cleanup failure. Do not add overlapping regression counts or reuse previous full-suite totals as proof of these new entries.

The subsequent format/archive round adds real PDF/DOCX/XLSX/PPTX trace and raw-byte roundtrips plus explicit DOCX CLI/TUI coverage. Its merged evidence is reported by the parent task; the earlier 55 tests do not prove these additions. Live Ollama/Qdrant, cost/quality evaluation, manual interactive UI and remote coordination remain unaccepted here. This CLI does not provide semantic splitting or archive operation commands; archival is a separate replaceable Python API without automatic restore/overwrite capability.
