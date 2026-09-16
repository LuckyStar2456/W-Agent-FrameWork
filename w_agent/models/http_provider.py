"""Declarative HTTP model provider with replaceable request/response mappings."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode, urlsplit

from .errors import ModelError, ModelFailure, ModelFailureKind
from .provider import CancellationToken
from .types import ModelCapability, ModelDescriptor, ModelRequest, StreamEvent


class HttpStreamFormat(StrEnum):
    """Wire framing understood by the default transport."""

    SSE = "sse"
    NDJSON = "ndjson"


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Provider-independent description of one HTTP request."""

    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] | None = None
    stream_format: HttpStreamFormat | None = None

    def __post_init__(self) -> None:
        method = self.method.strip().upper()
        if not method:
            raise ValueError("HTTP request method must not be empty")
        if not self.path.startswith("/"):
            raise ValueError("HTTP request path must start with '/'")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "query", MappingProxyType(dict(self.query)))
        if self.body is not None:
            object.__setattr__(self, "body", MappingProxyType(dict(self.body)))


@dataclass(frozen=True, slots=True)
class HttpStreamFrame:
    """One decoded JSON frame plus its optional SSE event name."""

    data: Mapping[str, Any]
    event: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


class HttpProviderTransport(Protocol):
    """Replaceable transport used by :class:`HttpModelProvider`."""

    async def request_json(
        self,
        url: str,
        *,
        request: HttpRequest,
        timeout: float,
    ) -> Mapping[str, Any]: ...

    def stream(
        self,
        url: str,
        *,
        request: HttpRequest,
        timeout: float,
    ) -> AsyncIterator[HttpStreamFrame]: ...

    async def aclose(self) -> None: ...


class HttpStreamDecoder(Protocol):
    """Stateful mapping from vendor frames to stable model stream events."""

    def feed(self, frame: HttpStreamFrame) -> tuple[StreamEvent, ...]: ...

    def finish(self) -> tuple[StreamEvent, ...]: ...


class HttpProviderMapping(Protocol):
    """Public extension point for a vendor's HTTP schema."""

    def catalog_request(self) -> HttpRequest | None: ...

    def parse_catalog(self, payload: Mapping[str, Any]) -> tuple[str, ...]: ...

    def generation_request(self, request: ModelRequest, model: str) -> HttpRequest: ...

    def stream_decoder(self, request: ModelRequest, model: str) -> HttpStreamDecoder: ...


class HttpxProviderTransport:
    """HTTPX implementation supporting JSON, SSE, and newline-delimited JSON."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    def _httpx(self) -> Any:
        try:
            import httpx
        except ImportError as exc:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "missing-httpx",
                    "HTTPX is required; install wagent-framework[models]",
                )
            ) from exc
        return httpx

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._httpx().AsyncClient()
        return self._client

    async def request_json(
        self,
        url: str,
        *,
        request: HttpRequest,
        timeout: float,
    ) -> Mapping[str, Any]:
        httpx = self._httpx()
        try:
            response = await self._get_client().request(
                request.method,
                url,
                headers=dict(request.headers),
                json=dict(request.body) if request.body is not None else None,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise _transport_failure(ModelFailureKind.TIMEOUT, "timeout", exc, True)
        except httpx.HTTPError as exc:
            raise _transport_failure(
                ModelFailureKind.NETWORK, "network-error", exc, True
            )
        _raise_for_status(response.status_code, _response_message(response))
        return _json_object(response.json, "provider response")

    async def stream(
        self,
        url: str,
        *,
        request: HttpRequest,
        timeout: float,
    ) -> AsyncIterator[HttpStreamFrame]:
        if request.stream_format is None:
            raise ValueError("stream request needs a stream format")
        httpx = self._httpx()
        try:
            async with self._get_client().stream(
                request.method,
                url,
                headers=dict(request.headers),
                json=dict(request.body) if request.body is not None else None,
                timeout=timeout,
            ) as response:
                if response.status_code >= 400:
                    payload = (await response.aread()).decode(errors="replace")
                    _raise_for_status(response.status_code, payload[:1000])
                if request.stream_format == HttpStreamFormat.SSE:
                    async for frame in _sse_frames(response.aiter_lines()):
                        yield frame
                else:
                    async for frame in _ndjson_frames(response.aiter_lines()):
                        yield frame
        except ModelError:
            raise
        except httpx.TimeoutException as exc:
            raise _transport_failure(ModelFailureKind.TIMEOUT, "timeout", exc, True)
        except httpx.HTTPError as exc:
            raise _transport_failure(
                ModelFailureKind.NETWORK, "network-error", exc, True
            )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


@dataclass(frozen=True, slots=True)
class HttpModelProfile:
    """Capabilities and optional limits for one HTTP-backed model."""

    model: str
    capabilities: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
            }
        )
    )
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_efforts: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model profile needs a model identifier")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))


class HttpModelProvider:
    """Model provider assembled from a base URL, mapping, and transport."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        mapping: HttpProviderMapping,
        default_model: str | None = None,
        profiles: tuple[HttpModelProfile, ...] = (),
        default_capabilities: frozenset[ModelCapability] | None = None,
        timeout: float = 60.0,
        headers: Mapping[str, str] | None = None,
        transport: HttpProviderTransport | None = None,
    ) -> None:
        if not name:
            raise ValueError("provider name must not be empty")
        _validate_base_url(base_url)
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.mapping = mapping
        self.default_model = default_model
        self.timeout = timeout
        self.headers = MappingProxyType(dict(headers or {}))
        self.transport = transport or HttpxProviderTransport()
        self.default_capabilities = frozenset(
            default_capabilities
            or {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TEXT_OUTPUT,
                ModelCapability.STREAMING,
            }
        )
        self._profiles = {profile.model: profile for profile in profiles}
        known = set(self._profiles)
        if default_model is not None:
            known.add(default_model)
        self._descriptors = {model: self._descriptor(model) for model in known}

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        catalog = self.mapping.catalog_request()
        if catalog is not None:
            request = self._prepare(catalog)
            payload = await self.transport.request_json(
                self._url(request), request=request, timeout=self.timeout
            )
            for model in self.mapping.parse_catalog(payload):
                self._descriptors[model] = self._descriptor(model)
        return tuple(self._descriptors[key] for key in sorted(self._descriptors))

    async def resolve(self, model: str) -> ModelDescriptor:
        descriptor = self._descriptors.get(model)
        if descriptor is None and self.mapping.catalog_request() is not None:
            await self.list_models()
            descriptor = self._descriptors.get(model)
        if descriptor is None:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "unknown-model",
                    f"model {model!r} is not available",
                    provider=self.name,
                    model=model,
                )
            )
        return descriptor

    async def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        model = request.model or self.default_model
        if model is None:
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "model-required",
                    "request.model or provider default_model is required",
                    provider=self.name,
                )
            )
        descriptor = self._descriptors.get(model) or self._descriptor(model)
        missing = request.required_capabilities() - descriptor.capabilities
        if missing:
            values = ", ".join(sorted(item.value for item in missing))
            raise ModelError(
                ModelFailure(
                    ModelFailureKind.CONFIGURATION,
                    "unsupported-capability",
                    f"model {model!r} does not declare: {values}",
                    provider=self.name,
                    model=model,
                )
            )
        wire_request = self._prepare(self.mapping.generation_request(request, model))
        decoder = self.mapping.stream_decoder(request, model)
        async for frame in self.transport.stream(
            self._url(wire_request), request=wire_request, timeout=self.timeout
        ):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            for event in decoder.feed(frame):
                yield event
        for event in decoder.finish():
            yield event

    async def aclose(self) -> None:
        await self.transport.aclose()

    def _descriptor(self, model: str) -> ModelDescriptor:
        profile = self._profiles.get(model)
        return ModelDescriptor(
            provider=self.name,
            model=model,
            capabilities=profile.capabilities if profile else self.default_capabilities,
            context_window=profile.context_window if profile else None,
            max_output_tokens=profile.max_output_tokens if profile else None,
            reasoning_efforts=profile.reasoning_efforts if profile else (),
            extensions=profile.extensions if profile else {},
        )

    def _prepare(self, request: HttpRequest) -> HttpRequest:
        return HttpRequest(
            method=request.method,
            path=request.path,
            headers={**self.headers, **request.headers},
            query=request.query,
            body=request.body,
            stream_format=request.stream_format,
        )

    def _url(self, request: HttpRequest) -> str:
        url = f"{self.base_url}{request.path}"
        if request.query:
            url = f"{url}?{urlencode(request.query)}"
        return url


