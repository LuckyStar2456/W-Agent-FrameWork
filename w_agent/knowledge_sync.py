"""Version-independent source-bound vectors and explicitly approved sync plans.

This is a separate mutable-index identity scheme. Existing snapshot-bound v1
indexes are not migrated. Deleting stale points can invalidate older versions'
remote retrieval; archived source text remains available locally.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from w_agent.knowledge_context import InMemoryKnowledgeDocumentStore, KnowledgeDocument, VectorKnowledgeRetriever
from w_agent.knowledge_files import _digest
from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_provenance import TracedKnowledgeImport, compare_knowledge_imports
from w_agent.knowledge_vectors import _DimensionCheckedEmbedder, knowledge_document_embedding_text
from w_agent.vector_indexing import DenseVectorPoint, QdrantUpsertPlan, QdrantWriteResult, VectorIndexWriteError
from w_agent.vector_retrieval import AsyncTextEmbedder, DenseVectorSearch, _integer, _point_id, _reject_constant, _timeout, _unique_object, _vector

MAX_SYNC_BYTES = 256 * 1024 * 1024


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class KnowledgeSyncError(RuntimeError):
    """Fixed public code; pending/unknown journal states require inspection."""


def _canonical_sync_endpoint(endpoint: str) -> str:
    """Require one unambiguous spelling; DNS aliases remain host-owned.

    Reject encoded/dot/empty path segments, credentials, query/fragment, host
    case variants and explicit default ports. Caller fixes configuration instead
    of silently changing the approved target. Reverse-proxy prefixes are allowed.
    """
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > 4096 or any(ord(char) <= 32 or ord(char) == 127 for char in endpoint):
        raise ValueError("sync endpoint must be canonical")
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("sync endpoint must be canonical")
    host = parsed.hostname
    if ":" in host:
        host = "[" + ipaddress.IPv6Address(host).compressed + "]"
    elif host.endswith(".") or not re.fullmatch(r"[a-z0-9.-]+", host):
        raise ValueError("sync endpoint must be canonical")
    port = parsed.port
    if port is not None and port != (80 if parsed.scheme == "http" else 443):
        host += ":" + str(port)
    segments = parsed.path.split("/")[1:]
    if (not parsed.path.startswith("/") or len(segments) < 3 or segments[-3] != "collections"
            or segments[-1] != "points" or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} for part in segments)):
        raise ValueError("sync endpoint must be canonical")
    canonical = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if canonical != endpoint:
        raise ValueError("sync endpoint must be canonical")
    return canonical


def knowledge_sync_point_ids(trace: TracedKnowledgeImport, embedding_key: str, dimensions: int) -> tuple[str, ...]:
    """Bind full file provenance/chunk slice/model, deliberately excluding version.

    A change anywhere in a file invalidates that file's points. This is file-level
    incremental indexing, not semantic chunk deduplication. Raw-only changes and
    parser/chunk configuration changes also invalidate identities.
    """
    if not isinstance(trace, TracedKnowledgeImport):
        raise ValueError("sync requires a traced import")
    _label(embedding_key)
    _integer(dimensions, 65536)
    sources = {item.document_id: item for item in trace.imported.records if item.document_id is not None}
    ids = []
    for document, origin in zip(trace.snapshot.documents, trace.origins, strict=True):
        record = sources[origin.document_id]
        identity_fields = [
            "wagent-knowledge-sync-point-v1", trace.snapshot.namespace,
            trace.imported.parser_key, record.to_dict(), trace.chunk_bytes,
            origin.char_start, origin.char_end, origin.byte_start, origin.byte_end,
            document.text, document.source, document.title, embedding_key, dimensions,
        ]
        if trace.splitter == "structure":
            identity_fields[0] = "wagent-knowledge-sync-point-v2"
            identity_fields.append(trace.splitting_config)
        identity = _json(identity_fields)
        ids.append(str(UUID(bytes=hashlib.sha256(identity.encode("utf-8")).digest()[:16])))
    if len(set(ids)) != len(ids):
        raise ValueError("sync point identities collide")
    return tuple(ids)


@dataclass(frozen=True, slots=True)
class KnowledgeSyncIndex:
    """Complete immutable vector cache, not a claim of remote application."""

    trace: TracedKnowledgeImport = field(repr=False)
    embedding_key: str = field(repr=False)
    dimensions: int
    points: tuple[DenseVectorPoint, ...] = field(repr=False)

    def __post_init__(self) -> None:
        ids = knowledge_sync_point_ids(self.trace, self.embedding_key, self.dimensions)
        if (not isinstance(self.points, tuple) or len(self.points) > 1024 or len(self.points) != len(ids)
                or len(ids) * self.dimensions > 1024 * 1024
                or any(not isinstance(point, DenseVectorPoint) or point.point_id != identity
                       or len(point.vector) != self.dimensions for point, identity in zip(self.points, ids))):
            raise ValueError("invalid knowledge sync vector cache")

    @property
    def point_ids(self) -> tuple[str, ...]:
        return tuple(point.point_id for point in self.points)

    def to_dict(self) -> dict:
        return {"format": "wagent-knowledge-sync-index-v1", "trace": json.loads(self.trace.to_json()),
                "embedding_key": self.embedding_key, "dimensions": self.dimensions,
                "points": [{"id": point.point_id, "vector": list(point.vector)} for point in self.points]}

    def to_json(self) -> str:
        return _json(self.to_dict())

    @property
    def digest(self) -> str:
        return _sha(self.to_json())

    @classmethod
    def from_dict(cls, value: dict) -> KnowledgeSyncIndex:
        if (not isinstance(value, dict) or set(value) != {"format", "trace", "embedding_key", "dimensions", "points"}
                or value["format"] != "wagent-knowledge-sync-index-v1"
                or not isinstance(value["points"], list) or len(value["points"]) > 1024):
            raise ValueError("invalid sync index")
        payload = _json(value["trace"])
        trace = TracedKnowledgeImport.from_json(payload, expected_digest=_sha(payload))
        points = []
        for item in value["points"]:
            if not isinstance(item, dict) or set(item) != {"id", "vector"} or not isinstance(item["vector"], list):
                raise ValueError("invalid sync point")
            points.append(DenseVectorPoint(item["id"], tuple(item["vector"])))
        return cls(trace, value["embedding_key"], value["dimensions"], tuple(points))


async def prepare_knowledge_sync_index(
    trace: TracedKnowledgeImport, embedding_key: str, dimensions: int,
    embedder: AsyncTextEmbedder | None = None, *, previous: KnowledgeSyncIndex | None = None,
    confirm_embedding: bool = False, confirm_reuse_digest: str | None = None,
    max_input_bytes: int = 16 * 1024 * 1024, timeout: float = 30.0,
) -> KnowledgeSyncIndex:
    """Reuse exact old vectors; only new/changed-file chunks reach the embedder.

    A version-only change makes zero embedding calls and needs no embedding
    consent, but reuse requires confirmation of the exact previous cache digest.
    Limits are checked for the whole changed selection before calls.
    Partial paid work is not automatically retried or reported as rolled back.
    """
    try:
        if type(confirm_embedding) is not bool:
            raise ValueError
        _integer(max_input_bytes, 32 * 1024 * 1024)
        _timeout(timeout)
        if previous is not None and (not isinstance(previous, KnowledgeSyncIndex)
                                      or previous.trace.snapshot.namespace != trace.snapshot.namespace):
            raise ValueError
        if previous is not None:
            # A matching caller-provided model label alone never admits a cache.
            KnowledgeSyncIndex.from_dict(previous.to_dict())
        # Reject manually assembled incomplete traces before trusting cache keys.
        TracedKnowledgeImport.from_json(trace.to_json(), expected_digest=trace.digest)
        ids = knowledge_sync_point_ids(trace, embedding_key, dimensions)
        if len(ids) * dimensions > 1024 * 1024:
            raise ValueError
        cached = {point.point_id: point for point in previous.points} if previous is not None else {}
        if any(identity in cached for identity in ids) and confirm_reuse_digest != previous.digest:
            raise ValueError
        missing = [(identity, knowledge_document_embedding_text(document))
                   for identity, document in zip(ids, trace.snapshot.documents) if identity not in cached]
        if sum(len(text.encode("utf-8")) for _, text in missing) > max_input_bytes:
            raise ValueError
        if missing and (confirm_embedding is not True or not callable(getattr(embedder, "embed", None))):
            raise ValueError
        async with asyncio.timeout(timeout):
            for identity, text in missing:
                vector = _vector(await embedder.embed(text))
                if len(vector) != dimensions:
                    raise ValueError
                cached[identity] = DenseVectorPoint(identity, vector)
        return KnowledgeSyncIndex(trace, embedding_key, dimensions, tuple(cached[identity] for identity in ids))
    except Exception:
        raise KnowledgeSyncError("knowledge-sync-preparation-failed-prior-calls-may-be-billed") from None


@dataclass(frozen=True, slots=True)
class QdrantDeletePlan:
    """Exact nonempty point-ID deletion; never a broad filter or collection drop."""

    endpoint: str = field(repr=False)
    point_ids: tuple[str | int, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint or len(self.endpoint) > 4096:
            raise ValueError("invalid delete endpoint")
        if not isinstance(self.point_ids, tuple) or not 1 <= len(self.point_ids) <= 128:
            raise ValueError("invalid delete selection")
        ids = tuple(_point_id(identity) for identity in self.point_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate delete identities")
        object.__setattr__(self, "point_ids", ids)

    @property
    def digest(self) -> str:
        return _sha(_json({"format": "wagent-qdrant-delete-v1", "method": "POST", "endpoint": self.endpoint,
                           "query": {"wait": "true"}, "body": {"points": list(self.point_ids)}}))


@dataclass(frozen=True, slots=True)
class KnowledgeSyncPlan:
    """Exact previous/new states and independently approved upsert/delete batches.

    endpoint denotes a dedicated collection's points URL. One managed lineage per
    endpoint is enforced by the default journal, including named-vector changes.
    Old snapshot-bound indexes cannot be used as an implicit predecessor.
    """

    endpoint: str = field(repr=False)
    vector_name: str | None
    current: KnowledgeSyncIndex = field(repr=False)
    previous: KnowledgeSyncIndex | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _canonical_sync_endpoint(self.endpoint)
        if self.vector_name is not None:
            _label(self.vector_name)
        if not isinstance(self.current, KnowledgeSyncIndex) or (self.previous is not None and not isinstance(self.previous, KnowledgeSyncIndex)):
            raise ValueError("invalid sync indexes")
        if self.previous is not None:
            if self.previous.trace.snapshot.namespace != self.current.trace.snapshot.namespace:
                raise ValueError("sync namespaces differ")
            old = {point.point_id: point.vector for point in self.previous.points}
            if any(point.point_id in old and point.vector != old[point.point_id] for point in self.current.points):
                raise ValueError("same content identity cannot replace cached vectors")

    @property
    def upsert_points(self) -> tuple[DenseVectorPoint, ...]:
        old = set(self.previous.point_ids) if self.previous is not None else set()
        return tuple(point for point in self.current.points if point.point_id not in old)

    @property
    def delete_ids(self) -> tuple[str, ...]:
        current = set(self.current.point_ids)
        return tuple(identity for identity in self.previous.point_ids if identity not in current) if self.previous is not None else ()

    @property
    def batches(self) -> tuple[QdrantUpsertPlan | QdrantDeletePlan, ...]:
        points, removed = self.upsert_points, self.delete_ids
        return (tuple(QdrantUpsertPlan(self.endpoint, self.vector_name, points[start:start + 128]) for start in range(0, len(points), 128))
                + tuple(QdrantDeletePlan(self.endpoint.rstrip("/") + "/delete", removed[start:start + 128]) for start in range(0, len(removed), 128)))

    @property
    def upsert_digest(self) -> str:
        return _sha(_json(["wagent-sync-upserts-v1", self.digest, [batch.digest for batch in self.batches if isinstance(batch, QdrantUpsertPlan)]]))

    @property
    def delete_digest(self) -> str:
        return _sha(_json(["wagent-sync-deletes-v1", self.digest, [batch.digest for batch in self.batches if isinstance(batch, QdrantDeletePlan)]]))

    @property
    def target_key(self) -> str:
        return _sha(self.endpoint)

    def to_json(self) -> str:
        return _json({"format": "wagent-knowledge-sync-plan-v1", "endpoint": self.endpoint,
                      "vector_name": self.vector_name, "current": self.current.to_dict(),
                      "previous": self.previous.to_dict() if self.previous is not None else None})

    @property
    def digest(self) -> str:
        return _sha(self.to_json())

    def summary(self) -> dict:
        result = {"plan_digest": self.digest, "upsert_digest": self.upsert_digest, "delete_digest": self.delete_digest,
                  "upsert_points": len(self.upsert_points), "delete_points": len(self.delete_ids),
                  "reused_points": len(self.current.points) - len(self.upsert_points),
                  "namespace": self.current.trace.snapshot.namespace, "version": self.current.trace.snapshot.version,
                  "previous_index_digest": self.previous.digest if self.previous is not None else None,
                  "current_index_digest": self.current.digest, "remote_verified": False}
        if self.previous is not None:
            delta = compare_knowledge_imports(self.previous.trace.imported, self.current.trace.imported)
            result["files"] = {name: len(getattr(delta, name)) for name in ("added", "changed", "removed", "unchanged")}
        return result

    @classmethod
    def from_json(cls, payload: str, *, expected_digest: str) -> KnowledgeSyncPlan:
        try:
            _digest(expected_digest)
            if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_SYNC_BYTES or _sha(payload) != expected_digest:
                raise ValueError
            value = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if set(value) != {"format", "endpoint", "vector_name", "current", "previous"} or value["format"] != "wagent-knowledge-sync-plan-v1":
                raise ValueError
            result = cls(value["endpoint"], value["vector_name"], KnowledgeSyncIndex.from_dict(value["current"]),
                         KnowledgeSyncIndex.from_dict(value["previous"]) if value["previous"] is not None else None)
            if result.to_json() != payload:
                raise ValueError
            return result
        except Exception:
            raise KnowledgeSyncError("knowledge-sync-plan-invalid") from None


class KnowledgeSyncWriter(Protocol):
    endpoint: str
    vector_name: str | None

    async def upsert(self, plan: QdrantUpsertPlan, *, confirm_digest: str) -> QdrantWriteResult: ...

    async def delete(self, plan: QdrantDeletePlan, *, confirm_digest: str) -> QdrantWriteResult: ...


@dataclass(frozen=True, slots=True)
class KnowledgeSyncStatus:
    plan_digest: str
    outcomes: tuple[str, ...]
    finished: bool

    def __post_init__(self) -> None:
        _digest(self.plan_digest)
        if (not isinstance(self.outcomes, tuple) or len(self.outcomes) > 16
                or any(value not in {"ready", "pending", "unknown", "acknowledged", "completed", "not-sent"} for value in self.outcomes)
                or type(self.finished) is not bool or self.finished != all(value == "completed" for value in self.outcomes)):
            raise ValueError("invalid sync status")


@dataclass(frozen=True, slots=True)
class KnowledgeSyncRetryRecord:
    """Immutable previous not-sent attempt; the new attempt is generation + 1."""

    batch: int
    generation: int
    retry_id: str
    prior_outcome: str = "not-sent"

    def __post_init__(self) -> None:
        _label(self.retry_id)
        if (type(self.batch) is not int or not 0 <= self.batch < 16
                or type(self.generation) is not int or not 0 <= self.generation < 64
                or self.prior_outcome != "not-sent"):
            raise ValueError("invalid sync retry record")


def knowledge_sync_retry_digest(plan_digest: str, batch: int, generation: int) -> str:
    """Separate approval of retrying one exact, confirmed-not-sent generation."""
    _digest(plan_digest)
    KnowledgeSyncRetryRecord(batch, generation, "validation")
    return _sha(_json(["wagent-knowledge-sync-retry-v1", plan_digest, batch, generation]))


class KnowledgeSyncJournal(Protocol):
    """Durably stage exact vectors and serialize a collection's head progression."""

    async def stage(self, plan: KnowledgeSyncPlan, *, confirm_write: bool = False) -> KnowledgeSyncStatus: ...

    async def inspect(self, plan_digest: str) -> KnowledgeSyncStatus: ...

    async def load_plan(self, plan_digest: str) -> KnowledgeSyncPlan: ...

    async def claim(self, plan_digest: str, batch: int, *, confirm_write: bool = False) -> None: ...

    async def record(self, plan_digest: str, batch: int, outcome: str, *, receipt: QdrantWriteResult | None = None,
                     confirm_write: bool = False) -> KnowledgeSyncStatus: ...


