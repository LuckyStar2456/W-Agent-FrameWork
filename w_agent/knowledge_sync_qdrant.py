"""Borrow existing Qdrant upserts and add explicit point-ID-only deletion."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from w_agent.knowledge_sync import QdrantDeletePlan, _canonical_sync_endpoint
from w_agent.tools.http_adapter import HttpToolRequest, HttpToolResponse
from w_agent.vector_indexing import QdrantUpsertPlan, QdrantVectorWriter, QdrantWriteResult, VectorIndexWriteError
from w_agent.vector_retrieval import _reject_constant, _unique_object


@dataclass(frozen=True, slots=True)
class QdrantKnowledgeSyncWriter:
    """Opt-in destructive sync for a dedicated host-owned collection.

    Delete removes the entire point (all named vectors/payload), not just a
    selected named vector. No filters, collection deletion, polling or retries.
    """

    writer: QdrantVectorWriter = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.writer, QdrantVectorWriter):
            raise ValueError("sync requires a Qdrant writer")
        _canonical_sync_endpoint(self.writer.endpoint)

    @property
    def endpoint(self) -> str:
        return self.writer.endpoint

    @property
    def vector_name(self) -> str | None:
        return self.writer.backend.vector_name

    async def upsert(self, plan: QdrantUpsertPlan, *, confirm_digest: str) -> QdrantWriteResult:
        return await self.writer.upsert(plan, confirm_digest=confirm_digest)

    async def delete(self, plan: QdrantDeletePlan, *, confirm_digest: str) -> QdrantWriteResult:
        entered = False
        try:
            backend = self.writer.backend
            endpoint = self.endpoint + "/delete"
            if not isinstance(plan, QdrantDeletePlan) or plan.endpoint != endpoint or confirm_digest != plan.digest:
                raise ValueError
            body = {"points": list(plan.point_ids)}
            if len(json.dumps(body).encode("utf-8")) > backend.max_request_bytes:
                raise ValueError
            headers = {"Content-Type": "application/json"}
            if backend.api_key is not None:
                headers["api-key"] = backend.api_key
            request = HttpToolRequest("POST", endpoint, headers=headers, query={"wait": "true"},
                                      json_body=body, max_response_bytes=backend.max_response_bytes)
            async with asyncio.timeout(backend.timeout):
                entered = True
                response = await backend.transport.send(request)
            if (not isinstance(response, HttpToolResponse) or not 200 <= response.status < 300
                    or len(response.body) > backend.max_response_bytes):
                raise ValueError
            payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("result"), dict):
                raise ValueError
            result = payload["result"]
            return QdrantWriteResult(plan.digest, len(plan.point_ids), result.get("status"), result.get("operation_id"))
        except Exception:
            raise VectorIndexWriteError(may_have_written=entered) from None
