# Explicit history-vector preparation and Qdrant writes

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./vector-indexing.md)

2.0.0 Experimental: local regressions pass; included in 2.0.0 and outside 2.0.0a9. Live services, billing, quality and manual production UI acceptance remain outstanding.

## Two independent side-effect stages

[History retrieval](./vector-retrieval.en.md) remains read-only and never triggers indexing. Preparation functions, immutable data and the writer are independently replaceable. They do not replace Agent Loop, grant model-tool permissions or discover/import host code automatically.

1. `prepare_qdrant_history_points(namespace, turns, embedder, confirm_embedding=True)` validates the entire batch, duplicate IDs and text size before sequentially invoking the host Embedder. Consent permits disclosing selected history bodies to that callback, separately from sending a search query.
2. `QdrantVectorWriter.plan(points)` creates an immutable `QdrantUpsertPlan` locally without model/network access. After reviewing destination, point IDs, vector contents and overwrite risk, hosts send once using `upsert(plan, confirm_digest=reviewed_digest)`.

The [Qdrant Upsert API](https://api.qdrant.tech/api-reference/points/upsert-points) overwrites existing points with matching IDs. This template sends `PUT /collections/{collection}/points?wait=true`, containing IDs, default/named vectors and empty payloads. It is not insert-only and does not guarantee preservation of existing payloads or other vectors. Use dedicated host-managed collections and review conflicts before approval; existence is not checked automatically.

## Assembly example

```python
from w_agent import (
    MessageRole, ModelMessage, SessionHistoryTurn,
    QdrantVectorSearch, QdrantVectorWriter, prepare_qdrant_history_points,
)
from my_application import authorized_embedder, review_index_overwrite

# Select contiguous Run text segments matching the history policy.
turns = (SessionHistoryTurn("run-1", (
    ModelMessage.text(MessageRole.USER, "What is the refund policy?"),
    ModelMessage.text(MessageRole.ASSISTANT, "Confirmed policy summary..."),
)),)
points = await prepare_qdrant_history_points(
    "support-session-v1", turns, authorized_embedder, confirm_embedding=True,
)
backend = QdrantVectorSearch(
    "http://127.0.0.1:6333", "support_history", vector_name="dense",
)
writer = QdrantVectorWriter(backend)
plan = writer.plan(points)
# Host callback obtains real approval; never trust a stranger plan's own digest.
reviewed_digest = await review_index_overwrite(plan)
receipt = await writer.upsert(plan, confirm_digest=reviewed_digest)
if not receipt.applied:
    # Only acknowledged: inspect status, never display completed or auto-retry.
    pass
```

Hosts must precreate the collection with dimension/distance/named-vector settings matching the chosen embedding model. This example does not execute on import or documentation loading. The same backend can serve `QdrantSessionHistoryRetriever`; indexing/retrieval namespace/text/Run-ID conventions must agree.

Hosts may alternatively create `DenseVectorPoint(point_id, vector)` themselves and feed another store/writer, or this template's planner. Generic IDs accept bounded strings/uint64; Qdrant plans require UUID/uint64. Preparation does not depend on Writer, and Writer never invokes Embedder.

## Text, plan and result contracts

- `qdrant_history_embedding_text(turn)` locally renders versioned JSON containing ordered roles/text blocks, excluding Run IDs, names, metadata and Session titles. The output contains sensitive history, is not a prompt-injection defense and is not automatically redacted.
- IDs reuse `qdrant_history_point_id(namespace, turn)` without names/metadata. Changed text or namespace creates a new ID; old points are not removed. Writing unchanged IDs is still an explicit overwrite, not existing-point skipping or incremental synchronization.
- At most 128 segments per preparation batch. Actual JSON/role/text UTF-8 bytes disclosed to Embedder obey `SessionHistoryLimits.max_input_bytes`. Embeddings must be finite numeric tuples with consistent dimensions. Empty preparation performs no embedding but cannot create an empty upsert plan.
- Points/plans are immutable, and repr hides vectors/targets/point sets. Reading fields, printing requests or logging Embedder arguments still exposes sensitive information. Vectors are not anonymized data; IDs/digests are not secrets.
- Plan digests use SHA-256 over the version, PUT method, exact endpoint, wait parameter, ordered IDs/vectors and empty payloads. Changed target/content requires new review. API keys are excluded, permitting credential rotation; the host still reviews which account/permissions are used.
- A digest is not a signature, single-use token or isolation boundary. `confirm_digest` must follow trusted host approval, never automatic acceptance of user/model/shared-package digests. Explicit repeated execution is allowed but neither deduplicated nor retried automatically. Custom Python/transports can bypass library-level checks.
- Writer borrows backend credentials, vector name, transport, timeout and byte limits. It rejects plans for another target/vector name and rechecks body size before sending. Oversized plans may be refused after paid embedding, so hosts choose appropriate batch sizes/dimensions upfront.
- `QdrantWriteResult` includes `plan_digest`, `point_count`, `status` and optional `operation_id`. Only `completed` makes `applied=True`; `acknowledged` does not imply eventual success or trigger polling. Completion does not prove retrieval quality, billing authenticity or permanence against subsequent writers.
- `VectorIndexWriteError.may_have_written=False` means this template did not enter the transport. True means it entered and the outcome is indeterminate. HTTP errors, invalid/oversized responses, bad receipts, transport failures and timeouts do not prove zero writes; partial/all writes may have occurred. Inspect remote state before deciding next steps. No rollback, cross-call atomicity or durable receipt ledger is provided.
- Task cancellation propagates `CancelledError`. Started embedding/writes cannot have remote charges/effects undone; hosts retain the plan and execution phase. Failed preparation returns no partial batch, although earlier embedding may be billed. Preparation itself never writes unless the host separately invokes Writer.
- Default timeout is 30 seconds: the full sequential embedding batch for preparation, one request for writes. Default HTTPX resources close per request; injected transport/Embedder objects are borrowed and host-owned. Blocking or cancellation-ignoring extensions cannot be force-terminated.

## Accounting and remaining work

Embedding/retrieval/write costs are not automatically merged into Agent Runs, Sessions or shared pools. Hosts explicitly meter paid callbacks; unknown cost is not zero. These interfaces do not verify model/index semantic compatibility.

Local fake-transport regressions pass for separate consent, bounds, privacy, exact digests, mapping, unknown outcomes, cancellation and preparation→write→retrieval IDs. [Document context](./knowledge-context.en.md), [snapshot vectors](./knowledge-vectors.en.md), journaled plans and build CLI/TUI entries explicitly compose this Writer. [PDF/Office and incremental parsing](./knowledge-import-extensions.en.md) are implemented separately. Collection creation, remote evidence/lookup, differential synchronization, additional embedding templates, real Qdrant acceptance and unified accounting remain incomplete.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
