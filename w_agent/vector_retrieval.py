"""Opt-in dense-vector lookup and a read-only Qdrant history selector.

Hosts own endpoint authorization, indexing, embedding costs and borrowed clients.
Nothing is discovered, indexed, retried or imported from configuration implicitly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from w_agent.session_context_templates import SessionHistoryLimits, SessionHistoryTurn
from w_agent.tools.http_adapter import HttpToolRequest, HttpToolResponse, HttpToolTransport, HttpxToolTransport


class VectorRetrievalError(RuntimeError):
    """A retrieval operation failed; messages omit query, credentials and bodies."""


def _integer(value: int, maximum: int) -> None:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("retrieval limit is invalid")


def _timeout(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 3600:
        raise ValueError("retrieval timeout is invalid")


def _point_id(value: str | int) -> str | int:
    if type(value) is int and 0 <= value < 2**64:
        return value
    if isinstance(value, str) and len(value) <= 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    raise ValueError("retrieval point identity is invalid")


def _vector(value: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, tuple) or not 1 <= len(value) <= 65536:
        raise ValueError("retrieval vector must be a bounded nonempty tuple")
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in value):
        raise ValueError("retrieval vector must contain finite numbers")
    return tuple(float(item) for item in value)


@dataclass(frozen=True, slots=True)
class VectorSearchMatch:
    """A match identity and backend-defined score, never remote prompt content."""

    point_id: str | int
    score: float

    def __post_init__(self) -> None:
        valid_id = (type(self.point_id) is int and 0 <= self.point_id < 2**64) or (
            isinstance(self.point_id, str) and 1 <= len(self.point_id.encode("utf-8")) <= 512
        )
        if not valid_id:
            raise ValueError("retrieval match identity is invalid")
        if type(self.score) not in (int, float) or not math.isfinite(self.score):
            raise ValueError("retrieval score must be finite")
        object.__setattr__(self, "score", float(self.score))


class AsyncTextEmbedder(Protocol):
    """Host-authorized embedding callback; accounting and model choice are external."""

    async def embed(self, text: str) -> tuple[float, ...]: ...


class DenseVectorSearch(Protocol):
    """Replaceable lookup; a supplied candidate list must restrict every result."""

    async def search(
        self, vector: tuple[float, ...], *, limit: int,
        point_ids: tuple[str | int, ...] | None = None,
    ) -> tuple[VectorSearchMatch, ...]: ...


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite response number")


@dataclass(frozen=True, slots=True)
class QdrantVectorSearch:
    """Read-only POST points/query template, with no payload or vector disclosure.

    Default HTTPX transport is lazy and closes its per-request client. Injected
    transports are borrowed; their lifecycle, redirects and logging are host-owned.
    A coroutine timeout bounds waiting, not external execution or refund behavior.
    """

    base_url: str = field(repr=False)
    collection: str = field(repr=False)
    api_key: str | None = field(default=None, repr=False)
    vector_name: str | None = None
    score_threshold: float | None = None
    transport: HttpToolTransport | None = field(default=None, repr=False)
    timeout: float = 30.0
    max_response_bytes: int = 1024 * 1024
    max_request_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        _timeout(self.timeout)
        _integer(self.max_response_bytes, 16 * 1024 * 1024)
        _integer(self.max_request_bytes, 16 * 1024 * 1024)
        try:
            if not isinstance(self.base_url, str) or len(self.base_url) > 4096:
                raise ValueError
            if any(ord(char) <= 32 or ord(char) == 127 for char in self.base_url):
                raise ValueError
            parsed = urlsplit(self.base_url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment):
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise ValueError("retrieval endpoint is invalid") from None
        if not isinstance(self.collection, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.collection):
            raise ValueError("retrieval collection is invalid")
        if self.api_key is not None and (
            not isinstance(self.api_key, str) or not 1 <= len(self.api_key) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in self.api_key)
        ):
            raise ValueError("retrieval credential is invalid")
        if self.vector_name is not None and (
            not isinstance(self.vector_name, str) or not self.vector_name
            or len(self.vector_name.encode("utf-8")) > 128
        ):
            raise ValueError("retrieval vector name is invalid")
        if self.score_threshold is not None and (
            type(self.score_threshold) not in (int, float) or not math.isfinite(self.score_threshold)
        ):
            raise ValueError("retrieval score threshold is invalid")
        transport = self.transport if self.transport is not None else HttpxToolTransport(timeout=self.timeout)
        if not callable(getattr(transport, "send", None)):
            raise ValueError("retrieval transport needs send")
        object.__setattr__(self, "transport", transport)

    async def search(
        self, vector: tuple[float, ...], *, limit: int,
        point_ids: tuple[str | int, ...] | None = None,
    ) -> tuple[VectorSearchMatch, ...]:
        try:
            _integer(limit, 128)
            vector = _vector(vector)
            ids = None
            if point_ids is not None:
                if not isinstance(point_ids, tuple) or len(point_ids) > 1024:
                    raise ValueError("invalid candidate list")
                ids = tuple(_point_id(item) for item in point_ids)
                if len(set(ids)) != len(ids):
                    raise ValueError("duplicate candidate")
                if not ids:
                    return ()  # Never translate an empty scope into an unfiltered query.
            body: dict[str, object] = {"query": list(vector), "limit": limit, "with_payload": False, "with_vector": False}
            if ids is not None:
                body["filter"] = {"must": [{"has_id": list(ids)}]}
            if self.vector_name is not None:
                body["using"] = self.vector_name
            if self.score_threshold is not None:
                body["score_threshold"] = self.score_threshold
            if len(json.dumps(body, allow_nan=False).encode("utf-8")) > self.max_request_bytes:
                raise ValueError("request exceeds limit")
            headers = {"Content-Type": "application/json"}
            if self.api_key is not None:
                headers["api-key"] = self.api_key
            request = HttpToolRequest(
                "POST", f"{self.base_url.rstrip('/')}/collections/{self.collection}/points/query",
                headers=headers, json_body=body, max_response_bytes=self.max_response_bytes,
            )
            async with asyncio.timeout(self.timeout):
                response = await self.transport.send(request)
            if (not isinstance(response, HttpToolResponse) or not 200 <= response.status < 300
                    or len(response.body) > self.max_response_bytes):
                raise ValueError("invalid response")
            payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise ValueError("unsuccessful response")
            result = payload.get("result")
            points = result.get("points") if isinstance(result, dict) else None
            if not isinstance(points, list) or len(points) > limit:
                raise ValueError("invalid result list")
            matches = []
            seen = set()
            allowed = set(ids) if ids is not None else None
            for point in points:
                if not isinstance(point, dict):
                    raise ValueError("invalid result")
                match = VectorSearchMatch(_point_id(point["id"]), point["score"])
                if match.point_id in seen or (allowed is not None and match.point_id not in allowed):
                    raise ValueError("duplicate or out-of-scope result")
                seen.add(match.point_id)
                matches.append(match)
            return tuple(matches)
        except Exception:
            raise VectorRetrievalError("vector search failed") from None


def qdrant_history_point_id(namespace: str, turn: SessionHistoryTurn) -> str:
    """Versioned SHA-256-derived UUID for host indexing and local matching.

    Binds namespace, Run ID and ordered text/roles, not names or metadata. It is
    a content locator, not a signature, secrecy guarantee or authorization token.
    """
    try:
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", namespace):
            raise ValueError("invalid namespace")
        if not isinstance(turn, SessionHistoryTurn) or len(turn.run_id.encode("utf-8")) > 512:
            raise ValueError("invalid turn")
        if len(turn.messages) > 1024:
            raise ValueError("too many messages")
        if sum(len(message.content) for message in turn.messages) > 4096:
            raise ValueError("too many text blocks")
        text_size = sum(len(block.text.encode("utf-8")) for message in turn.messages for block in message.content)
        if text_size > 1024 * 1024:
            raise ValueError("oversized turn")
        value = ["wagent-history-vector-v1", namespace, turn.run_id,
                 [[message.role.value, [block.text for block in message.content]] for message in turn.messages]]
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return str(UUID(bytes=hashlib.sha256(encoded).digest()[:16]))
    except Exception:
        raise VectorRetrievalError("history point identity failed") from None


@dataclass(frozen=True, slots=True)
class QdrantSessionHistoryRetriever:
    """Select only supplied historical text via a host-prebuilt Qdrant index.

    The embedder sees only the explicit query. Search sees its vector and derived
    candidate IDs, never history text. Returned scores influence selection, not
    chronology; AsyncRetrievedSessionHistoryPolicy restores local segment order.
    """

    namespace: str = field(repr=False)
    embedder: AsyncTextEmbedder = field(repr=False)
    backend: DenseVectorSearch = field(repr=False)
    limits: SessionHistoryLimits = field(default_factory=SessionHistoryLimits)
    timeout: float = 30.0

    def __post_init__(self) -> None:
        _timeout(self.timeout)
        if not isinstance(self.namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", self.namespace):
            raise ValueError("retrieval namespace is invalid")
        if not isinstance(self.limits, SessionHistoryLimits):
            raise ValueError("retrieval history limits are invalid")
        if not callable(getattr(self.embedder, "embed", None)) or not callable(getattr(self.backend, "search", None)):
            raise ValueError("retrieval callbacks are invalid")

    async def select(self, query: str, turns: tuple[SessionHistoryTurn, ...], *, limit: int) -> tuple[int, ...]:
        try:
            _integer(limit, 128)
            if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > self.limits.max_query_bytes:
                raise ValueError("invalid query")
            if not isinstance(turns, tuple) or len(turns) > 1024 or any(not isinstance(turn, SessionHistoryTurn) for turn in turns):
                raise ValueError("invalid candidates")
            message_count = sum(len(turn.messages) for turn in turns)
            if message_count > self.limits.max_messages:
                raise ValueError("candidate history exceeds message bound")
            size = sum(len(block.text.encode("utf-8")) for turn in turns for message in turn.messages for block in message.content)
            if size > self.limits.max_input_bytes:
                raise ValueError("candidate history exceeds bounds")
            ids = tuple(qdrant_history_point_id(self.namespace, turn) for turn in turns)
            if len(set(ids)) != len(ids):
                raise ValueError("ambiguous candidate identity")
            if not ids:
                return ()
            async with asyncio.timeout(self.timeout):
                vector = _vector(await self.embedder.embed(query))
                matches = await self.backend.search(vector, limit=min(limit, len(ids)), point_ids=ids)
            if not isinstance(matches, tuple) or len(matches) > min(limit, len(ids)):
                raise ValueError("invalid matches")
            indices = {identity: index for index, identity in enumerate(ids)}
            selected = []
            for match in matches:
                if not isinstance(match, VectorSearchMatch) or match.point_id not in indices:
                    raise ValueError("match outside candidate history")
                index = indices[match.point_id]
                if index in selected:
                    raise ValueError("duplicate match")
                selected.append(index)
            return tuple(selected)
        except Exception:
            raise VectorRetrievalError("vector history selection failed") from None