async def execute_knowledge_sync(
    plan: KnowledgeSyncPlan, writer: KnowledgeSyncWriter, journal: KnowledgeSyncJournal, *,
    confirm_plan_digest: str, confirm_upsert_digest: str | None = None,
    confirm_delete_digest: str | None = None, confirm_record: bool = False,
) -> KnowledgeSyncStatus:
    """Upsert all changed batches, then delete explicitly approved stale IDs.

    Each batch is durably claimed before send. Resume skips completed batches;
    pending/unknown/acknowledged/not-sent batches are never replayed. Journal
    failure after a send preserves the pending barrier. No rollback is claimed.
    """
    if (not isinstance(plan, KnowledgeSyncPlan) or confirm_record is not True
            or confirm_plan_digest != plan.digest or writer.endpoint != plan.endpoint
            or writer.vector_name != plan.vector_name
            or (plan.upsert_points and confirm_upsert_digest != plan.upsert_digest)
            or (plan.delete_ids and confirm_delete_digest != plan.delete_digest)):
        raise KnowledgeSyncError("knowledge-sync-confirmation-invalid")
    status = await journal.stage(plan, confirm_write=True)
    batches = plan.batches
    if not isinstance(status, KnowledgeSyncStatus) or status.plan_digest != plan.digest or len(status.outcomes) != len(batches):
        raise KnowledgeSyncError("knowledge-sync-journal-invalid")
    for index, batch in enumerate(batches):
        if status.outcomes[index] == "completed":
            continue
        if status.outcomes[index] != "ready":
            raise KnowledgeSyncError("knowledge-sync-unresolved-no-replay")
        await journal.claim(plan.digest, index, confirm_write=True)
        try:
            operation = writer.upsert if isinstance(batch, QdrantUpsertPlan) else writer.delete
            receipt = await operation(batch, confirm_digest=batch.digest)
            count = len(batch.points) if isinstance(batch, QdrantUpsertPlan) else len(batch.point_ids)
            if not isinstance(receipt, QdrantWriteResult) or receipt.plan_digest != batch.digest or receipt.point_count != count:
                raise KnowledgeSyncError("knowledge-sync-receipt-invalid")
        except (Exception, asyncio.CancelledError) as error:
            outcome = "not-sent" if isinstance(error, VectorIndexWriteError) and not error.may_have_written else "unknown"
            try:
                await journal.record(plan.digest, index, outcome, confirm_write=True)
            except (Exception, asyncio.CancelledError):
                pass
            raise
        previous_status = status
        status = await journal.record(plan.digest, index, receipt.status, receipt=receipt, confirm_write=True)
        if (not isinstance(status, KnowledgeSyncStatus) or status.plan_digest != plan.digest
                or len(status.outcomes) != len(batches) or status.outcomes[index] != receipt.status
                or status.outcomes[:index] != previous_status.outcomes[:index]
                or status.outcomes[index + 1:] != previous_status.outcomes[index + 1:]):
            raise KnowledgeSyncError("knowledge-sync-journal-invalid")
        if receipt.status != "completed":
            return status  # Acknowledgement is not sufficient for deletion or next batch.
    return status


@dataclass(frozen=True, slots=True)
class SyncVectorKnowledgeRetriever:
    """Resolve stable sync IDs to the current archive's local snapshot documents."""

    index: KnowledgeSyncIndex = field(repr=False)
    embedder: AsyncTextEmbedder = field(repr=False)
    backend: DenseVectorSearch = field(repr=False)

    async def retrieve(self, query: str, *, limit: int) -> tuple[KnowledgeDocument, ...]:
        originals = dict(zip(self.index.point_ids, self.index.trace.snapshot.documents))
        store = InMemoryKnowledgeDocumentStore(tuple(KnowledgeDocument(identity, item.text, item.source, item.title)
                                                     for identity, item in originals.items()))
        delegate = VectorKnowledgeRetriever(_DimensionCheckedEmbedder(self.embedder, self.index.dimensions),
                                             self.backend, store, point_ids=self.index.point_ids)
        return tuple(originals[item.document_id] for item in await delegate.retrieve(query, limit=limit))
