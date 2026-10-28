# Sparse and hybrid retrieval with reranking

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

Status: workspace Experimental, published in 2.0.0. Offline regressions cover local BM25, RRF fusion, candidate reranking, and Workflow/evaluation assembly. Live services and retrieval quality benchmarks have not been accepted.

Components in `w_agent.knowledge_retrieval` implement the existing `KnowledgeRetriever` contract and work with `LocalKnowledgeBinding`, `knowledge_search_tool`, and `AsyncKnowledgeContextPolicy`. Construction performs no network calls, provider discovery, or model installation. Hosts explicitly supply authorized corpora, dense retrievers, and optional rerankers.

```python
from w_agent.knowledge_context import InMemoryKnowledgeDocumentStore, KnowledgeDocument
from w_agent.knowledge_retrieval import BM25KnowledgeRetriever
from w_agent.knowledge_runtime import LocalKnowledgeBinding

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("refund", "Refund requests are accepted within seven days", "local:refund"),
    KnowledgeDocument("delivery", "Delivery usually takes three days", "local:delivery"),
))
sparse = BM25KnowledgeRetriever(store)
binding = LocalKnowledgeBinding(sparse, limit=2)
# In an async host: await sparse.retrieve("refund", limit=2)
```

BM25 scores title and body, keeps Unicode word boundaries, and tokenizes CJK characters individually. No match returns an empty tuple; ties preserve corpus order. This is a small-corpus local baseline with no language model, Chinese dictionary, or persistent inverted index. Defaults are `k1=1.2` and `b=0.75`, both configurable.

Compose hybrid retrieval with `HybridKnowledgeRetriever((dense, sparse), candidate_limit=32)`; `dense` can be the existing `VectorKnowledgeRetriever`. Each source returns up to `candidate_limit` documents. Reciprocal-rank fusion computes `sum(weight / (rank_constant + rank))` with one-based rank, a default constant of 60, and equal weights. Raw backend scores are not compared. Source order and rank break ties. The same ID must carry identical text, title, and source or fusion fails; use the same pinned knowledge version across branches. Two to eight sources run in host order under one overall timeout. Any failure stops the operation without partial evidence.

```python
from w_agent.knowledge_retrieval import (
    BM25KnowledgeReranker, HybridKnowledgeRetriever, RerankedKnowledgeRetriever,
)

# dense is a previously assembled and authorized host KnowledgeRetriever.
hybrid = HybridKnowledgeRetriever((dense, sparse), candidate_limit=32)
retriever = RerankedKnowledgeRetriever(
    hybrid, BM25KnowledgeReranker(), candidate_limit=32,
)
```

The async `KnowledgeReranker.rerank(query, documents, *, limit)` protocol returns a tuple of unique candidate indices. For example, `(2, 0)` selects the third then first original document. Empty results are allowed; duplicate/out-of-range positions and substituted text are rejected. `BM25KnowledgeReranker` is the included offline implementation. Hosts implement and authorize semantic/external rerankers, which receive the query and full candidate text. Candidates without lexical matches remain last in their original order.

Fusion and reranking require request `limit <= candidate_limit` (maximum 128). `max_document_bytes` bounds candidate and combined fusion content; oversized content fails without silent truncation. Timeouts and asyncio cancellation drain the borrowed coroutine but cannot prove external execution stopped or was refunded. Each source enforces its own authorization scope; fusion grants no additional access.

Run `py -3.11 -m pytest tests/test_knowledge_retrieval.py`. See [Workflow and evaluation](knowledge-workflow-evaluation.en.md) for end-to-end assembly.
