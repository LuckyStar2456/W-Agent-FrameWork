"""Snapshot-bound dense-vector preparation and read-only knowledge retrieval."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from w_agent.knowledge_context import (
    KnowledgeDocument, KnowledgeRetrievalError, VectorKnowledgeRetriever,
    _documents as _validate_documents, _identity,
)
from w_agent.knowledge_ingestion import KnowledgeSnapshot, _label
from w_agent.vector_indexing import DenseVectorPoint
from w_agent.vector_retrieval import (
    AsyncTextEmbedder, DenseVectorSearch, VectorRetrievalError, _integer, _timeout, _vector,
)


@dataclass(frozen=True, slots=True)
class KnowledgeVectorIndex:
    """Pure identity map, not proof that an index exists or writes have completed.

    embedding_key is a host-owned model/preprocessing revision label. Actual
    model identity cannot be inferred from a generic embedding callback.
    """

    snapshot: KnowledgeSnapshot = field(repr=False)
    embedding_key: str = field(repr=False)
    dimensions: int
    snapshot_digest: str = field(init=False)
    point_ids: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, KnowledgeSnapshot):
            raise ValueError("knowledge vector index requires a snapshot")
        _label(self.embedding_key)
        _integer(self.dimensions, 65536)
        digest = self.snapshot.digest
        ids = []
        for document in self.snapshot.documents:
            encoded = json.dumps([
                "wagent-knowledge-vector-point-v1", digest, self.embedding_key,
                self.dimensions, document.document_id,
            ], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ids.append(str(UUID(bytes=hashlib.sha256(encoded).digest()[:16])))
        if len(set(ids)) != len(ids):
            raise ValueError("knowledge vector identities must be unique")
        object.__setattr__(self, "snapshot_digest", digest)
        object.__setattr__(self, "point_ids", tuple(ids))

    def point_id(self, document_id: str | int) -> str:
        """Resolve an exact snapshot document identity without external lookup."""
        _identity(document_id)
        for document, point_id in zip(self.snapshot.documents, self.point_ids, strict=True):
            if document.document_id == document_id:
                return point_id
        raise ValueError("document is not in the knowledge vector index")


def knowledge_document_embedding_text(document: KnowledgeDocument) -> str:
    """Render title/body only; source, original ID and version labels are excluded."""
    try:
        if not isinstance(document, KnowledgeDocument):
            raise ValueError
        return json.dumps({
            "format": "wagent-knowledge-embedding-v1", "title": document.title, "text": document.text,
        }, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except Exception:
        raise VectorRetrievalError("knowledge embedding text preparation failed") from None


async def prepare_knowledge_vectors(
    index: KnowledgeVectorIndex,
    embedder: AsyncTextEmbedder,
    *,
    document_ids: tuple[str | int, ...] | None = None,
    confirm_embedding: bool = False,
    max_input_bytes: int = 1024 * 1024,
    max_vector_values: int = 1024 * 1024,
    timeout: float = 30.0,
) -> tuple[DenseVectorPoint, ...]:
    """Explicitly disclose a bounded batch to Embedder; never write or retry.

    None selects the whole snapshot only if it fits one batch (128 documents).
    Bigger snapshots require explicit subsets. All selection/text bounds are
    checked before the first potentially billed embedding call.
    """
    try:
        if confirm_embedding is not True or not isinstance(index, KnowledgeVectorIndex):
            raise ValueError
        if not callable(getattr(embedder, "embed", None)):
            raise ValueError
        _integer(max_input_bytes, 32 * 1024 * 1024)
        _integer(max_vector_values, 8 * 1024 * 1024)
        _timeout(timeout)
        selected = document_ids
        if selected is None:
            selected = tuple(document.document_id for document in index.snapshot.documents)
        if not isinstance(selected, tuple) or len(selected) > 128:
            raise ValueError
        for identity in selected:
            _identity(identity)
        if len(set(selected)) != len(selected) or len(selected) * index.dimensions > max_vector_values:
            raise ValueError
        documents = {document.document_id: document for document in index.snapshot.documents}
        # Resolve every ID and render every disclosed string before any callback.
        identities = tuple(index.point_id(identity) for identity in selected)
        texts = tuple(knowledge_document_embedding_text(documents[identity]) for identity in selected)
        if sum(len(text.encode("utf-8")) for text in texts) > max_input_bytes:
            raise ValueError
        points = []
        async with asyncio.timeout(timeout):
            for identity, text in zip(identities, texts, strict=True):
                vector = _vector(await embedder.embed(text))
                if len(vector) != index.dimensions:
                    raise ValueError
                points.append(DenseVectorPoint(identity, vector))
        return tuple(points)
    except Exception:
        raise VectorRetrievalError("knowledge vector preparation failed; prior embedding calls may be billed") from None


@dataclass(frozen=True, slots=True)
class _DimensionCheckedEmbedder:
    embedder: AsyncTextEmbedder = field(repr=False)
    dimensions: int

    async def embed(self, text: str) -> tuple[float, ...]:
        result = _vector(await self.embedder.embed(text))
        if len(result) != self.dimensions:
            raise ValueError("knowledge query embedding dimensions do not match")
        return result


@dataclass(frozen=True, slots=True)
class _SnapshotPointStore:
    documents: Mapping[str, KnowledgeDocument] = field(repr=False)

    async def get_many(self, document_ids: tuple[str | int, ...]) -> tuple[KnowledgeDocument, ...]:
        return tuple(KnowledgeDocument(
            identity, self.documents[identity].text, self.documents[identity].source,
            self.documents[identity].title,
        ) for identity in document_ids)


@dataclass(frozen=True, slots=True)
class SnapshotVectorKnowledgeRetriever:
    """Search only snapshot/model-bound IDs, returning original local documents.

    No lookup/upload/latest-version selection occurs during construction. Query
    bodies go to the borrowed Embedder; remote payloads never supply prompt text.
    """

    index: KnowledgeVectorIndex = field(repr=False)
    embedder: AsyncTextEmbedder = field(repr=False)
    backend: DenseVectorSearch = field(repr=False)
    timeout: float = 30.0
    max_document_bytes: int = 1024 * 1024
    _delegate: VectorKnowledgeRetriever = field(init=False, repr=False)
    _documents: Mapping[str, KnowledgeDocument] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.index, KnowledgeVectorIndex) or not callable(getattr(self.embedder, "embed", None)):
            raise ValueError("snapshot retrieval requires an index and embedder")
        mapped = {}
        for document, identity in zip(self.index.snapshot.documents, self.index.point_ids, strict=True):
            mapped[identity] = document
        documents = MappingProxyType(mapped)
        delegate = VectorKnowledgeRetriever(
            _DimensionCheckedEmbedder(self.embedder, self.index.dimensions), self.backend,
            _SnapshotPointStore(documents), point_ids=self.index.point_ids,
            timeout=self.timeout, max_document_bytes=self.max_document_bytes,
        )
        object.__setattr__(self, "_documents", documents)
        object.__setattr__(self, "_delegate", delegate)

    async def retrieve(self, query: str, *, limit: int) -> tuple[KnowledgeDocument, ...]:
        try:
            matched = await self._delegate.retrieve(query, limit=limit)
            # The delegate validates the exact candidate set and keeps backend rank.
            originals = tuple(self._documents[document.document_id] for document in matched)
            _validate_documents(originals, limit, self.max_document_bytes)
            return originals
        except Exception:
            raise KnowledgeRetrievalError("snapshot knowledge retrieval failed") from None
