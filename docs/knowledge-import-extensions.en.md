# Optional parsers, traceable imports and preview commit locks

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-import-extensions.md)

2.0.0 Experimental, included in 2.0.0. Initial ingestion regressions on 2026-10-01 were **102 passed / 5 skipped**. The user then approved installing pypdf 6.19.0, openpyxl 3.1.5 and python-pptx 1.0.2 in a dedicated virtual environment, reusing python-docx 1.2.0. Extension tests reran with **15 passed, no skips**. Real DOCX paragraphs/tables passed extraction → preview → digest-locked SQLite save → search. A real PDF verified nonempty text extraction; XLSX/PPTX verified cell/slide text. Two older Windows symlink/FIFO cases retain platform limitations. No model/paid call, remote write or release; see the [unified acceptance record](./acceptance-2026-10-01.en.md).

## Explicit parser selection

A later increment adds replaceable SQLite trace persistence, exact vector-cache reuse and file-level incremental upsert/delete; see [knowledge sync](./knowledge-sync.en.md) and its [CLI/TUI entries](./knowledge-sync-entries.en.md). [Raw binary archives](./knowledge-archives.en.md) provide independently authorized storage. Ordinary snapshot imports do not archive automatically or migrate snapshot-bound indexes.

Source installations offer the optional `knowledge-documents` extra; core installation does not require document parser libraries. This new extra has not been published in a new PyPI release.

```python
from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_parsers import OptionalDocumentKnowledgeParser

parser = OptionalDocumentKnowledgeParser(parser_key="host-pinned-parsers-v1")
importer = LocalTextKnowledgeImporter(root, parser=parser, suffixes=parser.suffixes)
loaded = await importer.load(("manual.docx",), confirm_read=True)
```

The default importer still accepts only `.txt`/`.md`. The optional template lazily loads pypdf for PDF, python-docx for DOCX, openpyxl for XLSX, and python-pptx for PPTX. DOCX paragraphs/tables follow body order; PDF yields page text; XLSX yields sheet names and cached cell values without evaluating formulas; PPTX yields top-level text frames/tables. There is no OCR, macro execution, link downloading, legacy `.doc/.xls/.ppt` support, or complete header/footer/comment/note fidelity.

Input files remain bounded to 1 MiB; extracted text to 1 MiB; Office ZIPs default to 4096 entries and 32 MiB declared expansion; XLSX traversal to 100000 cells. These are not CPU/memory sandbox limits: parsers and directories remain trusted. Direct parser calls report a fixed `KnowledgeParserDependencyError`; the importer continues to sanitize parser exceptions. Hosts pin dependency versions and change `parser_key` whenever extraction logic/configuration changes.

## Incremental parsing and deltas

`await importer.load(paths, confirm_read=True, previous=loaded)` still reads and hashes every selected file. It reuses nonblank parsed documents only when relative path, raw SHA-256/length, and parser_key match. Blank originals have no retained document and are parsed again. The previous result is trusted host-owned cache data, not authenticated evidence.

`compare_knowledge_imports(previous, current)` returns sorted `added/changed/removed/unchanged` relative paths. Narrowing a selection also reports unselected old paths as removed. This is only a report: no files, snapshots or remote vectors are deleted. It is not a watcher or incremental embedding/index synchronizer.

## Exact provenance and portable originals

```python
from w_agent.knowledge_provenance import TracedKnowledgeImport, prepare_traced_knowledge_import

traced = prepare_traced_knowledge_import("manual", "v1", loaded, chunk_bytes=4096)
snapshot = traced.snapshot
archive_json = traced.to_json()  # Discloses extracted originals; host owns archival permissions.
restored = TracedKnowledgeImport.from_json(archive_json, expected_digest=traced.digest)
```

Each `origins` entry binds a chunk to its original document ID and half-open character/UTF-8 byte offsets in **extracted text**, not PDF/Office binary offsets or layout coordinates. Skipped whitespace remains in the retained original. Export includes file fingerprints, extracted originals, snapshot, chunk configuration and offsets. Import validates canonical JSON, digest, source records, exact slices and recomputed preparation. Existing snapshot JSON/SQLite schema remains unchanged. Default nonoverlapping UTF-8 remains trace v1; explicit `splitter="structure", overlap_chars=...` uses self-validating v2: see [structural/overlap splitting](./knowledge-splitting.en.md), a heuristic rather than semantic model understanding. Trace and raw-binary persistence now have separate explicit entries; automatic archival and cross-storage atomic commits remain absent.

## Digest-locked commit

First run `knowledge-import ... --confirm-read` to obtain a body-free preview. Reuse the same options with `--confirm-write --expected-preview-digest <preview_digest>`; add `--confirm-create` when creation is needed. Add `--document-formats` for optional formats. The TUI exposes the format switch and expected-digest input too.

The lock binds root, selection, recursion/format options, chunk configuration, raw/extracted digests, snapshot/version and destination database path. Drift raises `knowledge-preview-conflict` before database initialization, including raw-only changes such as a BOM. This is not a user signature or process lock, and cannot guarantee the disk source stays unchanged after reading: the saved snapshot is the immutable content read and matched to the preview. Existing one-step confirmed saves remain available and report `preview_locked=False`.

The older `knowledge-import` entry described here returns `preview_digest` and `trace_digest`, with explicit `manifest_persisted=False` and `trace_persisted=False`: that entry stores only snapshot bodies. Use separate `knowledge-sync-import` / sync entries and dedicated databases for durable traces, structural splitting and incremental caches. Do not interpret the older command's limits as missing capabilities across the module; no entry implicitly prints bodies in CLI output.
