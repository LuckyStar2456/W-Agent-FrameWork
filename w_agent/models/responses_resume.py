"""Opt-in Responses background streams with durable, same-generation cursors."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import quote

from .errors import ModelError, ModelFailure, ModelFailureKind
from .http_provider import HttpModelProvider, HttpRequest, HttpStreamDecoder, HttpStreamFormat
from .openai_responses import OpenAIResponsesMapping
from .provider import CancellationToken, CursorStreamItem
from .responses_checkpoints import ResponsesCheckpointStore
from .types import FinishEvent, ModelRequest, ModelStreamProtocolError


class OpenAIResponsesResumableProvider(HttpModelProvider):
    """Explicit native continuation for stored background Responses.

    Both ``background`` and ``store`` must be true in
    ``request.extensions['openai_responses.body']``. Normal ``stream`` retains
    the HTTP provider behavior. Use ``NativeCursorRecovery`` with ModelExecutor
    or persist a returned cursor and explicitly call ``resume_stream`` later.
    """

    def __init__(
        self, *, checkpoint_store: ResponsesCheckpointStore, **kwargs: Any
    ) -> None:
        mapping = kwargs.pop("mapping", None)
        if mapping is not None and type(mapping) is not OpenAIResponsesMapping:
            raise ValueError("native Responses recovery requires OpenAIResponsesMapping")
        super().__init__(mapping=mapping or OpenAIResponsesMapping(), **kwargs)
        self.checkpoint_store = checkpoint_store

    def _bound_request(self, request: ModelRequest) -> tuple[str, HttpRequest, str]:
        model = self._generation_model(request)
        wire = self._prepare(self.mapping.generation_request(request, model))
        if wire.body.get("background") is not True or wire.body.get("store") is not True:
            raise ValueError("native Responses recovery requires explicit background=true and store=true")
        # Version pins decoder semantics; the binding saves only a digest.
        identity = {
            "version": 1, "provider": self.name, "url": self._url(wire),
            "headers": {key.lower(): value for key, value in wire.headers.items()},
            "body": dict(wire.body),
            "max_image_bytes": self.mapping.max_image_bytes,
        }
        serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
        binding = hashlib.sha256(serialized.encode()).hexdigest()
        return model, wire, binding

    async def stream_with_cursor(
        self, request: ModelRequest, *, cancellation: CancellationToken | None = None
    ) -> AsyncIterator[CursorStreamItem]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        model, wire, binding = self._bound_request(request)
        decoder = self.mapping.stream_decoder(request, model)
        async for item in self._read(
            wire, decoder, binding, cancellation=cancellation
        ):
            yield item

    async def resume_stream(
        self, request: ModelRequest, cursor: str,
        *, cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[CursorStreamItem]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        model, _, binding = self._bound_request(request)
        checkpoint = self.checkpoint_store.load(cursor, binding)
        decoder = self.mapping.stream_decoder(request, model)
        events = ()
        for frame in checkpoint.frames:
            events = decoder.feed(frame)
        if not events or not 0 < checkpoint.event_offset <= len(events):
            raise ModelStreamProtocolError("checkpoint event offset is invalid")
        # A single vendor event may produce BlockStart + delta, or usage + finish.
        # Deliver its pending local suffix before asking for the next wire event.
        for offset in range(checkpoint.event_offset, len(events)):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            yield CursorStreamItem(events[offset], self.checkpoint_store.cursor(
                checkpoint.stream_id, checkpoint.sequence, offset + 1,
            ))
        if any(isinstance(event, FinishEvent) for event in events):
            decoder.finish()
            return
        wire = self._prepare(HttpRequest(
            "GET", "/responses/" + quote(checkpoint.response_id, safe=""),
            query={"stream": "true", "starting_after": str(checkpoint.sequence)},
            stream_format=HttpStreamFormat.SSE,
        ))
        async for item in self._read(
            wire, decoder, binding, cancellation=cancellation,
            stream_id=checkpoint.stream_id, response_id=checkpoint.response_id,
            sequence=checkpoint.sequence,
        ):
            yield item

    async def _read(
        self, wire: HttpRequest, decoder: HttpStreamDecoder, binding: str,
        *, cancellation: CancellationToken | None,
        stream_id: str | None = None, response_id: str | None = None,
        sequence: int = -1,
    ) -> AsyncIterator[CursorStreamItem]:
        finished = False
        async for frame in self.transport.stream(
            self._url(wire), request=wire, timeout=self.timeout
        ):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            current = frame.data.get("sequence_number")
            if isinstance(current, bool) or not isinstance(current, int) or current <= sequence:
                raise ModelStreamProtocolError("Responses sequence must increase strictly")
            response = frame.data.get("response")
            if isinstance(response, Mapping) and (
                response.get("background") is False or response.get("store") is False
            ):
                raise ModelStreamProtocolError("Responses did not retain the requested background generation")
            supplied_id = response.get("id") if isinstance(response, Mapping) else None
            if supplied_id is not None:
                if not isinstance(supplied_id, str) or not supplied_id or len(supplied_id) > 512:
                    raise ModelStreamProtocolError("Responses response id is invalid")
                if response_id is not None and supplied_id != response_id:
                    raise ModelStreamProtocolError("Responses resumed a different generation")
                response_id = supplied_id
            if response_id is None:
                raise ModelStreamProtocolError("Responses cursor stream needs an initial response id")
            events = decoder.feed(frame)
            if stream_id is None:
                stream_id = self.checkpoint_store.create(binding, response_id)
            self.checkpoint_store.append(stream_id, current, frame)
            for offset, event in enumerate(events, 1):
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                finished = finished or isinstance(event, FinishEvent)
                yield CursorStreamItem(event, self.checkpoint_store.cursor(stream_id, current, offset))
            sequence = current
        if not finished:
            raise ModelError(ModelFailure(
                ModelFailureKind.NETWORK, "responses-stream-interrupted",
                "Responses connection ended before a terminal event", retryable=True,
                provider=self.name,
            ))
        decoder.finish()
