"""Pure, portable import deltas and chunk-to-extracted-text provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from uuid import UUID

from w_agent.knowledge_context import KnowledgeDocument
from w_agent.knowledge_files import KnowledgeFileRecord, KnowledgeTextImport, _digest
from w_agent.knowledge_ingestion import KnowledgeSnapshot, Utf8KnowledgeTextSplitter, _json, prepare_knowledge_snapshot
from w_agent.knowledge_sqlite import _decode
from w_agent.knowledge_splitters import StructureKnowledgeSpanSplitter
from w_agent.vector_retrieval import _reject_constant, _unique_object


@dataclass(frozen=True, slots=True)
class KnowledgeImportDelta:
    """Paths relative to the selected tree, not instructions to delete storage."""

    added: tuple[str, ...] = field(repr=False)
    changed: tuple[str, ...] = field(repr=False)
    removed: tuple[str, ...] = field(repr=False)
    unchanged: tuple[str, ...] = field(repr=False)


def compare_knowledge_imports(previous: KnowledgeTextImport, current: KnowledgeTextImport) -> KnowledgeImportDelta:
    """Compare complete selections; a narrower selection counts as removed here."""
    if not isinstance(previous, KnowledgeTextImport) or not isinstance(current, KnowledgeTextImport):
        raise TypeError("knowledge imports are required")
    old = {item.relative_path: item for item in previous.records}
    new = {item.relative_path: item for item in current.records}
    common = old.keys() & new.keys()
    unchanged = {path for path in common if old[path] == new[path] and previous.parser_key == current.parser_key}
    return KnowledgeImportDelta(tuple(sorted(new.keys() - old.keys())), tuple(sorted(common - unchanged)),
                                tuple(sorted(old.keys() - new.keys())), tuple(sorted(unchanged)))


@dataclass(frozen=True, slots=True)
class KnowledgeChunkOrigin:
    """Half-open Unicode character and UTF-8 byte offsets in extracted text."""

    chunk_id: str
    document_id: str
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class TracedKnowledgeImport:
    """Retain extracted originals and validated offsets; no raw binaries or I/O.

    to_json explicitly discloses all original extracted text for host archival.
    Offsets are not PDF page coordinates or offsets into the original file bytes.
    """

    imported: KnowledgeTextImport = field(repr=False)
    snapshot: KnowledgeSnapshot = field(repr=False)
    origins: tuple[KnowledgeChunkOrigin, ...] = field(repr=False)
    chunk_bytes: int = 4096
    splitter: str = "utf8"
    overlap_chars: int = 0

    def __post_init__(self) -> None:
        Utf8KnowledgeTextSplitter(self.chunk_bytes)
        if self.splitter not in {"utf8", "structure"} or type(self.overlap_chars) is not int:
            raise ValueError("invalid knowledge trace splitting configuration")
        if self.splitter == "utf8" and self.overlap_chars != 0:
            raise ValueError("legacy UTF-8 splitting does not support overlap")
        if self.splitter == "structure":
            StructureKnowledgeSpanSplitter(self.chunk_bytes, self.overlap_chars)
        if not isinstance(self.imported, KnowledgeTextImport) or not isinstance(self.snapshot, KnowledgeSnapshot):
            raise ValueError("invalid traced import")
        if not isinstance(self.origins, tuple) or len(self.origins) != len(self.snapshot.documents):
            raise ValueError("invalid knowledge chunk origins")
        sources = {item.document_id: item for item in self.imported.documents}
        requested_positions: dict[str, set[int]] = {}
        for origin in self.origins:
            if (not isinstance(origin, KnowledgeChunkOrigin) or origin.document_id not in sources
                    or type(origin.char_start) is not int or type(origin.char_end) is not int
                    or not 0 <= origin.char_start < origin.char_end <= len(sources[origin.document_id].text)):
                raise ValueError("invalid knowledge chunk origin")
            requested_positions.setdefault(origin.document_id, set()).update((origin.char_start, origin.char_end))
        byte_positions = {}
        for identity, positions in requested_positions.items():
            cursor = byte_cursor = 0
            source_text = sources[identity].text
            resolved = {}
            for position in sorted(positions):
                byte_cursor += len(source_text[cursor:position].encode("utf-8"))
                resolved[position] = byte_cursor
                cursor = position
            byte_positions[identity] = resolved
        previous_ends: dict[str, int] = {}
        previous_starts: dict[str, int] = {}
        for chunk, origin in zip(self.snapshot.documents, self.origins):
            if not isinstance(origin, KnowledgeChunkOrigin) or origin.chunk_id != chunk.document_id:
                raise ValueError("invalid knowledge chunk origin")
            source = sources.get(origin.document_id)
            offsets = (origin.char_start, origin.char_end, origin.byte_start, origin.byte_end)
            if (source is None or any(type(value) is not int for value in offsets)
                    or not 0 <= origin.char_start < origin.char_end <= len(source.text)
                    or (self.splitter == "utf8" and origin.char_start < previous_ends.get(origin.document_id, 0))
                    or origin.char_start <= previous_starts.get(origin.document_id, -1)
                    or origin.char_end <= previous_ends.get(origin.document_id, 0)
                    or (self.splitter == "structure" and previous_ends.get(origin.document_id, 0) - origin.char_start > self.overlap_chars)
                    or origin.byte_end - origin.byte_start > self.chunk_bytes
                    or source.text[origin.char_start:origin.char_end] != chunk.text
                    or origin.byte_start != byte_positions[origin.document_id][origin.char_start]
                    or origin.byte_end != byte_positions[origin.document_id][origin.char_end]
                    or (source.source, source.title) != (chunk.source, chunk.title)):
                raise ValueError("knowledge chunk origin does not match source")
            previous_ends[origin.document_id] = origin.char_end
            previous_starts[origin.document_id] = origin.char_start

    @property
    def splitting_config(self) -> dict:
        return {"algorithm": "structure-v1" if self.splitter == "structure" else "utf8-v1",
                "chunk_bytes": self.chunk_bytes, "overlap_chars": self.overlap_chars}

    def to_json(self) -> str:
        """Export a self-contained trace; caller owns persistence and permissions."""
        value = {
            "format": "wagent-traced-knowledge-import-v1", "chunk_bytes": self.chunk_bytes,
            "manifest": json.loads(self.imported.to_manifest_json()),
            "sources": [{"id": item.document_id, "text": item.text, "source": item.source, "title": item.title}
                        for item in self.imported.documents],
            "snapshot": json.loads(self.snapshot.to_json()),
            "origins": [item.to_dict() for item in self.origins],
        }
        if self.splitter == "structure":
            value["format"] = "wagent-traced-knowledge-import-v2"
            value["splitting"] = self.splitting_config
        return _json(value)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, payload: str, *, expected_digest: str) -> TracedKnowledgeImport:
        """Validate a host-loaded canonical archive; hash is not authentication."""
        try:
            _digest(expected_digest)
            if (not isinstance(payload, str) or len(payload.encode("utf-8")) > 96 * 1024 * 1024
                    or hashlib.sha256(payload.encode("utf-8")).hexdigest() != expected_digest):
                raise ValueError
            value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            v2 = value.get("format") == "wagent-traced-knowledge-import-v2"
            keys = {"format", "chunk_bytes", "manifest", "sources", "snapshot", "origins"}
            if v2:
                keys.add("splitting")
            if set(value) != keys or value["format"] not in {"wagent-traced-knowledge-import-v1", "wagent-traced-knowledge-import-v2"}:
                raise ValueError
            if v2:
                config = value["splitting"]
                if (not isinstance(config, dict) or set(config) != {"algorithm", "chunk_bytes", "overlap_chars"}
                        or config["algorithm"] != "structure-v1" or config["chunk_bytes"] != value["chunk_bytes"]):
                    raise ValueError
            manifest = value["manifest"]
            if set(manifest) != {"format", "parser_key", "records"} or manifest["format"] != "wagent-knowledge-text-import-v1":
                raise ValueError
            if any(not isinstance(value[key], list) or len(value[key]) > 1024 for key in ("sources", "origins")):
                raise ValueError
            if not isinstance(manifest["records"], list) or len(manifest["records"]) > 1024:
                raise ValueError
            sources = []
            for item in value["sources"]:
                if set(item) != {"id", "text", "source", "title"}:
                    raise ValueError
                sources.append(KnowledgeDocument(item["id"], item["text"], item["source"], item["title"]))
            imported = KnowledgeTextImport(manifest["parser_key"], tuple(sources),
                                           tuple(KnowledgeFileRecord(**item) for item in manifest["records"]))
            snapshot_json = _json(value["snapshot"])
            snapshot = _decode(snapshot_json, hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
                               value["snapshot"]["namespace"], value["snapshot"]["version"])
            result = cls(imported, snapshot, tuple(KnowledgeChunkOrigin(**item) for item in value["origins"]), value["chunk_bytes"],
                         "structure" if v2 else "utf8", config["overlap_chars"] if v2 else 0)
            expected = prepare_traced_knowledge_import(snapshot.namespace, snapshot.version, imported, chunk_bytes=result.chunk_bytes,
                                                      splitter=result.splitter, overlap_chars=result.overlap_chars)
            if result != expected or result.to_json() != payload:
                raise ValueError
            return result
        except Exception:
            raise ValueError("invalid traced knowledge import archive") from None


def prepare_traced_knowledge_import(
    namespace: str, version: str, imported: KnowledgeTextImport, *, chunk_bytes: int = 4096,
    splitter: str = "utf8", overlap_chars: int = 0,
) -> TracedKnowledgeImport:
    """Prepare the built-in non-transforming splitter with exact source slices."""
    if not isinstance(imported, KnowledgeTextImport):
        raise TypeError("a knowledge text import is required")
    if splitter == "structure":
        selected = StructureKnowledgeSpanSplitter(chunk_bytes, overlap_chars)
        documents, origins = [], []
        total_bytes = 0
        config = {"algorithm": "structure-v1", "chunk_bytes": chunk_bytes, "overlap_chars": overlap_chars}
        for source in imported.documents:
            for position, span in enumerate(selected.split_spans(source.text)):
                text = source.text[span.char_start:span.char_end]
                total_bytes += 36 + len(text.encode("utf-8")) + len(source.source.encode("utf-8")) + len(source.title.encode("utf-8"))
                if len(documents) >= 1024 or total_bytes > 16 * 1024 * 1024:
                    raise ValueError("knowledge structural chunk expansion exceeds limit")
                identity = str(UUID(bytes=hashlib.sha256(_json([
                    "wagent-knowledge-chunk-v2", namespace, version, source.document_id, config, position,
                    span.char_start, span.char_end, span.byte_start, span.byte_end, text, source.source, source.title,
                ]).encode("utf-8")).digest()[:16]))
                documents.append(KnowledgeDocument(identity, text, source.source, source.title))
                origins.append(KnowledgeChunkOrigin(identity, source.document_id, span.char_start, span.char_end, span.byte_start, span.byte_end))
        return TracedKnowledgeImport(imported, KnowledgeSnapshot(namespace, version, tuple(documents)), tuple(origins),
                                     chunk_bytes, splitter, overlap_chars)
    if splitter != "utf8" or type(overlap_chars) is not int or overlap_chars != 0:
        raise ValueError("invalid knowledge splitting configuration")
    selected = Utf8KnowledgeTextSplitter(chunk_bytes)
    snapshot = prepare_knowledge_snapshot(namespace, version, imported.documents, splitter=selected)
    chunks = iter(snapshot.documents)
    origins = []
    for source in imported.documents:
        cursor = byte_cursor = 0
        for text in selected.split(source.text):
            chunk = next(chunks)
            start = source.text.index(text, cursor)
            end = start + len(text)
            byte_start = byte_cursor + len(source.text[cursor:start].encode("utf-8"))
            byte_end = byte_start + len(text.encode("utf-8"))
            origins.append(KnowledgeChunkOrigin(chunk.document_id, source.document_id, start, end, byte_start, byte_end))
            cursor, byte_cursor = end, byte_end
    return TracedKnowledgeImport(imported, snapshot, tuple(origins), chunk_bytes)
