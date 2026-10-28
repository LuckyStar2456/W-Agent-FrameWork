# Pure-text preparation and versioned SQLite knowledge snapshots

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-ingestion.md)

Status: 2.0.0 `Experimental`, included in 2.0.0 and outside `2.0.0a9`. On 2026-10-01, initial targeted ingestion regressions returned 102 passed / 5 skipped, covering temporary SQLite creation, pinned retrieval and real DOCX ingestion. The new [traceable import extension](./knowledge-import-extensions.en.md) retains extracted originals and exact chunk offsets without changing `KnowledgeSnapshot`. That page supersedes historical remaining-work claims below.

## Host text to a pinned version

`prepare_knowledge_snapshot(namespace, version, documents, splitter=...)` accepts a tuple of host-read/parsed `KnowledgeDocument` records and returns an immutable `KnowledgeSnapshot`. Default preparation is local and does not read files, scan directories, download citations, load third-party parsers or call Embedding.

For local text reads, separately opt into the locally regression-tested [file/directory importer](./knowledge-files.en.md), then pass `loaded.documents` here. Preparing or saving a snapshot never implicitly starts an import.

`KnowledgeTextSplitter.split(text)` is a replaceable synchronous protocol. `Utf8KnowledgeTextSplitter(max_chunk_bytes=4096)` splits by UTF-8 byte ceiling without splitting code points, overlapping or normalizing text. Whitespace-only chunks are omitted; other characters within each chunk are preserved. This is not semantic, sentence, grapheme-cluster or token splitting: combining characters/emoji sequences may span chunks. Configure 4 bytes–1 MiB per chunk, with at most 1024 chunks per source document.

```python
from w_agent import (
    KnowledgeDocument, SQLiteKnowledgeSnapshotStore, Utf8KnowledgeTextSplitter,
    KeywordKnowledgeRetriever, knowledge_search_tool, prepare_knowledge_snapshot,
    ToolSideEffect,
)

snapshot = prepare_knowledge_snapshot(
    "support-manual", "experiment A",
    (KnowledgeDocument("refund", "Sample returns window: seven days. Not a real policy.",
                       "sample:refund", "Returns"),),
    splitter=Utf8KnowledgeTextSplitter(max_chunk_bytes=4096),
)

# Hosts precreate the parent directory; construction does not create the database.
versions = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
await versions.initialize(confirm_create=True)
digest = await versions.save(snapshot, confirm_write=True)

# Explicit version after reopening; no automatic latest pointer.
reopened = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
pinned = await reopened.load("support-manual", "experiment A")
documents = pinned.as_document_store()
binding = knowledge_search_tool(
    KeywordKnowledgeRetriever(documents), side_effect=ToolSideEffect.READ,
)
```

Use `binding` through the [knowledge tool](./knowledge-tools.en.md) registry/Runtime path, or pass `KeywordKnowledgeRetriever(documents)` to the [knowledge context policy](./knowledge-context.en.md). The loaded in-memory document set remains pinned when other processes append versions. There is no persistent connection or `aclose()` requirement; each SQLite operation closes its own connection.

## Identity, content and version semantics

- Namespace/version are exact user-chosen labels supporting Unicode, each at most 128 UTF-8 bytes, nonblank and without ASCII control characters. They are not trimmed, normalized, compared as semantic versions or treated as paths; case/space differences matter. Namespace is local grouping, not a tenant, ACL or service-platform boundary.
- Preparation generates UUID strings from the first 128 SHA-256 bits of canonical JSON binding format, namespace/version, original document ID, chunk position/text, source and title. Changing a bound field changes IDs. These IDs fit Qdrant's format but do not imply indexing. Reordering different input documents preserves their chunk IDs but changes the snapshot digest.
- Source/title remain untrusted citations, never opened or authenticated. Prepared documents do not additionally retain parent IDs, byte offsets, splitter implementation versions or complete originals; UUIDs cannot recover them. Hosts can separately retain file-level fingerprints from the local importer. The separate [traceable import extension](./knowledge-import-extensions.en.md) retains extracted originals and exact chunk offsets; raw binary archival storage and automatic manifest persistence remain planned.
- Constructing `KnowledgeSnapshot(namespace, version, documents)` directly preserves host-owned IDs/chunks. It does not generate version-bound IDs: avoid reusing vector-point IDs across versions if that would overwrite another version's index.
- Snapshot fields are immutable and repr hides documents, not labels. `to_json()` explicitly exposes canonical JSON containing full bodies. `digest` hashes this serialization, covering order, types, text and citations. Digests/UUIDs are not signatures, secrets, authorization or anonymization and cannot detect an attacker changing both content and digest.
- Saving identical canonical content under the same namespace/version returns the same digest. Different content raises `knowledge-version-conflict` without overwrite. New content requires an explicit new version name. There is no deletion, automatic migration/merge/overwrite/rollback or latest-version selection.

