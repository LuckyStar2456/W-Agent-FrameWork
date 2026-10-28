"""Pure text preparation and immutable named knowledge snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from w_agent.knowledge_context import (
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KnowledgeRetrievalError,
    _documents, _text,
)

MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


def _label(value: str) -> None:
    _text(value, 128)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("knowledge snapshot label is invalid")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


class KnowledgeTextSplitter(Protocol):
    """Trusted pure text extension; output must be a bounded tuple of strings."""

    def split(self, text: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class Utf8KnowledgeTextSplitter:
    """Non-overlapping character-aligned UTF-8 chunks, not semantic/token chunks.

    Preserve characters within chunks; skip whitespace-only chunks. No file
    access, normalization, sentence detection, embedding or remote callbacks.
    """

    max_chunk_bytes: int = 4096

    def __post_init__(self) -> None:
        if type(self.max_chunk_bytes) is not int or not 4 <= self.max_chunk_bytes <= 1024 * 1024:
            raise ValueError("knowledge chunk size must be between 4 bytes and 1 MiB")

    def split(self, text: str) -> tuple[str, ...]:
        _text(text, 1024 * 1024)
        chunks: list[str] = []
        current: list[str] = []
        size = 0
        for char in text:
            width = len(char.encode("utf-8"))
            if size + width > self.max_chunk_bytes:
                chunk = "".join(current)
                if chunk.strip():
                    chunks.append(chunk)
                    if len(chunks) > 1024:
                        raise ValueError("knowledge split exceeds chunk limit")
                current = []
                size = 0
            current.append(char)
            size += width
        chunk = "".join(current)
        if chunk.strip():
            chunks.append(chunk)
        if len(chunks) > 1024:
            raise ValueError("knowledge split exceeds chunk limit")
        return tuple(chunks)


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshot:
    """Ordered immutable documents pinned to exact user-chosen labels.

    Digest is an integrity locator, not a signature, secret or authorization.
    Neither construction nor conversion to an in-memory store performs I/O.
    """

    namespace: str
    version: str
    documents: tuple[KnowledgeDocument, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _label(self.namespace)
        _label(self.version)
        _documents(self.documents, 1024, 16 * 1024 * 1024)
        if len(self.to_json().encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("knowledge snapshot exceeds serialized limit")

    def to_json(self) -> str:
        """Explicitly expose snapshot bodies as canonical JSON; never auto-log."""
        return _json({
            "format": "wagent-knowledge-snapshot-v1",
            "namespace": self.namespace, "version": self.version,
            "documents": [{"id": item.document_id, "text": item.text,
                           "source": item.source, "title": item.title} for item in self.documents],
        })

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def as_document_store(self) -> InMemoryKnowledgeDocumentStore:
        """Pin this snapshot without a live latest-version pointer or database handle."""
        return InMemoryKnowledgeDocumentStore(self.documents)


def prepare_knowledge_snapshot(
    namespace: str, version: str, documents: tuple[KnowledgeDocument, ...],
    *, splitter: KnowledgeTextSplitter | None = None,
) -> KnowledgeSnapshot:
    """Prepare host-supplied text; no implicit files, databases or embedding calls.

    IDs bind format, namespace/version, original ID, chunk position/text and
    source/title. Host splitters can transform text; their execution is trusted.
    """
    try:
        _label(namespace)
        _label(version)
        _documents(documents, 1024, 16 * 1024 * 1024)
        selected = splitter if splitter is not None else Utf8KnowledgeTextSplitter()
        if not callable(getattr(selected, "split", None)):
            raise ValueError
        prepared = []
        size = 0
        for document in documents:
            chunks = selected.split(document.text)
            if not isinstance(chunks, tuple) or not chunks or len(prepared) + len(chunks) > 1024:
                raise ValueError
            for index, text in enumerate(chunks):
                _text(text, 1024 * 1024)
                # Bound cumulative expansion before hashing/constructing output.
                size += 36 + sum(len(value.encode("utf-8")) for value in (text, document.source, document.title))
                if size > 16 * 1024 * 1024:
                    raise ValueError
                identity = str(UUID(bytes=hashlib.sha256(_json([
                    "wagent-knowledge-chunk-v1", namespace, version, document.document_id,
                    index, text, document.source, document.title,
                ]).encode("utf-8")).digest()[:16]))
                prepared.append(KnowledgeDocument(identity, text, document.source, document.title))
        return KnowledgeSnapshot(namespace, version, tuple(prepared))
    except Exception:
        raise KnowledgeRetrievalError("knowledge snapshot preparation failed") from None


class KnowledgeSnapshotStore(Protocol):
    """Append immutable named versions; persistence implementations are replaceable."""

    async def save(self, snapshot: KnowledgeSnapshot, *, confirm_write: bool = False) -> str: ...

    async def load(self, namespace: str, version: str) -> KnowledgeSnapshot: ...


@dataclass(frozen=True, slots=True)
class KnowledgeSnapshotInfo:
    """Stored catalog declarations, not proof that the snapshot body is intact."""

    namespace: str
    version: str
    digest: str
    payload_bytes: int

    def __post_init__(self) -> None:
        _label(self.namespace)
        _label(self.version)
        if (not isinstance(self.digest, str) or len(self.digest) != 64
                or any(char not in "0123456789abcdef" for char in self.digest)):
            raise ValueError("invalid knowledge digest")
        if type(self.payload_bytes) is not int or not 0 < self.payload_bytes <= MAX_SNAPSHOT_BYTES:
            raise ValueError("invalid knowledge payload size")


class KnowledgeSnapshotCatalog(Protocol):
    """Optional catalog extension; existing snapshot-store plugins need not implement it."""

    async def list_snapshots(self, namespace: str | None = None) -> tuple[KnowledgeSnapshotInfo, ...]: ...
