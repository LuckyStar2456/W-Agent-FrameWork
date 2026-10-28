# Local knowledge management

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-management.md)

2.0.0 Experimental, included in 2.0.0 and outside 2.0.0a9. On 2026-10-01, initial ingestion regressions returned 102 passed / 5 skipped, including management, CLI, existing TUI regressions and real DOCX import/save/search; this is not manual GUI acceptance. New `--document-formats` and `--expected-preview-digest` options are documented in [import extensions](./knowledge-import-extensions.en.md).

## Scope and extension points

`LocalKnowledgeRequest` captures one operation; `manage_local_knowledge(request)` is the shared CLI/TUI local template, not a service. It defaults to UTF-8 `.txt`/`.md` ingestion and can explicitly enable optional PDF/Office parsers, followed by UTF-8 splitting, immutable SQLite snapshots and local keyword retrieval. It loads no host factories, calls no model/embedding service, changes no remote index and never rewrites Runtime configuration.

Underlying importers, splitters, stores and retrievers remain replaceable; this convenience entry currently selects built-ins. Optional `KnowledgeSnapshotCatalog` and `KnowledgeSnapshotInfo` extend discovery without requiring existing `KnowledgeSnapshotStore` plugins to add methods.

## CLI

```powershell
# Read and preview only; never open/create the database
wagent knowledge-import --database .wagent/knowledge.sqlite3 --root ./manuals --path faq.md --namespace support --version draft-1 --confirm-read

# Reread sources, prepare and persist; parent directory must already exist
wagent knowledge-import --database .wagent/knowledge.sqlite3 --root ./manuals --path faq.md --namespace support --version draft-1 --confirm-read --confirm-write --confirm-create

wagent knowledge-list --database .wagent/knowledge.sqlite3 --namespace support --confirm-read
wagent knowledge-search --database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --query refund --confirm-read
# Add --include-text to disclose matched bodies
```

- Repeat `--path` with POSIX-relative selections. Explicit `--path .` selects the root; recursive traversal additionally needs `--recursive`. Hidden entries are off by default; links/reparse points are rejected. This is not filesystem isolation.
- Every operation requires `--confirm-read`. Import returns counts, version and digests, never bodies; it does not persist the import manifest.
- Only `--confirm-write` saves; `--confirm-create` additionally requires write consent. Without creation consent only an existing database may be opened. No implicit parent creation. Same-content versions are idempotent; conflicts never overwrite.
- Preview and save reread sources independently: this is not a digest-locked preview/commit protocol. Sources may change; inspect the final digest. An import-manifest digest does not mean that manifest was archived.
- Catalog entries are sorted lexically by namespace/version, bounded to 4096 with failure rather than silent truncation. No implicit latest version. `body_integrity_verified=false` means stored digest/size declarations only, not body verification or source authentication.
- Search requires exact namespace/version/query and validates canonical serialization and digest when loading. Default output includes matching IDs, sources and titles; `--include-text` discloses bodies. Read consent permits reading bodies for retrieval; display consent separately governs output. Titles/sources/labels can also be sensitive.
- JSON escapes non-ASCII/control characters to prevent terminal control sequences. Failures omit raw file/database exception details and bodies. Cancellation/failure may follow a completed write: inspect the exact version before retrying. Creation and save are not one atomic transaction.

Inherited defaults: 128 files, 1 MiB per file, 16 MiB each for total raw/parsed text; 4096 UTF-8 bytes per chunk (`--chunk-bytes`), at most 1024 snapshot chunks. See [file ingestion](./knowledge-files.en.md) and [snapshots](./knowledge-ingestion.en.md). Use a trusted, stable directory; link checks do not isolate malicious concurrent file replacement.

## TUI

Knowledge provides database, namespace, exact version, import root, relative-path JSON array, chunk size, query and result-limit fields.

Enter `READ KNOWLEDGE` per operation; saving requires `WRITE KNOWLEDGE`, creation additionally `CREATE KNOWLEDGE`, and body display `SHOW TEXT`. Confirmations are consumed on capture; incorrect words reject the request. Import/preview, catalog and pinned-search buttons use the shared API. Nothing loads automatically on mount. Relative database/root paths use the TUI workspace; CLI paths use its invocation directory.

Captured requests lock the fields and run in a background coroutine. Cancellation/unmount drains started storage/file threads without claiming rollback of committed writes. Cancellation tells the user to inspect the version. Results remain in the panel, without an automatic log; terminal history/screenshots remain the user's responsibility. TUI layout and interaction have not been accepted this round.

## Agent assembly

Management and [Run knowledge context](./knowledge-runtime.en.md) are separate entries. A trusted host factory still explicitly calls `await SQLiteKnowledgeSnapshotStore(path).load(namespace, version)` and wraps `KeywordKnowledgeRetriever(snapshot.as_document_store())` in `LocalKnowledgeBinding`. Management never loads `.env` or Python factories, selects a version for a Run or sends bodies to a model automatically.

## Progress and remaining work

Local management API/CLI and headless TUI regressions pass. [Import extensions](./knowledge-import-extensions.en.md) implement optional PDF/Office parsing, incremental parsing reuse, extracted originals/offsets and digest-locked commits. [Build recovery](./knowledge-build-recovery.en.md) and hybrid/Workflow/evaluation APIs are separate modules. Remaining: raw binary archival storage, automatic trace/cache persistence, vector differential synchronization, unified preparation accounting, real retrieval quality and manual production UI acceptance.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
