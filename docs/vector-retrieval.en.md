# External vector retrieval and Qdrant history selection

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./vector-retrieval.md)

Status: 2.0.0 `Experimental`, included in 2.0.0 and not part of `2.0.0a9`. All 51 offline regressions in `tests/test_vector_retrieval.py` pass. Live Qdrant/embedding acceptance has not been performed; a9 validation does not cover this addition.

## Open protocols and first template

Optionally supply the locally regression-tested worktree [HTTP embedding/budget wrapper](./embeddings.en.md). This does not change candidate filtering, history ordering or Qdrant read boundaries, or implicitly authorize query disclosure.

- `AsyncTextEmbedder.embed(text)` is a host-authorized async embedding protocol returning a tuple of finite numbers. No model, credential or query is selected implicitly. Hosts may choose local models, their own Providers or services and account for costs separately.
- `DenseVectorSearch.search(vector, *, limit, point_ids=None)` is replaceable and returns immutable `VectorSearchMatch(point_id, score)`. Matches contain IDs/scores, not remote text or authority. Generic match IDs may be nonempty strings or uint64; the Qdrant template further restricts them to UUID/uint64.
- `QdrantVectorSearch` implements read-only dense Query API lookup, supporting default/named vectors, thresholds, candidate-ID filtering, API keys and replaceable `HttpToolTransport`. No mandatory SDK: the default lazily uses the existing HTTPX transport (`models` extra), never installing dependencies.
- `QdrantSessionHistoryRetriever` implements the existing `AsyncSessionHistoryRetriever`, selecting only current candidate history without changing Runtime or Agent Loop. Other `DenseVectorSearch` implementations may be injected, but the history-ID convention below still applies.

Requests use `POST /collections/{collection}/points/query`, explicitly disable payload/vector return, and use `using`, `score_threshold` and optional `filter.must.has_id`. Mapping follows the [Qdrant Query API](https://api.qdrant.tech/api-reference/search/query-points) and [ID-filter documentation](https://qdrant.tech/documentation/search/filtering/#has-id). This is not a complete Qdrant client and exposes no writes, arbitrary query parameters or server-side inference.

## Host-prepared history index

The worktree now supplies separate [explicit vector preparation/write templates](./vector-indexing.en.md), with independent history-embedding consent and exact-plan overwrite confirmation. Retrieval never invokes them automatically. They are also included in 2.0.0, with local regressions passing and outside a9. Read-only boundaries below still refer to the retrieval template itself.

The template queries only: no collection creation, history upload or vector update. In a separately authorized indexing workflow, hosts should:

1. Choose a stable, non-secret `namespace` for the project/Session/index version and create `SessionHistoryTurn` segments matching the history policy's contiguous Run text segments.
2. Generate IDs with `qdrant_history_point_id(namespace, turn)`, embed each segment with the host-selected model and index the vector in Qdrant. Index/query models, dimensions and named-vector settings must agree; none of these operations is automatic here.
3. Construct the selector with the same namespace and explicit query. The embedder receives only query text; search receives the query vector and candidate IDs, never history bodies, Session titles or name/metadata.

IDs are UUIDs derived from the first 128 SHA-256 bits of canonical JSON containing a version label, namespace, Run ID, ordered roles and text blocks. Names/metadata are excluded. Changes to text/order/Run ID/namespace require host reindexing. Repeated identical segments are ambiguous and rejected, not guessed. This is not a tenant, permission boundary, signature or secret; guessable content may be dictionary-matched. Hosts still own the association between indexed vectors and IDs: hashing does not prove relevance.

```python
import os
from w_agent import (
    AsyncRetrievedSessionHistoryPolicy, QdrantSessionHistoryRetriever,
    QdrantVectorSearch, load_local_runtime_config, assemble_local_runtime,
)
from my_application import authorized_embedder  # Host async embed(text) implementation.

backend = QdrantVectorSearch(
    base_url="http://127.0.0.1:6333", collection="support_history",
    api_key=os.environ.get("QDRANT_API_KEY"), vector_name="dense",
)
retriever = QdrantSessionHistoryRetriever("support-session-v1", authorized_embedder, backend)
history = AsyncRetrievedSessionHistoryPolicy(
    query="refund handling evidence", retriever=retriever,
    max_retrieved_turns=4, recent_turns=2,
)
config = load_local_runtime_config("runtime.json")
async with assemble_local_runtime(config) as runtime:
    run = await runtime.run(
        "Continue the refund task", session_id="existing-session-id", history_policy=history,
    )
```

The example requires an existing project/Session/index and host authorization for embedding and model access. The outer history policy restores chronology and retains recent segments; backend scores only guide selection. No older segments means no embedding/search. Valid zero matches retain only recent history, without silently falling back to all history. HTTP errors, missing collections or invalid results fail closed without retries.

Direct `await backend.search((0.1, 0.2), limit=4)` also returns IDs/scores for host-defined document stores and content policies. Omitting `point_ids` explicitly searches the entire collection. An empty tuple sends no request and never removes filtering. The history adapter always supplies candidates and revalidates replacement-backend results: unfamiliar IDs cannot introduce remote text.

## Boundaries, lifecycle and accounting

- At most 128 results, 1024 candidate IDs and 1–65536 vector dimensions per call; bool, NaN, Infinity, duplicate IDs and non-tuple vectors are rejected. History additionally follows `SessionHistoryLimits`. A single identity input allows at most 1024 messages, 4096 text blocks and 1 MiB text; Run IDs allow 512 UTF-8 bytes.
- Request/response bodies default to 1 MiB each, configurable up to 16 MiB. The default transport bounds streamed response bytes; injected responses are checked again. Custom-transport allocation, decompression and internal retries are outside that check.
- HTTP(S) only; endpoint userinfo, queries, fragments and whitespace/control characters are rejected, and collection names are restricted. Default redirects are disabled; unsuccessful HTTP and duplicate JSON fields fail closed. URL validation is not SSRF defense, network isolation or permission enforcement. Hosts own destinations, TLS, proxies and network/filesystem permissions. Send API keys only to trusted destinations.
- Backend repr excludes API key, endpoint and collection. Fixed error messages omit queries, credentials and remote error bodies. Transport logs, traces, callbacks or explicitly printing requests may still disclose data and require host controls.
- Default transport opens/closes a client per request. Custom transports/embedders are borrowed and not closed automatically by Runtime; hosts release them after active work ends. Borrowing does not sandbox code.
- Backend timeout covers request waiting; selector timeout covers embedding plus retrieval, both defaulting to 30 seconds. The history policy has its own timeout. Async cancellation propagates rather than becoming success/empty results. Blocking or cancellation-ignoring callbacks cannot be force-terminated, and cancellation cannot undo external charges.
- Embedding, Qdrant resource usage and indexing do not automatically enter Agent `TokenBudget`, shared pools or Session totals. Backend resource counters are not LLM tokens. Hosts must instrument paid embedding callbacks with appropriate reservations/accounting. This is not a unified preparation/main-Run ledger.

## Remaining work and verification

Local regressions pass for request mapping, candidate boundaries, privacy, failures, size limits, cancellation, and Session-policy integration. Separate index preparation/write source is linked above. [Knowledge-body retrieval/context policies](./knowledge-context.en.md) and new [BM25/hybrid/reranking](./knowledge-retrieval.en.md) also have offline regressions. See the [roadmap](./roadmap.en.md) for live Qdrant/embedding acceptance, other backends, and remaining plans.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
