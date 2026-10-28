# Structural and overlapping knowledge chunks

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](knowledge-splitting.md) · [Sync entries](knowledge-sync-entries.en.md) · [Raw archives](knowledge-archives.en.md)

`KnowledgeSpanSplitter` is a pure no-I/O protocol; `StructureKnowledgeSpanSplitter` is its paragraph/sentence heuristic template. It preserves source text and calls no model, embedding, network or tokenizer service. This is structural splitting, not embedding-based semantic understanding or a claim of improved retrieval quality.

## Usage and bounds

```python
from w_agent.knowledge_splitters import StructureKnowledgeSpanSplitter
from w_agent.knowledge_provenance import prepare_traced_knowledge_import

splitter = StructureKnowledgeSpanSplitter(max_chunk_bytes=4096, overlap_chars=128)
spans = splitter.split_spans(text)
chunks = splitter.split(text)  # Existing KnowledgeTextSplitter adapter; spans are authoritative.

trace = prepare_traced_knowledge_import(
    "manual", "v2", imported,
    chunk_bytes=4096, splitter="structure", overlap_chars=128,
)
```

`KnowledgeTextSpan` contains half-open `[char_start,char_end)` and `[byte_start,byte_end)` offsets into original extracted text: Unicode characters and UTF-8 bytes respectively. These are not tokens, graphemes, PDF page coordinates or original Office/PDF binary offsets. Chinese/emoji remain valid UTF-8, although combining-character/ZWJ sequences may cross chunks.

Each window first establishes a strict UTF-8 limit. In its latter half, the template prefers the last paragraph blank-line ending, then the last sentence ending, otherwise a complete-character hard boundary. A remaining suffix already within the limit is kept intact. English sentence endings use `.?!` followed by whitespace/line end; Chinese uses `。！？`. Abbreviations, code, tables and unpunctuated languages receive no semantic interpretation. Whitespace is preserved, not normalized; whitespace-only output chunks are skipped, while all non-whitespace source characters remain covered.

The next window overlaps by at most `overlap_chars` Unicode characters, shortened where needed for progress. Integer-only parameters (not bool): `4 <= chunk_bytes <= 1 MiB`, `0 <= overlap_chars <= min(1024, chunk_bytes // 8)`. This conservative half-window rule reserves room for worst-case four-byte characters, so small windows cannot request large ASCII overlap. Both starts and ends strictly advance without loops/reordering. Each source is bounded to 1 MiB/1024 chunks; the whole trace retains the existing 1024-chunk and 16 MiB output-plus-metadata bounds. Excess fails instead of truncating silently. Repeated source text uses explicit spans, not substring search.

Hosts may replace `KnowledgeSpanSplitter` in pure composition; the template also implements existing `KnowledgeTextSplitter.split`. Persistent traces currently admit only the deterministic built-in `utf8`/`structure` strategies. Archives never load arbitrary Python/splitter plugins. Persistent codecs/registration for custom span splitters remain a separate explicit extension.

## Versions and stable identities

Default `splitter="utf8", overlap_chars=0` retains the original non-overlap chain and `wagent-traced-knowledge-import-v1`: canonical bytes/digest, snapshot IDs and `wagent-knowledge-sync-point-v1` remain unchanged. Legacy UTF-8 mode rejects nonzero overlap.

Structural mode emits `wagent-traced-knowledge-import-v2` with a strict `splitting` object: `algorithm="structure-v1"`, `chunk_bytes`, `overlap_chars`. Loading verifies the digest, field set, exact text slices, character/byte offsets, limits and progress, then regenerates the entire snapshot/origins using the built-in algorithm and compares canonical serialization. Rehashing a tampered strategy, offset, configuration or chunk does not bypass validation.

Both v2 snapshot chunk IDs and sync `point-v2` identities bind full splitting configuration and source spans. Changing strategy/overlap cannot wrongly reuse vectors even when chunk text happens to be identical. Changing only the snapshot version with the same source/configuration preserves stable sync IDs and permits explicitly approved vector reuse. A strategy change may legitimately re-embed all affected files and delete their prior IDs; it is a configuration change, not fake version-only incremental work. Existing snapshots/indexes are not automatically migrated.

Trace stores, sync indexes/plans and raw archives need no SQLite schema changes: they consume strict v1/v2 `TracedKnowledgeImport.from_json/to_json`. Raw archives still bind the exact trace digest and store original bytes, not expanded overlapping chunks as originals.

## CLI, TUI and management

`KnowledgeSyncImportRequest` appends `splitter="utf8"` and `overlap_chars=0`, preserving existing positional arguments. CLI example (reuse existing preview/save approval flow):

```text
python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v2 --trace-database ./data/traces.db --chunk-bytes 4096 --splitter structure --overlap-chars 128 --confirm-read
```

Add explicit `--document-formats` for PDF/Office; structural splitting applies to extracted text. TUI fields “Splitter: utf8 or structure” and “Structure overlap characters” default to `utf8`/`0`, never selecting a strategy or authorizing reads automatically. Preview digests bind every splitting option; changed strategy/options/source require renewed review. Default v1 preview hashing remains unchanged.

Management performs CPU splitting in a worker rather than blocking the TUI loop. Cancellation drains the started worker, then propagates without proceeding to trace creation/save; it does not forcibly terminate a thread. Existing SQLite/remote cancellation boundaries still do not promise rollback.

## Current evidence and remaining scope

2026-10-01, existing clean Python 3.11: 40 new `tests/test_knowledge_splitting.py` cases and one `tests/test_knowledge_splitting_tui.py` case, together with related import/sync/management/raw-archive/four-format/TUI tests: **137 passed** (17.45s, no skips). Six changed modules passed compileall. Coverage includes reference legacy v1 bytes/IDs, strict v2 reconstruction, repeated text/Chinese/emoji, overlap/expansion bounds, identical text with different configurations, preview locks, canceled workers not saving, actual CLI/TUI v2 persistence/reopening, version-only zero repeated embedding and raw-archive roundtrips. The parent records final merged evidence; do not add overlapping totals.

No external model/paid service, installation, release or full-suite run occurred. Semantic-model splitting, multilingual syntax, quality gains, manual live-service UI and persistent custom-splitter codecs remain unaccepted/unprovided.
