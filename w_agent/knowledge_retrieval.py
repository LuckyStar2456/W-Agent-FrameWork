"""Offline BM25, reciprocal-rank fusion and replaceable knowledge reranking.

All corpora and callbacks are supplied by the host. Construction never discovers
providers or performs I/O. A retriever is not an authorization boundary.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from w_agent.knowledge_context import (
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KnowledgeRetrievalError,
    KnowledgeRetriever, _documents, _text,
)
from w_agent.vector_retrieval import _integer, _timeout


def _terms(text: str) -> tuple[str, ...]:
    # CJK characters are individual tokens; other Unicode words retain boundaries.
    return tuple(re.findall(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+", text.casefold()))


def _bm25(query: str, documents: tuple[KnowledgeDocument, ...],
          k1: float, b: float) -> tuple[float, ...]:
    frequencies = [Counter(_terms(document.title + "\n" + document.text)) for document in documents]
    lengths = [sum(values.values()) for values in frequencies]
    average = sum(lengths) / len(lengths) if lengths else 0
    terms = set(_terms(query))
    counts = {term: sum(term in values for values in frequencies) for term in terms}
    scores = []
    for values, length in zip(frequencies, lengths):
        score = 0.0
        for term in terms:
            frequency = values[term]
            if frequency:
                inverse = math.log1p((len(documents) - counts[term] + 0.5) / (counts[term] + 0.5))
                normalizer = frequency + k1 * (1 - b + b * length / average)
                score += inverse * frequency * (k1 + 1) / normalizer
        scores.append(score)
    return tuple(scores)


def _parameters(k1: float, b: float) -> None:
    if type(k1) not in (int, float) or not math.isfinite(k1) or not 0 < k1 <= 100:
        raise ValueError("BM25 k1 must be finite and positive")
    if type(b) not in (int, float) or not math.isfinite(b) or not 0 <= b <= 1:
        raise ValueError("BM25 b must be between zero and one")


@dataclass(frozen=True, slots=True)
class BM25KnowledgeRetriever:
    """Small local sparse lexical baseline with deterministic corpus-order ties."""

    store: InMemoryKnowledgeDocumentStore = field(repr=False)
    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self) -> None:
        if not isinstance(self.store, InMemoryKnowledgeDocumentStore):
            raise ValueError("BM25 requires an explicit in-memory corpus")
        _parameters(self.k1, self.b)

    async def retrieve(self, query: str, *, limit: int) -> tuple[KnowledgeDocument, ...]:
        try:
            _text(query, 4096)
            _integer(limit, 128)
            scores = _bm25(query, self.store.documents, self.k1, self.b)
            indices = sorted(range(len(scores)), key=lambda index: -scores[index])
            return tuple(self.store.documents[index] for index in indices if scores[index] > 0)[:limit]
        except Exception:
            raise KnowledgeRetrievalError("BM25 knowledge retrieval failed") from None


class KnowledgeReranker(Protocol):
    """Select unique candidate indices, never substitute text or widen scope."""

    async def rerank(self, query: str, documents: tuple[KnowledgeDocument, ...], *,
                     limit: int) -> tuple[int, ...]: ...


@dataclass(frozen=True, slots=True)
class BM25KnowledgeReranker:
    """Offline reranker; candidates with no lexical match keep their relative order."""

    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self) -> None:
        _parameters(self.k1, self.b)

    async def rerank(self, query: str, documents: tuple[KnowledgeDocument, ...], *,
                     limit: int) -> tuple[int, ...]:
        _text(query, 4096)
        _integer(limit, 128)
        _documents(documents, 128, 16 * 1024 * 1024)
        scores = _bm25(query, documents, self.k1, self.b)
        return tuple(sorted(range(len(scores)), key=lambda index: -scores[index])[:limit])


@dataclass(frozen=True, slots=True)
class RerankedKnowledgeRetriever:
    """Bound a borrowed reranker to original candidates and an overall timeout."""

    retriever: KnowledgeRetriever = field(repr=False)
    reranker: KnowledgeReranker = field(repr=False)
    candidate_limit: int = 32
    max_document_bytes: int = 1024 * 1024
    timeout: float = 30.0

    def __post_init__(self) -> None:
        _integer(self.candidate_limit, 128)
        _integer(self.max_document_bytes, 16 * 1024 * 1024)
        _timeout(self.timeout)
        if not callable(getattr(self.retriever, "retrieve", None)) or not callable(getattr(self.reranker, "rerank", None)):
            raise ValueError("reranked retrieval requires retrieval and reranking callbacks")

    async def retrieve(self, query: str, *, limit: int) -> tuple[KnowledgeDocument, ...]:
        try:
            _text(query, 4096)
            _integer(limit, self.candidate_limit)
            async with asyncio.timeout(self.timeout):
                documents = await self.retriever.retrieve(query, limit=self.candidate_limit)
                _documents(documents, self.candidate_limit, self.max_document_bytes)
                if not documents:
                    return ()
                indices = await self.reranker.rerank(query, documents, limit=min(limit, len(documents)))
                if not isinstance(indices, tuple) or len(indices) > min(limit, len(documents)):
                    raise ValueError("invalid reranker output")
                if any(type(index) is not int or not 0 <= index < len(documents) for index in indices):
                    raise ValueError("reranker index outside candidates")
                if len(set(indices)) != len(indices):
                    raise ValueError("duplicate reranker index")
                return tuple(documents[index] for index in indices)
        except Exception:
            raise KnowledgeRetrievalError("knowledge reranking failed") from None


@dataclass(frozen=True, slots=True)
class HybridKnowledgeRetriever:
    """Weighted reciprocal-rank fusion over host-authorized ranked retrievers.

    Scores are sum(weight / (rank_constant + one_based_rank)). Sources execute
    in host order, under one timeout; failures never return partial evidence.
    Dense and lexical branches must use the same document IDs and content.
    """

    retrievers: tuple[KnowledgeRetriever, ...] = field(repr=False)
    weights: tuple[float, ...] | None = None
    candidate_limit: int = 32
    rank_constant: float = 60.0
    max_document_bytes: int = 1024 * 1024
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.retrievers, tuple) or not 2 <= len(self.retrievers) <= 8:
            raise ValueError("hybrid retrieval requires two to eight retrievers")
        if any(not callable(getattr(item, "retrieve", None)) for item in self.retrievers):
            raise ValueError("hybrid retrieval callback is invalid")
        weights = self.weights if self.weights is not None else (1.0,) * len(self.retrievers)
        if not isinstance(weights, tuple) or len(weights) != len(self.retrievers):
            raise ValueError("hybrid weights must match retrievers")
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1000 for value in weights):
            raise ValueError("hybrid weights must be finite and positive")
        if type(self.rank_constant) not in (int, float) or not math.isfinite(self.rank_constant) or not 0 < self.rank_constant <= 10000:
            raise ValueError("hybrid rank constant must be finite and positive")
        _integer(self.candidate_limit, 128)
        _integer(self.max_document_bytes, 16 * 1024 * 1024)
        _timeout(self.timeout)
        object.__setattr__(self, "weights", weights)

    async def retrieve(self, query: str, *, limit: int) -> tuple[KnowledgeDocument, ...]:
        try:
            _text(query, 4096)
            _integer(limit, self.candidate_limit)
            documents: dict[str | int, KnowledgeDocument] = {}
            scores: dict[str | int, float] = {}
            async with asyncio.timeout(self.timeout):
                for retriever, weight in zip(self.retrievers, self.weights):
                    matches = await retriever.retrieve(query, limit=self.candidate_limit)
                    _documents(matches, self.candidate_limit, self.max_document_bytes)
                    for rank, document in enumerate(matches, start=1):
                        identity = document.document_id
                        if identity in documents and documents[identity] != document:
                            raise ValueError("hybrid sources disagree on document content")
                        documents[identity] = document
                        scores[identity] = scores.get(identity, 0.0) + weight / (self.rank_constant + rank)
                    _documents(tuple(documents.values()), 1024, self.max_document_bytes)
            identities = sorted(scores, key=lambda identity: -scores[identity])[:limit]
            return tuple(documents[identity] for identity in identities)
        except Exception:
            raise KnowledgeRetrievalError("hybrid knowledge retrieval failed") from None
