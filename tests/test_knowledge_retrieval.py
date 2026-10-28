import asyncio

import pytest

from w_agent.knowledge_context import (
    InMemoryKnowledgeDocumentStore, KnowledgeDocument, KnowledgeRetrievalError,
    VectorKnowledgeRetriever,
)
from w_agent.knowledge_retrieval import (
    BM25KnowledgeReranker, BM25KnowledgeRetriever, HybridKnowledgeRetriever,
    RerankedKnowledgeRetriever,
)
from w_agent.vector_retrieval import VectorSearchMatch


class Ranked:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    async def retrieve(self, query, *, limit):
        self.calls.append((query, limit))
        return self.documents[:limit]


@pytest.mark.asyncio
async def test_bm25_word_boundaries_cjk_empty_and_stable_ties():
    documents = (KnowledgeDocument(1, "concatenate"), KnowledgeDocument(2, "cat"),
                 KnowledgeDocument(3, "CAT"), KnowledgeDocument(4, "退货政策"))
    retriever = BM25KnowledgeRetriever(InMemoryKnowledgeDocumentStore(documents))
    assert await retriever.retrieve("cat", limit=4) == documents[1:3]
    assert await retriever.retrieve("退货", limit=4) == documents[3:]
    assert await retriever.retrieve("unknown", limit=4) == ()
    assert await retriever.retrieve("!!!", limit=4) == ()
    assert await BM25KnowledgeRetriever(InMemoryKnowledgeDocumentStore(())).retrieve("cat", limit=1) == ()


@pytest.mark.asyncio
async def test_bm25_idf_and_length_normalization():
    rare = KnowledgeDocument("rare", "common rare")
    common = KnowledgeDocument("common", "common " * 80)
    retriever = BM25KnowledgeRetriever(InMemoryKnowledgeDocumentStore((common, rare)))
    assert (await retriever.retrieve("rare", limit=2)) == (rare,)
    scores_order = await retriever.retrieve("common rare", limit=2)
    assert scores_order[0] == rare


@pytest.mark.asyncio
async def test_dense_sparse_fusion_and_local_rerank_end_to_end():
    docs = (KnowledgeDocument(1, "delivery tomorrow"), KnowledgeDocument(2, "refund seven days"),
            KnowledgeDocument(3, "refund eligibility"))
    store = InMemoryKnowledgeDocumentStore(docs)

    class Embedder:
        async def embed(self, query):
            assert query == "refund"
            return (1.0, 0.0)

    class Backend:
        async def search(self, vector, *, limit, point_ids=None):
            assert vector == (1.0, 0.0) and point_ids == (1, 2, 3)
            return (VectorSearchMatch(1, 0.99), VectorSearchMatch(2, 0.9))[:limit]

    dense = VectorKnowledgeRetriever(Embedder(), Backend(), store, point_ids=(1, 2, 3))
    sparse = BM25KnowledgeRetriever(store)
    hybrid = HybridKnowledgeRetriever((dense, sparse), candidate_limit=3)
    result = await hybrid.retrieve("refund", limit=3)
    assert result[0] == docs[1]  # Appears in both ranked lists.
    assert {item.document_id for item in result} == {1, 2, 3}
    reranked = RerankedKnowledgeRetriever(hybrid, BM25KnowledgeReranker(), candidate_limit=3)
    result = await reranked.retrieve("refund", limit=3)
    assert result[-1] == docs[0]
    assert await RerankedKnowledgeRetriever(Ranked(()), BM25KnowledgeReranker()).retrieve("q", limit=1) == ()


@pytest.mark.asyncio
async def test_fusion_weights_and_stable_ties():
    one, two = KnowledgeDocument(1, "one"), KnowledgeDocument(2, "two")
    assert await HybridKnowledgeRetriever((Ranked((one,)), Ranked((two,)))).retrieve("q", limit=2) == (one, two)
    assert await HybridKnowledgeRetriever((Ranked((one,)), Ranked((two,))), weights=(1, 2)).retrieve("q", limit=2) == (two, one)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [(), (0, 0), (False,), (-1,), (2,), [0], (KnowledgeDocument(9, "outside"),)])
