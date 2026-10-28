# Local text-file and directory imports

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-files.md)

Status: 2.0.0 `Experimental`, included in 2.0.0 and outside `2.0.0a9`. On 2026-10-01, initial targeted ingestion regressions returned 102 passed / 5 skipped, including real DOCX import, save and search. See [import extensions](./knowledge-import-extensions.en.md) for optional parsers, provenance, incremental parsing reuse and preview commit locks. This base template still defaults to UTF-8; the extension page supersedes historical remaining-work claims below. Optional parser dependencies were subsequently installed with approval in a dedicated temporary project environment; see the extension page for real four-format parser validation. Included in 2.0.0.

## Explicit reads, separate persistence

`KnowledgeFileImporter.load(paths, confirm_read=...)` is a replaceable async protocol. `LocalTextKnowledgeImporter` returns immutable `KnowledgeTextImport` without saving a database, embedding text, writing indexes or executing imported file contents.

```python
from pathlib import Path
from w_agent import (
    LocalTextKnowledgeImporter, SQLiteKnowledgeSnapshotStore,
    Utf8KnowledgeTextSplitter, prepare_knowledge_snapshot,
)

# Host chooses a trusted directory that other processes will not mutate.
importer = LocalTextKnowledgeImporter(Path("my-knowledge"), recursive=True)
loaded = await importer.load(("manuals", "faq.txt"), confirm_read=True)
snapshot = prepare_knowledge_snapshot(
    "support", "local experiment A", loaded.documents,
    splitter=Utf8KnowledgeTextSplitter(max_chunk_bytes=4096),
)

# Separate authorization, not implied by read consent; parent must exist.
store = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
await store.initialize(confirm_create=True)
await store.save(snapshot, confirm_write=True)

# Explicit source serialization for host-managed retention; no file write.
source_manifest = loaded.to_manifest_json()
```

Use [pinned snapshots](./knowledge-ingestion.en.md) or [snapshot vectors](./knowledge-vectors.en.md) afterward. The body database does not also save `loaded.records`; hosts must retain the source manifest and associate it with the snapshot digest. There is no cross-store atomic commit or dedicated manifest repository yet.

## Selection, reads and limits

- Construction only stores an absolute root/configuration without filesystem access. `confirm_read` must be literal True: a host call boundary, not identity authentication, model authorization or a sandbox. Empty selection `()` returns an empty result without probing root.
- Paths are a tuple of at most 1024 unique relative paths using `/`. `.` explicitly selects the root directory. Absolute paths, drives, backslashes, `..`, empty components, wildcards, controls, colons/alternate data streams and trailing dots/spaces are rejected. Spelling is preserved without case/Unicode normalization.
- Default suffixes are `.txt` and `.md`, matched case-insensitively; hosts may configure others. Unmatched files encountered during scanning are skipped; explicitly selected unsupported files fail. Suffix filtering is not content security or secret scanning.
- `recursive=False` scans only the first level of selected directories. Explicitly naming a subdirectory still scans it. `include_hidden=False` skips dot-prefixed/Windows-hidden entries during enumeration and rejects explicitly selected hidden paths. Enabling it can expose sensitive files such as `.env`; hosts must review selection and suffixes.
- Accepted files are sorted by relative path. Overlapping selections of the same relative path read once. Hard links, differently cased spellings and other filesystem aliases are not promised content deduplication.
- Defaults: 128 files, 4096 enumerated entries, 16 directory levels, 1 MiB per file and 16 MiB total raw bytes. Parsed text has corresponding per-file/total byte limits. Configuration ceilings are 1024, 65536, 64, 1 MiB and 16 MiB respectively. Hidden/unmatched entries still consume enumeration allowance. Exceeding limits fails rather than truncates.
- Final documents additionally obey the existing 1024-document and 16 MiB combined ID/body/source/title limits. Blank files count toward file limits; a maximum-sized body may leave insufficient room for metadata. Selected sizes are checked before parsing, then reads use limit-plus-one bounds to detect growth.
- Root/ancestors and selected path components reject symbolic links and Windows reparse points. Only regular files are read, not devices/FIFOs. Where available `O_NOFOLLOW` is used; identity, size and timestamps are compared around opening/reading. Unmatched/non-recursed links may be skipped, never intentionally followed.
- These checks are not race-free cross-platform path isolation. Root, ancestors, files and parser must be trusted and not concurrently replaced. Hard links, mount points, network filesystems and filesystem-capable attackers are outside this isolation boundary. Hosts requiring stronger isolation must use a sandbox.
- The collection is not an atomic filesystem snapshot. Detected changes fail, but no detected change does not prove immutability. Failures return no partial result and do not retry; prior reads or custom-parser side effects cannot be undone.

## Parsing and source identity

`KnowledgeFileTextParser` defines `parser_key` and synchronous `parse(data, relative_path=...) -> str`. Default `Utf8KnowledgeFileParser` strictly decodes UTF-8, removes one leading BOM, preserves CR/LF and other characters, never replaces invalid bytes or executes Markdown/scripts, and rejects NUL. Empty or parsed-whitespace-only files retain source records without producing `KnowledgeDocument` objects.

Hosts may inject parsers and explicitly configure accepted suffixes. `parser_key` is a host version label of up to 128 UTF-8 bytes, not verified implementation identity. Custom parsers are trusted code running in the worker thread: they can block or cause side effects and require host review/isolation. The interface allows PDF/Office extensions; the initial template does not parse those formats.

Each `KnowledgeFileRecord` stores relative path, raw SHA-256/byte count, parsed-text SHA-256/UTF-8 byte count and optional document ID. Deterministic UUIDs bind format, relative path, raw digest, parsed digest and parser_key. Moving the same tree to another root preserves identity; changing path/raw bytes/text/parser label changes it. Source is `local:<relative path>` and title is the filename. Sources are citations, not automatically opened URLs.

`to_manifest_json()` explicitly exposes canonical source records without absolute root, bodies or raw files; `digest` hashes that manifest. Default repr hides bodies/paths; explicit JSON exposes paths/digests. Neither constitutes a signature, anonymization or a secret; low-entropy text may be guessed from digests. Records neither archive originals nor map original-byte offsets to chunks, and cannot recover missing source text.

## Cancellation and remaining work

Reads/parsing run in a worker thread. Cancellation drains started work and closes handles before propagating; blocking filesystems/arbitrary parsers cannot be forcibly stopped. An external timeout is not an immediate-stop guarantee. Fixed `KnowledgeFileImportError` messages omit paths, bodies and parser exception details.

Local regressions pass for authorization, paths, UTF-8/BOM, selection, limits, fingerprints, source changes, parser replacement and cancellation; Windows symlink/FIFO tests retain platform skips. [Import extensions](./knowledge-import-extensions.en.md) provide optional PDF/Office parsing, extracted originals/offsets, incremental parsing reuse and CLI/TUI digest-locked commits. Raw binary archival storage, automatic trace/cache persistence, differential vector synchronization, OCR, semantic splitting and production acceptance remain incomplete.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