## Persistence and failure boundaries

`KnowledgeSnapshotStore` defines replaceable async `save(..., confirm_write=...)` / `load(namespace, version)` methods. The SQLite template adds explicit initialization.

- Construction/preparation do not create databases; `initialize(confirm_create=True)` creates or checks a dedicated file. Other applications' databases, unknown application/schema versions and changed table definitions are rejected, not adopted or migrated. Reads use read-only connections; save requires an existing database and creates neither missing databases nor parent directories.
- `confirm_create` and `confirm_write` must be literal boolean True. These are explicit host-call boundaries, not trusted-user signatures or sandboxes; do not derive permission automatically from models/shared-project declarations. SQLite stores plaintext document bodies. Hosts own directory permissions, backups, disk encryption and cleanup.
- `BEGIN IMMEDIATE` keeps conflict checking and insertion in one transaction. Concurrent processes saving different contents to the same version cannot both succeed. External vector indexes do not participate in this transaction; cross-store atomicity is not provided.
- Input batches/snapshots allow at most 1024 documents/chunks, 16 MiB of document fields and 32 MiB of canonical snapshot JSON. Individual bodies retain their 1 MiB ceiling. Custom splitters must return bounded nonempty tuples of nonblank strings; total expansion is bounded. Empty inputs can produce empty snapshots.
- SQLite defaults to at most 1024 snapshots and 256 MiB total payload, configurable through `max_snapshots` (up to 4096) and `max_total_bytes` (up to 2 GiB). These are admission bounds, not physical database/journal/process-memory/token quotas. Identical repeated saves consume no extra version. Reopening with different admission bounds does not delete existing versions.
- Loading bounds payload bytes before checking digest, JSON fields/duplicate keys, document constraints and requested labels. Corruption/mismatch fails without partial documents or storage mutation. Database files and parent directories must still be trusted; this is not an isolated malicious-SQLite-file parser.
- Default `timeout=5` seconds is SQLite's lock-wait setting, not a hard whole-operation deadline. I/O runs in a worker thread; cancellation drains started work and closes the connection before propagating `CancelledError`. It cannot forcibly stop a transaction or imply rollback; commit may already have happened. Process crashes/exits require SQLite/host recovery separately.
- `KnowledgeStoreError.code` is a fixed identifier without paths/bodies. `may_have_written=True` means the write stage was entered without confirmed success; load the version and compare its digest before deciding next steps. Failed initialization can leave an empty file. Cancellation is a separate exception and likewise requires outcome reconciliation. No automatic retry occurs.
- The default splitter and SQLite incur no model charges. Custom synchronous splitters are trusted host code and can block or cause side effects; they are not isolated. Character/byte limits are not token budgets. Later embedding/model calls require separate authorization and metering.

## Progress and remaining work

Pure-text preparation and SQLite snapshot local regressions pass, covering UTF-8, identities, reopen, conflicts/concurrency, capacity, corruption and cancellation.

Local [imports](./knowledge-files.en.md), [snapshot-vector preparation](./knowledge-vectors.en.md) and [receipt journals](./knowledge-index-journal.en.md) have local regression coverage and never run automatically when saving snapshots. [Import extensions](./knowledge-import-extensions.en.md) provide optional PDF/Office parsing, extracted originals/offsets and incremental parsing reuse; management CLI/TUI entries are implemented. Remaining: raw binary archival storage, automatic trace persistence, semantic/overlapping splitters, additional embedding templates, remote evidence/verification, cross-store synchronization and real end-to-end acceptance.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