async def test_reranker_can_return_empty_but_never_forge_or_duplicate_candidates(bad):
    class Reranker:
        async def rerank(self, query, documents, *, limit):
            return bad

    retriever = RerankedKnowledgeRetriever(Ranked((KnowledgeDocument(1, "one"), KnowledgeDocument(2, "two"))), Reranker())
    if bad == ():
        assert await retriever.retrieve("q", limit=2) == ()
    else:
        with pytest.raises(KnowledgeRetrievalError):
            await retriever.retrieve("q", limit=2)


@pytest.mark.asyncio
async def test_conflicting_source_documents_and_partial_failure_fail_closed():
    one = KnowledgeDocument(1, "one")
    conflicting = HybridKnowledgeRetriever((Ranked((one,)), Ranked((KnowledgeDocument(1, "other"),))))
    with pytest.raises(KnowledgeRetrievalError):
        await conflicting.retrieve("q", limit=2)

    class Failing:
        async def retrieve(self, query, *, limit):
            raise RuntimeError("PRIVATE_DETAILS")

    with pytest.raises(KnowledgeRetrievalError) as error:
        await HybridKnowledgeRetriever((Ranked((one,)), Failing())).retrieve("q", limit=2)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_hybrid_timeout_and_cancellation_drains_callback(cancel):
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow:
        async def retrieve(self, query, *, limit):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    retriever = HybridKnowledgeRetriever((Slow(), Ranked(())), timeout=30 if cancel else 0.01)
    task = asyncio.create_task(retriever.retrieve("q", limit=1))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else KnowledgeRetrievalError):
        await task
    assert closed.is_set()


@pytest.mark.parametrize("options", [{"weights": (1,)}, {"weights": (True, 1)},
    {"rank_constant": float("nan")}, {"candidate_limit": True}, {"timeout": 0}])
def test_hybrid_invalid_options_do_not_invoke_callbacks(options):
    source = Ranked(())
    with pytest.raises(ValueError):
        HybridKnowledgeRetriever((source, source), **options)
    assert not source.calls


@pytest.mark.asyncio
async def test_bounds_checked_before_callback_and_combined_corpus_bound():
    source = Ranked((KnowledgeDocument(1, "one"),))
    hybrid = HybridKnowledgeRetriever((source, source), candidate_limit=1)
    with pytest.raises(KnowledgeRetrievalError):
        await hybrid.retrieve("q", limit=2)
    assert not source.calls
    with pytest.raises(KnowledgeRetrievalError):
        await HybridKnowledgeRetriever((source, Ranked((KnowledgeDocument(2, "two"),))), max_document_bytes=7).retrieve("q", limit=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_reranker_timeout_or_cancellation_closes_callback(cancel):
    started, closed = asyncio.Event(), asyncio.Event()

    class Slow:
        async def rerank(self, query, documents, *, limit):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

    retriever = RerankedKnowledgeRetriever(Ranked((KnowledgeDocument(1, "one"),)), Slow(), timeout=30 if cancel else 0.01)
    task = asyncio.create_task(retriever.retrieve("q", limit=1))
    await started.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else KnowledgeRetrievalError):
        await task
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("documents", [[KnowledgeDocument(1, "one")], (object(),),
    (KnowledgeDocument(1, "one"), KnowledgeDocument(1, "one"))])
async def test_malformed_branch_stops_before_later_branch(documents):
    later = Ranked(())

    class Invalid:
        async def retrieve(self, query, *, limit):
            return documents

    with pytest.raises(KnowledgeRetrievalError):
        await HybridKnowledgeRetriever((Invalid(), later)).retrieve("q", limit=2)
    assert not later.calls
