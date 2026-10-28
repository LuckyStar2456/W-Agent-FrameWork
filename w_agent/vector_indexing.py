"""Explicit history embedding preparation and plan-bound Qdrant upserts.

This module never writes merely because a search or Agent Run occurred. Hosts
authorize embedding and remote overwrite separately, and own their accounting.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field

from w_agent.session_context_templates import SessionHistoryLimits, SessionHistoryTurn
from w_agent.tools.http_adapter import HttpToolRequest, HttpToolResponse
from w_agent.vector_retrieval import (
    AsyncTextEmbedder, QdrantVectorSearch, VectorRetrievalError,
    _integer, _point_id, _reject_constant, _timeout, _unique_object, _vector,
    qdrant_history_point_id,
)


@dataclass(frozen=True, slots=True)
class DenseVectorPoint:
    """Immutable vector and opaque identity; no text, metadata or write authority."""

    point_id: str | int
    vector: tuple[float, ...] = field(repr=False)

    def __post_init__(self) -> None:
        valid_id = (type(self.point_id) is int and 0 <= self.point_id < 2**64) or (
            isinstance(self.point_id, str) and 1 <= len(self.point_id.encode("utf-8")) <= 512
        )
        if not valid_id:
            raise ValueError("vector point identity is invalid")
        object.__setattr__(self, "vector", _vector(self.vector))


def qdrant_history_embedding_text(turn: SessionHistoryTurn) -> str:
    """Explicit text disclosure helper; content excludes Run/name/metadata fields.

    Indexers must use this versioned rendering consistently when embedding. It is
    not a prompt-injection defense or a tokenizer, and does not call any model.
    """
    try:
        qdrant_history_point_id("validation", turn)  # Reuse bounded segment checks.
        value = {
            "format": "wagent-history-embedding-v1",
            "messages": [
                {"role": message.role.value, "text": [block.text for block in message.content]}
                for message in turn.messages
            ],
        }
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raise VectorRetrievalError("history embedding text preparation failed") from None


async def prepare_qdrant_history_points(
    namespace: str,
    turns: tuple[SessionHistoryTurn, ...],
    embedder: AsyncTextEmbedder,
    *,
    confirm_embedding: bool = False,
    limits: SessionHistoryLimits | None = None,
    timeout: float = 30.0,
) -> tuple[DenseVectorPoint, ...]:
    """Validate a batch, then sequentially embed with explicit host consent.

    This does not create a collection or write points. Failure/cancellation may
    follow billed embedding calls; no rollback, retry or zero-cost inference.
    """
    try:
        if confirm_embedding is not True:
            raise ValueError("embedding consent required")
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", namespace):
            raise ValueError("invalid index namespace")
        _timeout(timeout)
        resolved_limits = limits if limits is not None else SessionHistoryLimits()
        if not isinstance(resolved_limits, SessionHistoryLimits):
            raise ValueError("invalid history limits")
        if not isinstance(turns, tuple) or len(turns) > 128:
            raise ValueError("invalid indexing batch")
        if not callable(getattr(embedder, "embed", None)):
            raise ValueError("invalid embedder")
        ids = tuple(qdrant_history_point_id(namespace, turn) for turn in turns)
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate history identity")
        if sum(len(turn.messages) for turn in turns) > resolved_limits.max_messages:
            raise ValueError("history exceeds message bound")
        texts = tuple(qdrant_history_embedding_text(turn) for turn in turns)
        # Bound the actual disclosed representation, including JSON/role overhead.
        if sum(len(text.encode("utf-8")) for text in texts) > resolved_limits.max_input_bytes:
            raise ValueError("embedding representation exceeds byte bound")
        points: list[DenseVectorPoint] = []
        dimensions: int | None = None
        async with asyncio.timeout(timeout):
            for identity, text in zip(ids, texts, strict=True):
                vector = _vector(await embedder.embed(text))
                if dimensions is not None and len(vector) != dimensions:
                    raise ValueError("inconsistent embedding dimensions")
                dimensions = len(vector)
                points.append(DenseVectorPoint(identity, vector))
        return tuple(points)
    except Exception:
        raise VectorRetrievalError("history vector preparation failed; prior embedding calls may be billed") from None


def _body(points: tuple[DenseVectorPoint, ...], vector_name: str | None) -> dict[str, object]:
    return {"points": [
        {
            "id": point.point_id,
            "vector": {vector_name: list(point.vector)} if vector_name is not None else list(point.vector),
            "payload": {},
        }
        for point in points
    ]}


@dataclass(frozen=True, slots=True)
class QdrantUpsertPlan:
    """Immutable exact target and vector contents, never a permission grant.

    IDs may overwrite existing points, clearing payload/other vector state. Use
    dedicated host-managed collections. Digests contain no credential but are not
    signatures, secrets, one-shot capabilities or a substitute for host approval.
    """

    endpoint: str = field(repr=False)
    vector_name: str | None
    points: tuple[DenseVectorPoint, ...] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise ValueError("upsert endpoint is invalid")
        if self.vector_name is not None and (
            not isinstance(self.vector_name, str) or not self.vector_name
            or len(self.vector_name.encode("utf-8")) > 128
        ):
            raise ValueError("upsert vector name is invalid")
        if not isinstance(self.points, tuple):
            raise ValueError("upsert points must be a tuple")
        _integer(len(self.points), 128)
        normalized: list[DenseVectorPoint] = []
        for point in self.points:
            if not isinstance(point, DenseVectorPoint):
                raise ValueError("upsert point is invalid")
            normalized.append(DenseVectorPoint(_point_id(point.point_id), point.vector))
        if len({point.point_id for point in normalized}) != len(normalized):
            raise ValueError("upsert identities must be unique")
        if len({len(point.vector) for point in normalized}) != 1:
            raise ValueError("upsert dimensions must agree")
        object.__setattr__(self, "points", tuple(normalized))

    @property
    def digest(self) -> str:
        data = {
            "format": "wagent-qdrant-upsert-v1", "method": "PUT",
            "endpoint": self.endpoint, "query": {"wait": "true"},
            "body": _body(self.points, self.vector_name),
        }
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class QdrantWriteResult:
    """Backend acknowledgement, not a claim of retrieval relevance or permanence."""

    plan_digest: str
    point_count: int
    status: str
    operation_id: int | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.plan_digest, str) or len(self.plan_digest) != 64
                or any(char not in "0123456789abcdef" for char in self.plan_digest)):
            raise ValueError("write result digest is invalid")
        _integer(self.point_count, 128)
        if self.status not in {"acknowledged", "completed"}:
            raise ValueError("write result status is invalid")
        if self.operation_id is not None and (
            type(self.operation_id) is not int or not 0 <= self.operation_id < 2**64
        ):
            raise ValueError("write operation identity is invalid")

    @property
    def applied(self) -> bool:
        return self.status == "completed"


class VectorIndexWriteError(RuntimeError):
    """A refusal before send, or an indeterminate outcome after transport entry."""

    def __init__(self, *, may_have_written: bool) -> None:
        self.may_have_written = may_have_written
        super().__init__(
            "vector index write outcome unknown; inspect remote state before retry"
            if may_have_written else "vector index write refused before transport"
        )


@dataclass(frozen=True, slots=True)
class QdrantVectorWriter:
    """Explicit upsert service borrowing a validated Qdrant endpoint/transport.

    Reads never call it. No automatic create, deletion, synchronization, retries
    or operation polling. The host must authorize overwrite of the exact plan.
    """

    backend: QdrantVectorSearch = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.backend, QdrantVectorSearch):
            raise ValueError("writer needs Qdrant endpoint settings")

    @property
    def endpoint(self) -> str:
        return f"{self.backend.base_url.rstrip('/')}/collections/{self.backend.collection}/points"

    def plan(self, points: tuple[DenseVectorPoint, ...]) -> QdrantUpsertPlan:
        """Pure preparation: no embedding, network access or writes."""
        try:
            plan = QdrantUpsertPlan(self.endpoint, self.backend.vector_name, points)
            self._validated_body(plan)
            return plan
        except Exception:
            raise VectorIndexWriteError(may_have_written=False) from None

    def _validated_body(self, plan: QdrantUpsertPlan) -> dict[str, object]:
        if (not isinstance(plan, QdrantUpsertPlan) or plan.endpoint != self.endpoint
                or plan.vector_name != self.backend.vector_name):
            raise ValueError("plan targets another index")
        body = _body(plan.points, plan.vector_name)
        if len(json.dumps(body, allow_nan=False).encode("utf-8")) > self.backend.max_request_bytes:
            raise ValueError("upsert request exceeds byte bound")
        return body

    async def upsert(self, plan: QdrantUpsertPlan, *, confirm_digest: str) -> QdrantWriteResult:
        """Send once after exact-plan host confirmation; cancellation propagates.

        Never feed an untrusted plan and its self-declared digest straight here.
        Same-plan repeated calls are explicit overwrites, not deduplicated writes.
        """
        entered = False
        try:
            body = self._validated_body(plan)
            digest = plan.digest
            if not isinstance(confirm_digest, str) or confirm_digest != digest:
                raise ValueError("exact plan confirmation required")
            headers = {"Content-Type": "application/json"}
            if self.backend.api_key is not None:
                headers["api-key"] = self.backend.api_key
            request = HttpToolRequest(
                "PUT", self.endpoint, headers=headers, query={"wait": "true"}, json_body=body,
                max_response_bytes=self.backend.max_response_bytes,
            )
            async with asyncio.timeout(self.backend.timeout):
                entered = True  # A borrowed transport may write before its first await.
                response = await self.backend.transport.send(request)
            if (not isinstance(response, HttpToolResponse) or not 200 <= response.status < 300
                    or len(response.body) > self.backend.max_response_bytes):
                raise ValueError("write response unavailable")
            payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError("write response unsuccessful")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError("write response has no receipt")
            return QdrantWriteResult(digest, len(plan.points), result.get("status"), result.get("operation_id"))
        except Exception:
            raise VectorIndexWriteError(may_have_written=entered) from None
