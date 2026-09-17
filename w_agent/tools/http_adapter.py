"""HTTP tool template with a fixed endpoint and replaceable transport."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from w_agent.models import CancellationToken, ToolDefinition

from .types import ToolBinding, ToolExecutionContext, ToolSideEffect


@dataclass(frozen=True, slots=True)
class HttpToolRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, Any] = field(default_factory=dict)
    json_body: Any = None
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        method = self.method.strip().upper()
        if not method or not self.url.strip():
            raise ValueError("HTTP tool method and URL must not be empty")
        if self.max_response_bytes <= 0:
            raise ValueError("HTTP tool response limit must be positive")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "query", MappingProxyType(dict(self.query)))


@dataclass(frozen=True, slots=True)
class HttpToolResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if not 100 <= self.status <= 599:
            raise ValueError("HTTP tool response status is invalid")
        if not isinstance(self.body, bytes):
            raise TypeError("HTTP tool response body must be bytes")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class HttpToolTransport(Protocol):
    async def send(
        self,
        request: HttpToolRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> HttpToolResponse: ...


class HttpToolError(RuntimeError):
    """A bounded HTTP tool request could not produce an accepted response."""


class HttpToolStatusError(HttpToolError):
    """The remote endpoint returned a non-success status."""


class HttpToolResponseTooLarge(HttpToolError):
    """The remote body exceeded the configured response limit."""


class HttpxToolTransport:
    """Optional HTTPX transport that streams into a bounded response buffer."""

    def __init__(
        self,
        *,
        timeout: float = 30,
        follow_redirects: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError("HTTP tool transport timeout must be positive")
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    async def send(
        self,
        request: HttpToolRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> HttpToolResponse:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "HTTP tools require the 'models' extra or a custom transport"
            ) from exc

        if cancellation is not None:
            cancellation.raise_if_cancelled()
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=self.follow_redirects,
        ) as client:
            async with client.stream(
                request.method,
                request.url,
                headers=dict(request.headers),
                params=dict(request.query),
                json=request.json_body,
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    body.extend(chunk)
                    if len(body) > request.max_response_bytes:
                        raise HttpToolResponseTooLarge(
                            "HTTP tool response exceeded its byte limit"
                        )
                return HttpToolResponse(
                    response.status_code,
                    dict(response.headers),
                    bytes(body),
                )


HttpToolRequestBuilder = Callable[[Mapping[str, Any]], HttpToolRequest]


def http_tool(
    name: str,
    description: str,
    input_schema: Mapping[str, Any],
    *,
    url: str,
    method: str = "POST",
    headers: Mapping[str, str] | None = None,
    transport: HttpToolTransport | None = None,
    request_builder: HttpToolRequestBuilder | None = None,
    max_response_bytes: int = 1_048_576,
    side_effect: ToolSideEffect = ToolSideEffect.EXTERNAL,
    required_permissions: frozenset[str] = frozenset({"network.http"}),
) -> ToolBinding:
    """Create a policy-enforced HTTP binding.

    The default mapping uses query parameters for GET/HEAD and a JSON body for
    other methods. The endpoint and headers are configuration, never model
    arguments. A custom builder can implement another mapping explicitly.
    """

    fixed_headers = dict(headers or {})
    default_method = method.strip().upper()
    if not name.strip() or not url.strip() or not default_method:
        raise ValueError("HTTP tool name, URL, and method must not be empty")
    if max_response_bytes <= 0:
        raise ValueError("HTTP tool response limit must be positive")
    resolved_transport = transport or HttpxToolTransport()
    definition = ToolDefinition(name, description, dict(input_schema))

    def build(arguments: Mapping[str, Any]) -> HttpToolRequest:
        if request_builder is not None:
            request = request_builder(arguments)
            if not isinstance(request, HttpToolRequest):
                raise TypeError("HTTP tool request_builder must return HttpToolRequest")
            return request
        query = dict(arguments) if default_method in {"GET", "HEAD"} else {}
        body = None if query else dict(arguments)
        return HttpToolRequest(
            default_method,
            url,
            fixed_headers,
            query,
            body,
            max_response_bytes,
        )

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        request = build(arguments)
        response = await resolved_transport.send(
            request,
            cancellation=context.cancellation,
        )
        if not 200 <= response.status < 300:
            raise HttpToolStatusError(f"HTTP tool returned status {response.status}")
        return {
            "status": response.status,
            "data": _decode_response(response),
        }

    return ToolBinding(
        definition,
        handler,
        side_effect,
        required_permissions,
        metadata={"adapter": "http", "method": default_method},
    )


def _decode_response(response: HttpToolResponse) -> Any:
    content_type = next(
        (
            value.lower()
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    text = response.body.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise HttpToolError("HTTP tool returned invalid JSON") from exc
    return text
