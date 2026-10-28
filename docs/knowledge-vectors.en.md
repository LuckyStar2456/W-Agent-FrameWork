# Snapshot-bound knowledge vectors and pinned retrieval

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-vectors.md)

2.0.0 Experimental: local regressions pass; included in 2.0.0 and outside 2.0.0a9. Live services, billing, quality and manual production UI acceptance remain outstanding.

## Compose existing components

Locally regression-tested [HTTP embedding and shared-budget templates](./embeddings.en.md) can supply this page's embedder. Explicitly wrap it for budgeting; a shared controller does not automatically associate usage with Run/Session history.

This module connects [versioned knowledge snapshots](./knowledge-ingestion.en.md), host `AsyncTextEmbedder`, existing `DenseVectorPoint` / [explicit Qdrant Writer](./vector-indexing.en.md) and [knowledge retrieval](./knowledge-context.en.md). Identity mapping, embedding, writes and reads remain separate, without requiring a model SDK or owning the Agent Loop.

1. `KnowledgeVectorIndex(snapshot, embedding_key, dimensions)` builds a pure identity map without model/file/network operations.
2. `prepare_knowledge_vectors(index, embedder, confirm_embedding=True)` explicitly discloses selected titles/bodies to the host Embedder and returns vector points; it never writes remotely.
3. Hosts separately plan writes, review destination/overwrite risks and upsert using the reviewed digest. Embedding consent does not authorize writes.
4. `SnapshotVectorKnowledgeRetriever(index, embedder, backend)` searches the same point IDs, resolves local snapshot text and returns original document IDs/sources/titles/bodies. Use it with `knowledge_search_tool()` or `AsyncKnowledgeContextPolicy`.

```python
from w_agent import (
    KnowledgeVectorIndex, QdrantVectorSearch, QdrantVectorWriter,
    SnapshotVectorKnowledgeRetriever, prepare_knowledge_vectors, knowledge_search_tool,
)
from my_application import authorized_embedder, review_exact_upsert

# Host creates snapshot or loads an exact SQLite version.
# Host label covers model/weights/preprocessing revision; 1536 is illustrative.
index = KnowledgeVectorIndex(snapshot, "my-embedding-pipeline-v1", dimensions=1536)
points = await prepare_knowledge_vectors(index, authorized_embedder, confirm_embedding=True)

# Precreate the collection with suitable dimension/distance settings.
backend = QdrantVectorSearch("http://127.0.0.1:6333", "support_knowledge")
writer = QdrantVectorWriter(backend)
plan = writer.plan(points)
reviewed_digest = await review_exact_upsert(plan)  # Real host review, not trust in a self-reported digest.
receipt = await writer.upsert(plan, confirm_digest=reviewed_digest)
if not receipt.applied:
    raise RuntimeError("Index operation is not confirmed completed; inspect remote state")

retriever = SnapshotVectorKnowledgeRetriever(index, authorized_embedder, backend)
binding = knowledge_search_tool(retriever)  # Permission and exact-call approval still apply by default.
```

This example handles a nonempty single-batch snapshot of at most 128 documents that fits request limits. Empty preparation returns an empty tuple and should not create a nonempty upsert plan. For larger snapshots, hosts explicitly select up to 128 original IDs using `document_ids=(...)`, preparing/reviewing/retaining receipts per batch. This is not automatic batching, resumable indexing or cross-batch atomicity.

## Document identity versus vector identity

- `KnowledgeVectorIndex.snapshot_digest` hashes the full canonical snapshot. Each vector UUID binds format, snapshot digest, `embedding_key`, dimension and original document ID. Snapshot version/content/order/citations or embedding label/dimension changes alter point IDs. Different snapshots do not proactively reuse old points.
- `index.point_ids` follows snapshot order; `index.point_id(original_id)` resolves locally. Integer/string IDs remain distinct and booleans are rejected. Even directly constructed snapshots reusing document IDs across versions produce different vector identities when their snapshot digest differs.
- Reloading the same SQLite snapshot with the same format/embedding label/dimension rebuilds the same mapping, without a latest pointer or ephemeral process state. Optional locally regression-tested [index manifests/durable receipts](./knowledge-index-journal.en.md) are separate and still never replay writes automatically.
- `embedding_key` is a host declaration, not a model identity automatically passed to or verified against Embedder. Preparation/query pipelines must be compatible. The framework checks finite values and declared dimension only; equal dimensions do not establish semantic compatibility. Update the label and rebuild when changing models.
- `KnowledgeVectorIndex` is not proof of remote existence, completeness or successful writes. Digests/point IDs are not authorization, signatures, secrets or anonymization. UUIDs use 128 digest bits, not a mathematical zero-collision guarantee. Backend/collection targets are bound by separate Writer plans, not by this identity map.

## Disclosure, limits and failures

- `knowledge_document_embedding_text(document)` locally renders versioned title/text JSON, excluding source, original ID and namespace/version fields. Those values are not redacted if already present in the body. Rendered output contains knowledge text and should not be automatically logged.
- `confirm_embedding` must be boolean True. All batch identities, duplicates/scope, rendered input bytes and declared-dimension coordinate budgets are checked before the first embedding call. Omitted `document_ids` selects the whole snapshot but rejects more than 128 documents without truncation. Empty selection invokes no Embedder.
- Actual input JSON defaults to 1 MiB per batch, configurable up to 32 MiB. `max_vector_values` defaults to 1,048,576 coordinates, configurable up to 8,388,608. Declared dimension is 1–65,536. Coordinates/bytes are not token/cost limits or exact Python-process memory bounds.
- The default 30-second timeout covers the entire sequential embedding batch. Vectors must be finite numeric tuples of exactly the declared dimension. Failure returns no partial points and never retries automatically; earlier calls may still be billed. Cancellation propagates with cooperative cleanup, not forced termination of blocking/cancellation-ignoring extensions.
- Writer request size can only be checked precisely after vectors exist; a rejected plan does not imply free preparation. Existing full-upsert overwrite semantics, exact-plan approval, acknowledged/applied distinction and unknown-outcome handling apply. No automatic rollback, old-version cleanup, polling or retry occurs.
- Retrieval sends only current snapshot/embedding-bound candidate IDs; empty snapshots invoke neither Embedder nor backend. Wrong query-vector dimensions fail before search. Existing timeout, unique/candidate-ID checks and document-byte limits apply, including original ID fields after remapping. Backend rank is preserved.
- Missing hits may reflect incomplete indexing rather than irrelevant documents. Normal retrieval returns matched subsets and does not verify every candidate's remote existence/vector contents. Hosts should reconcile all batch receipts and retrieval quality before declaring a version ready.
- Bodies come from local snapshots, not remote payloads. Sources are not opened and text is not executed. Candidate filters are not ACLs, labels are not prompt-injection defenses, and hosts own permissions/model destinations/tool approval/sensitive-data handling.
- Embedder/backends/clients are borrowed and host-owned. Embedding/retrieval charges are not automatically merged into Agent/Session/shared budgets; unknown is not zero. Knowledge tools, Session saving and Agent Runs never automatically trigger index preparation or writes.

## Progress and remaining work

Local fake-transport regressions pass for bound IDs, batch preparation, retrieval, original-ID restoration and preparation→write→reopen→retrieval wiring. [Plan actions](./knowledge-plan-actions.en.md), [build recovery](./knowledge-build-recovery.en.md) and journal catalogs provide explicit local lifecycle management. Additional embedding templates, remote evidence/lookup, differential synchronization, cross-store consistency, unified preparation accounting and real Qdrant acceptance remain incomplete.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
