# Explicit local raw-archive management

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](knowledge-archive-entries.md)

Workspace implementation, not released. This is a local developer API/CLI, not a service. It reuses the immutable trace store and the [raw archive](knowledge-archives.en.md) contract; no embedding, model, parser, external code import, network call, execution, directory restoration or garbage collection is triggered.

## Four separately authorized operations

`knowledge-archive preview` selects an **already saved** namespace/version from a trace database. It reads the trace and returns its SHA-256 digest plus source/blob/byte/chunk counts. It does not read source files or create an archive. Namespace labels, source names, absolute paths and extracted/raw content are not printed.

```powershell
wagent knowledge-archive preview --trace-database traces.db --namespace manual --version v1 --confirm-read
```

Review the counts and digest against your trusted import. `save` requires that independently approved digest, separate database-read/source-file-read/write confirmations, and an explicit source root. `--confirm-create` optionally initializes a dedicated archive database; its parent directory must already exist. Without it the archive must already exist. The trace and archive databases cannot be the same file, including hard-link aliases. Existing unrelated databases are not adopted.

```powershell
wagent knowledge-archive save --trace-database traces.db --archive-database raw.db --root ./sources --namespace manual --version v1 --expected-trace-digest <preview-trace-digest> --confirm-read --confirm-sources --confirm-write --confirm-create
```

The selected saved trace is validated before source reads. All manifest-selected raw files must still match their saved lengths/hashes before the archive is initialized or written. Identical bytes are deduplicated by content hash. No directory scanning or path expansion occurs beyond the saved manifest. An empty manifest is valid and produces an empty receipt. The SQLite archive commits the receipt and blobs atomically, but no transaction spans the import database and the filesystem. An interrupted commit can have completed; inspect before retrying.

`inspect` opens the archive read-only, validates the receipt and every referenced blob hash, and prints only trace/receipt/blob digests and counts. Missing databases are not created. This does read stored raw bytes internally to verify hashes, but it does not export them.

```powershell
wagent knowledge-archive inspect --archive-database raw.db --trace-digest <trace-digest> --confirm-read
```

`export` selects **one blob** from the approved receipt and writes the original bytes to one explicitly named **new file**. It independently requires read, export and path confirmations. Receipt membership, the approved receipt digest and the raw content hash are checked before writing. No directory is created; there is no overwrite, directory restore, file opening or execution.

```powershell
wagent knowledge-archive export --archive-database raw.db --trace-digest <trace-digest> --expected-receipt-digest <receipt-digest> --blob-digest <selected-blob-digest> --destination ./review/original.bin --confirm-read --confirm-export --confirm-path
```

The output contains digests and byte count, never raw bytes or the destination path. Existing files, database paths, symbolic links, Windows reparse points/junctions and linked ancestors are rejected. Exclusive file creation prevents truncating a file created after preflight. On a partial-write failure, cleanup removes only the file whose device/inode identity still matches this operation; a user replacement is not deleted. If identity cannot be proven or cleanup fails, a partial file may remain. The error explicitly asks for inspection. Cancellation drains an already-started worker and may leave a successfully exported file.

## Management API and extension boundaries

`w_agent.knowledge_archive_management` provides:

- `KnowledgeArchivePreviewRequest` → `preview_local_knowledge_archive`.
- `KnowledgeArchiveCreateRequest` → `archive_local_knowledge_sources`.
- `KnowledgeArchiveInspectRequest` → `inspect_local_knowledge_archive`.
- `KnowledgeArchiveExportRequest` → `export_local_knowledge_blob`.

All services are async. Required flags are exact booleans and checked before filesystem/database access. Request representations omit paths and namespace labels. Services return safe dictionaries rather than traces or byte payloads. `register_knowledge_archive_commands(app)` in `w_agent.knowledge_archive_cli` registers the Typer subgroup. No automatic configuration, global singleton or plugin loading is involved.

This management template deliberately uses the existing SQLite stores. Applications needing another store can compose the replaceable `KnowledgeRawArchive`/`KnowledgeImportStore` protocols and `archive_knowledge_sources`; no new persistence format is imposed. Exact trace validation uses the existing `to_json`/`from_json` contract, so the management layer does not reconstruct or assume a chunk-offset layout. SQLite capacities and raw-file/batch limits remain those of the underlying archive.

## Security and remaining scope

The databases and exported bytes are **plaintext**, potentially containing credentials, personal information, document macros, executables or malicious payloads. Export does not sanitize or disinfect them; never auto-open exported files. Hashes provide integrity, not authenticity, confidentiality or authorization; known-content hashes can also reveal membership. Restrict access to both databases, SQLite sidecars, source roots and output directories. New files request POSIX mode `0600`; Windows ACLs remain host-managed.

All paths and ancestors must be trusted and quiescent. Link/reparse checks and identity-aware cleanup are not a sandbox or protection against a malicious process racing directory replacement. No automatic ACL hardening, encryption, retention/GC, bulk restoration, cross-filesystem transaction or background retry is implemented. Inspect failures before deciding on another operation.

Related verification: `python -m pytest tests/test_knowledge_archive_entries.py tests/test_knowledge_archives.py -q` — **42 passed**, including 28 new management/CLI tests. Coverage uses real temporary SQLite and byte-exact exports, same-file/hard-link rejection, Windows junction rejection, missing-confirmation no-I/O gates, approval/source drift, corruption, partial-write cleanup, and preservation of a concurrent replacement. No skipped tests, external services or installations in this run.
