# Raw knowledge-source archives

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](knowledge-archives.md) · [Sync entries](knowledge-sync-entries.en.md) · [Archive management CLI](knowledge-archive-entries.en.md)

`knowledge_archives` provides replaceable `KnowledgeRawArchive` and local `SQLiteKnowledgeRawArchive`. It stores original bytes separately from extracted-text traces and does not alter index identity. Nothing reads sources, creates storage, archives or restores/overwrites files automatically.

## Explicit workflow

`wagent knowledge-archive preview/save/inspect/export` now reviews an already-saved namespace/version, separately confirms original-file reads and archive writes, checks receipts read-only, and exports one raw blob. Export writes only one explicitly selected new file: no overwrite, link following or automatic execution. **Single-file export is not directory restoration.** See [archive management entries](knowledge-archive-entries.en.md) for the API, independent permissions and failure cleanup boundaries. The example below remains the replaceable low-level protocol.

First save/review a trace through the sync entry and load it with `SQLiteKnowledgeImportStore.load(namespace,version)`. Approval must identify the independently reviewed version: do not automatically treat the loaded `trace.digest` as permission.

```python
from pathlib import Path
from w_agent.knowledge_archives import SQLiteKnowledgeRawArchive, archive_knowledge_sources

# Run only after separate local-database creation approval; parent must exist.
archive = SQLiteKnowledgeRawArchive(Path("data/raw-archive.sqlite3"))
await archive.initialize(confirm_create=True)

# trace is a loaded/validated TracedKnowledgeImport.
# approved_trace_digest comes from independent host review, not auto-approval.
receipt = await archive_knowledge_sources(
    trace, Path("manual"), archive,
    expected_trace_digest=approved_trace_digest,
    confirm_read=True, confirm_write=True,
)

# Complete in-memory bytes, at most 1 MiB; never interpreted or executed.
saved = await archive.receipt(approved_trace_digest, confirm_read=True)
raw = await archive.load(saved.blob_digests[0], confirm_read=True)
```

The helper roundtrip-validates the entire trace against the exact approved digest, then reads every manifest source. It reuses importer path/link restrictions: no traversal, linked/reparse sources or nonregular files; opening/stat stamps, byte counts and raw SHA-256 must match. All source bytes pass before `archive.save` is called. Any drift, missing source or limit failure prevents the entire storage call. Protect the source tree: this is not a filesystem sandbox against hostile concurrent ancestor replacement.

Identical bytes are deduplicated by raw SHA-256. `KnowledgeArchiveReceipt` binds the exact trace digest to sorted unique blob digests; the trace retains path→raw digest/size mapping. A versioned receipt checksum is persisted; reopening validates its association and each blob. Receipts expose no source paths, and the host must retain the corresponding trace. Low-level `save(receipt,blobs)` is a trusted-host API: a hand-constructed receipt is a host assertion, not source authentication. Prefer the complete-source-validation helper above.

## Storage, replacement and authorization

- `save` accepts a validated batch and receipt; `load`/`receipt` require `confirm_read=True`, writes independently require `confirm_write=True`. Construction performs no I/O; initialization separately requires `confirm_create=True`. Missing-database reads do not create files.
- SQLite has a dedicated application_id, user_version 1, three-table schema. No adoption of other knowledge databases, migration or overwrite. Exact existing saves are idempotent; conflicting associations for the same trace are refused.
- At most 1 MiB/blob and 1024 files/16 MiB/source batch. Defaults: 4096 unique blobs, 1024 traces, 512 MiB logical payload. Capacity checks and blob/association insertion share one transaction, preventing partial batches. Logical bounds are not physical SQLite/WAL disk or parser resource quotas.
- Replacement stores own their durability, atomicity and permissions; the helper verifies the returned receipt matches exactly. There is no transaction across trace/sync/raw stores or rollback of earlier imports/model charges.
- Raw bytes are plaintext and can include macros, sensitive metadata, hidden sheets or unextracted information. Low-level archiving does not decompress, parse, import optional dependencies, request networks, write out source files or restore originals. Separately authorized management export can write one new file whose bytes may be executable or contain macros; it never opens/executes that file. Subsequent interpretation by other host software requires separate authorization and safeguards.
- Cancellation drains started file/SQLite workers and may follow a committed write. SHA-256 provides integrity, not authentication/signatures or protection from malicious administrators. Hosts protect files/directories/SQLite permissions. No deletion/GC, cloud template, retention policy or automatic archive synchronization is included.

## Low-level archive increment evidence

Newer management API/CLI acceptance is recorded in [archive management entries](knowledge-archive-entries.en.md); do not add it to the overlapping low-level test set below.

2026-10-01, existing clean Python 3.11, targeted `tests/test_knowledge_archives.py tests/test_knowledge_sync_formats.py tests/test_knowledge_sync_management.py tests/test_knowledge_sync_cli.py tests/test_tui_knowledge_sync.py`: **58 passed** (11.74s, no skips). Includes real local PDF/DOCX/XLSX/PPTX→trace→byte-identical raw archives, DOCX CLI/TUI opt-in, parser/configuration/source drift locks, deduplication/reopening, independent consent, atomic capacity refusal, corruption rejection, empty versions, mismatched custom receipts, nonregular sources and unrelated-database rejection. Four changed modules also passed compileall. Do not add overlapping or earlier-round totals. Final merged targeted evidence belongs to the parent task. No live external service, cost/quality acceptance, dependency installation or release.
