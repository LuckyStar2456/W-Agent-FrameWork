# Replaceable knowledge retrieval and Agent context

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-context.md)

[Named Runtime/CLI/TUI assembly](./knowledge-runtime.en.md) explicitly composes this policy and supports knowledge-only mode. The include_history=False policy-skipping behavior below describes direct lower-level injection, not that composition path.

Status: 2.0.0 `Experimental`, included in 2.0.0 and not part of `2.0.0a9`. All 36 local regressions in `tests/test_knowledge_context.py` pass. Live model/database acceptance and publication have not been performed.

## Independent components, no Agent ownership

- `KnowledgeDocument(document_id, text, source="", title="")` is immutable text. Source is an opaque citation, never an automatically opened URL/file. IDs accept bounded strings or uint64. Text/source/title allow at most 1 MiB/4096/1024 UTF-8 bytes respectively; repr hides these three fields.
- `AsyncKnowledgeDocumentStore.get_many(ids)` must return all and only the requested documents, in any order. `InMemoryKnowledgeDocumentStore` holds at most 1024 documents and 16 MiB of fields; it is neither persistence nor authorization.
- `KnowledgeRetriever.retrieve(query, limit=...)` returns unique, ranked document tuples. Hosts can implement any retrieval pipeline.
- `KeywordKnowledgeRetriever` is a usable local baseline: casefolded whitespace-term substring matching, ranked by matched term count, with input order breaking ties. It is not semantic retrieval or a Chinese tokenizer.
- `VectorKnowledgeRetriever` composes a host Embedder, existing `DenseVectorSearch` and a document store. Only the explicit query goes to Embedder; vectors/candidate IDs go to search; matched IDs resolve host-controlled bodies. Arbitrary vector-service payloads are not adopted.
- `AsyncKnowledgeContextPolicy` composes a retriever with a sync/async history policy through the existing `history_policy` hook. No Loop replacement, global service, plugin discovery or implicit import is involved.

## Assembly without an external retrieval service

These are worktree APIs, not imports available in published a9. Hosts supply `runtime` using the existing local-runtime assembly functions.

```python
from w_agent import (
    AsyncKnowledgeContextPolicy, InMemoryKnowledgeDocumentStore,
    KnowledgeDocument, KeywordKnowledgeRetriever,
)

store = InMemoryKnowledgeDocumentStore((
    KnowledgeDocument("refund-v1", "Returns are accepted within seven days of delivery.",
                      "manual:refund-v1", "Returns policy"),
))
retriever = KeywordKnowledgeRetriever(store)
question = "returns delivery"
policy = AsyncKnowledgeContextPolicy(question, retriever, limit=3)
result = await runtime.run(question, history_policy=policy)
```

Construct a policy with the current explicit query per Run to avoid stale-query reuse. Empty Sessions also retrieve. Ordering is history → knowledge USER data → current input. No matches add no empty message. `include_history=False` skips the entire policy, including retrieval. Resuming an existing Run uses its saved checkpoint rather than retrieving again.

This template composes USER/ASSISTANT text history only. Its default history projection ignores recorded media, and composition strips name/metadata. Replace the policy for media, other roles or custom content types; this template does not automatically handle them.

## Vector assembly

```python
from w_agent import VectorKnowledgeRetriever
from my_application import authorized_embedder, authorized_vector_backend, document_store

retriever = VectorKnowledgeRetriever(
    authorized_embedder, authorized_vector_backend, document_store,
    point_ids=(101, 102),  # Host-selected retrieval scope.
)
policy = AsyncKnowledgeContextPolicy(question, retriever)
```

Use the [read-only Qdrant template](./vector-retrieval.en.md) or a custom backend. Hosts prebuild the index; IDs must exactly match the document store, with canonical UUID strings for Qdrant. Embedding model/dimension/index semantic compatibility is not verified. `point_ids=None` explicitly permits whole-configured-collection search; an empty tuple invokes no component. Supplied candidates are rechecked against every returned ID, with at most 1024 candidates and 128 results. Duplicate matches, missing/extra/duplicate documents and invalid return shapes fail closed rather than being silently dropped.

Hosts enforce document-store authorization; candidate lists are not ACLs and Python plugins are not sandboxes. There is no atomic snapshot across vector/document stores. Matching IDs do not prove matching content versions: use host-managed versioned IDs and coordinate both stores where required.

## Content, safety and accounting boundaries

- Output is versioned JSON retaining each document's ID/source/title/text, labeled as untrusted reference data in a USER message, never promoted to system/developer authority. JSON escaping and labels are not prompt-injection prevention; citation authenticity is not verified. Hosts still own tool permissions, sensitive-action approval and model-destination review.
- Selecting the policy authorizes its query callbacks and disclosure of retrieved bodies to the selected model; there is no built-in approval dialog. Custom history policies can also contact services. Retrieval does not write indexes, download citations or invoke tools automatically.
- Queries allow at most 4096 UTF-8 bytes and results at most 128 documents. Vector document fields default to a combined 1 MiB limit. The context policy uses `SessionHistoryLimits`: raw history and retrieved documents each obey `max_input_bytes`; final history plus knowledge JSON/labels obey `max_output_bytes` and `max_messages`. Oversized output fails without truncation. Current inputs, system prompts and Provider serialization overhead are outside these text bounds; these are not token limits.
- Raw history is checked before history callbacks and retrieval. Already-paid preparation can fail at final output validation without refund. The default 30-second coroutine deadline covers the whole preparation. Public errors omit queries/bodies/underlying exception messages; no automatic retries occur. Cancellation propagates with cooperative cleanup, but blocking or cancellation-ignoring extensions cannot be forcibly terminated.
- Embedder/backend/store lifecycles are host-owned. Queries, vectors and documents may be sensitive. Hidden repr fields are not encryption, IDs remain visible, and custom logs can disclose data.
- The policy does not mutate Sessions. SessionManager does not append synthetic knowledge as new user input, but model answers may quote it and Run results/checkpoints/host observability may retain it. This is not a no-persistence guarantee.
- Preparation embedding/retrieval costs do not automatically enter Run TokenBudget, shared pools or Session totals. Hosts meter these explicitly; unknown costs are not zero. Knowledge included in the main model request follows normal Provider-reported input-token accounting, not a preparation ledger.

## Progress and remaining work

Local regressions pass for document protocols, memory/keyword templates, vector resolution, and context wiring. Compose them with [knowledge tools](./knowledge-tools.en.md), [versioned snapshots](./knowledge-ingestion.en.md), [snapshot vectors](./knowledge-vectors.en.md), and separate [index manifests/receipt journals](./knowledge-index-journal.en.md); consult each component's own validation status. Generic tool entries are not dedicated retrieval UI. Live-service acceptance and remaining plans are tracked in the [roadmap](./roadmap.en.md).

## Retrieval and assembly extensions

See [knowledge retrieval](knowledge-retrieval.en.md) for local BM25, hybrid fusion, and replaceable reranking. Dedicated [Workflow and evaluation assembly](knowledge-workflow-evaluation.en.md) reuses the existing retriever and context boundaries.