async def _sse_frames(lines: AsyncIterator[str]) -> AsyncIterator[HttpStreamFrame]:
    event: str | None = None
    data_lines: list[str] = []
    async for line in lines:
        if not line:
            if data_lines:
                frame = _parse_frame("\n".join(data_lines), event)
                if frame is not None:
                    yield frame
            event, data_lines = None, []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        frame = _parse_frame("\n".join(data_lines), event)
        if frame is not None:
            yield frame


async def _ndjson_frames(lines: AsyncIterator[str]) -> AsyncIterator[HttpStreamFrame]:
    async for line in lines:
        stripped = line.strip()
        if stripped:
            frame = _parse_frame(stripped, None)
            if frame is not None:
                yield frame


def _parse_frame(value: str, event: str | None) -> HttpStreamFrame | None:
    if value == "[DONE]":
        return None
    try:
        payload = json.loads(value)
    except ValueError as exc:
        raise _transport_failure(
            ModelFailureKind.PROTOCOL, "invalid-stream-json", exc, False
        )
    if not isinstance(payload, Mapping):
        raise ModelError(
            ModelFailure(
                ModelFailureKind.PROTOCOL,
                "invalid-stream-shape",
                "stream event must be a JSON object",
            )
        )
    return HttpStreamFrame(payload, event)


def _json_object(loader: Any, label: str) -> Mapping[str, Any]:
    try:
        value = loader()
    except (TypeError, ValueError) as exc:
        raise _transport_failure(
            ModelFailureKind.PROTOCOL, "invalid-json", exc, False
        )
    if not isinstance(value, Mapping):
        raise ModelError(
            ModelFailure(
                ModelFailureKind.PROTOCOL,
                "invalid-json-shape",
                f"{label} must be a JSON object",
            )
        )
    return value


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("base_url must be an absolute HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an absolute HTTP(S) URL")


def _response_message(response: Any) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return str(getattr(response, "text", ""))[:1000]
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return str(payload)[:1000]


def _raise_for_status(status: int, message: str) -> None:
    if status < 400:
        return
    if status in {401, 403}:
        kind, retryable = ModelFailureKind.AUTHENTICATION, False
    elif status == 429:
        kind, retryable = ModelFailureKind.RATE_LIMIT, True
    elif status in {408, 504}:
        kind, retryable = ModelFailureKind.TIMEOUT, True
    elif status >= 500:
        kind, retryable = ModelFailureKind.PROVIDER, True
    else:
        kind, retryable = ModelFailureKind.PROTOCOL, False
    raise ModelError(
        ModelFailure(
            kind,
            f"http-{status}",
            message or f"provider returned HTTP {status}",
            retryable,
        )
    )


def _transport_failure(
    kind: ModelFailureKind,
    code: str,
    error: Exception,
    retryable: bool,
) -> ModelError:
    return ModelError(ModelFailure(kind, code, str(error), retryable))
