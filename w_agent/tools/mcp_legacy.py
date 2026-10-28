"""Opt-in MCP 2025 initialization lifecycle for stdio and Streamable HTTP."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Protocol

from w_agent.models import CancellationToken

from .mcp_handlers import McpClientHandlers, McpNotificationHandler

from .mcp_client import (
    HttpxMcpExchange,
    McpClient,
    McpClientInfo,
    McpHttpExchange,
    McpHttpRequest,
    McpHttpResponse,
    McpProtocolError,
    McpStreamableHttpTransport,
    McpTransportError,
    _await_with_cancellation,
    _decode_http_messages,
    _parse_rpc_response,
)


MCP_LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")


class McpLegacyTransport(Protocol):
    """Request/notification transport for the stateful initialization lifecycle."""

    async def send(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...

    async def send_notification(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
    ) -> None: ...

    async def aclose(self) -> None: ...


class McpLegacyClient(McpClient):
    """Initialize once, negotiate an explicitly supported 2025 revision, then use tools.

    The client never silently falls back from the stateless 2026 lifecycle. A failed
    handshake is terminal for this instance because peer state may be ambiguous.
    """

    def __init__(
        self,
        transport: McpLegacyTransport,
        *,
        client_info: McpClientInfo | None = None,
        client_capabilities: Mapping[str, Any] | None = None,
        supported_versions: Sequence[str] = MCP_LEGACY_VERSIONS,
        max_pages: int = 100,
        max_tools: int = 10_000,
        handlers: McpClientHandlers | None = None,
        notification_handler: McpNotificationHandler | None = None,
    ) -> None:
        versions = tuple(supported_versions)
        if not versions or any(not isinstance(version, str) for version in versions):
            raise ValueError("MCP legacy versions must be non-empty strings")
        if len(set(versions)) != len(versions):
            raise ValueError("MCP legacy versions must be non-empty and unique")
        if any(version not in MCP_LEGACY_VERSIONS for version in versions):
            raise ValueError("MCP legacy version is not supported by this client")
        super().__init__(
            transport,
            client_info=client_info,
            client_capabilities=client_capabilities,
            protocol_version=versions[0],
            max_pages=max_pages,
            max_tools=max_tools,
            handlers=handlers,
            notification_handler=notification_handler,
        )
        setter = getattr(transport, "set_request_handler", None)
        if any(key in self.client_capabilities for key in ("sampling", "elicitation", "roots")) and setter is None:
            raise ValueError("MCP legacy client handlers require a duplex transport")
        if setter is not None:
            setter(self._respond_to_server)
        self.supported_versions = versions
        self._initialize_lock = asyncio.Lock()
        self._initialized = False
        self._failed = False
        self._initialize_result: Mapping[str, Any] | None = None
        self.server_capabilities: Mapping[str, Any] | None = None
        self.server_info: Mapping[str, Any] | None = None
        self.server_instructions: str | None = None

    async def _respond_to_server(self, message):
        if not self._initialized and message.get("method") != "ping":
            return {"jsonrpc": "2.0", "id": message.get("id"),
                    "error": {"code": -32601, "message": "Client is not initialized"}}
        return await self.handlers.respond(message, capabilities=self.client_capabilities)

    def listen(self, notifications, *, cancellation=None):
        raise McpProtocolError("subscriptions/listen requires the modern MCP lifecycle")

    async def subscribe_resource(self, uri: str, *, cancellation=None):
        return await self._resource_subscription("resources/subscribe", uri, cancellation)

    async def unsubscribe_resource(self, uri: str, *, cancellation=None):
        return await self._resource_subscription("resources/unsubscribe", uri, cancellation)

    async def _resource_subscription(self, method, uri, cancellation):
        if not isinstance(uri, str) or not uri:
            raise ValueError("MCP resource URI must be non-empty")
        await self.initialize(cancellation=cancellation)
        resources = (self.server_capabilities or {}).get("resources", {})
        if not isinstance(resources, Mapping) or resources.get("subscribe") is not True:
            raise McpProtocolError("MCP server did not negotiate resource subscriptions")
        return await self.request(method, {"uri": uri}, cancellation=cancellation)

    async def initialize(
        self, *, cancellation: CancellationToken | None = None
    ) -> Mapping[str, Any]:
        if self._failed:
            raise McpProtocolError("MCP legacy initialization failed; create a new client")
        async with self._initialize_lock:
            if self._failed:
                raise McpProtocolError("MCP legacy initialization failed; create a new client")
            if self._initialized:
                assert self._initialize_result is not None
                return self._initialize_result
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            request_id = self._next_id
            self._next_id += 1
            message = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": self.supported_versions[0],
                    "capabilities": dict(self.client_capabilities),
                    "clientInfo": {
                        "name": self.client_info.name,
                        "version": self.client_info.version,
                    },
                },
            }
            try:
                response = await self.transport.send(message, cancellation=cancellation)
                result = _parse_rpc_response(response, request_id)
                version = result.get("protocolVersion")
                capabilities = result.get("capabilities")
                server_info = result.get("serverInfo")
                instructions = result.get("instructions")
                if version not in self.supported_versions:
                    raise McpProtocolError("MCP server selected an unsupported version")
                if not isinstance(capabilities, Mapping) or not isinstance(
                    server_info, Mapping
                ):
                    raise McpProtocolError("MCP initialize result lacks server metadata")
                if "tools" in capabilities and not isinstance(
                    capabilities["tools"], Mapping
                ):
                    raise McpProtocolError("MCP server tool capability is invalid")
                if not all(
                    isinstance(server_info.get(key), str) and server_info[key]
                    for key in ("name", "version")
                ):
                    raise McpProtocolError("MCP server identity is invalid")
                if instructions is not None and not isinstance(instructions, str):
                    raise McpProtocolError("MCP server instructions must be text")
                set_version = getattr(self.transport, "set_protocol_version", None)
                if set_version is not None:
                    set_version(version)
                await self.transport.send_notification(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    cancellation=cancellation,
                )
            except BaseException:
                self._failed = True
                raise
            self.protocol_version = version
            self.server_capabilities = MappingProxyType(dict(capabilities))
            self.server_info = MappingProxyType(dict(server_info))
            self.server_instructions = instructions
            self._initialize_result = result
            self._initialized = True
            return result

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not method.strip() or method == "initialize":
            raise ValueError("MCP legacy method must be non-empty and not initialize")
        await self.initialize(cancellation=cancellation)
        if method in {"tools/list", "tools/call"} and "tools" not in (
            self.server_capabilities or {}
        ):
            raise McpProtocolError("MCP server did not negotiate tool capability")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        request_id = self._next_id
        self._next_id += 1
        response = await self.transport.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params or {}),
            },
            cancellation=cancellation,
            tool_schema=tool_schema,
        )
        return _parse_rpc_response(response, request_id)


class McpLegacyStreamableHttpTransport(McpStreamableHttpTransport):
    """2025 Streamable HTTP POST transport with negotiated version and session ID.

    This does not implement the older 2024 HTTP+SSE endpoint pair or server-to-
    client requests. A session-expired response fails closed; callers create a
    new client instead of silently replaying a possibly side-effecting call.
    """

    requires_tool_schema = False
    reject_invalid_tool_headers = False

    def validate_tool_schema(self, schema: Mapping[str, Any]) -> None:
        del schema

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str] | None = None,
        exchange: McpHttpExchange | None = None,
        max_request_bytes: int = 4_194_304,
        max_response_bytes: int = 4_194_304,
    ) -> None:
        super().__init__(
            endpoint,
            headers=headers,
            exchange=exchange or HttpxMcpExchange(),
            protocol_version=MCP_LEGACY_VERSIONS[0],
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
        )
        self._negotiated_version: str | None = None
        self._session_id: str | None = None

    def set_protocol_version(self, version: str) -> None:
        if version not in MCP_LEGACY_VERSIONS:
            raise McpProtocolError("MCP legacy transport received an invalid version")
        self._negotiated_version = version

    async def send(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        del tool_schema
        method = message.get("method")
        if (
            message.get("jsonrpc") != "2.0"
            or not isinstance(method, str)
            or not method
            or "id" not in message
        ):
            raise McpProtocolError("MCP legacy HTTP request needs method and ID")
        if method == "initialize" and self._negotiated_version is not None:
            raise McpProtocolError("MCP legacy HTTP session is already initialized")
        if method != "initialize" and self._negotiated_version is None:
            raise McpProtocolError("MCP legacy HTTP transport is not initialized")
        response = await self._post(message, cancellation=cancellation)
        if response.status == 404 and self._session_id is not None:
            raise McpTransportError("MCP legacy HTTP session expired; create a new client")
        if not 200 <= response.status < 300:
            raise McpTransportError(f"MCP legacy HTTP server returned status {response.status}")
        messages = _decode_http_messages(response)
        for candidate in messages:
            if "method" in candidate and "id" in candidate:
                raise McpProtocolError(
                    "MCP legacy server-initiated requests are not supported"
                )
            if candidate.get("id") == message["id"]:
                if method == "initialize":
                    session_id = _response_header(response.headers, "mcp-session-id")
                    if session_id is not None:
                        if not session_id or any(
                            not 0x21 <= ord(character) <= 0x7E
                            for character in session_id
                        ):
                            raise McpProtocolError("MCP legacy session ID is invalid")
                        self._session_id = session_id
                return candidate
        raise McpProtocolError("MCP legacy HTTP response did not contain the request result")

    async def send_notification(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
    ) -> None:
        if (
            message.get("jsonrpc") != "2.0"
            or "id" in message
            or not isinstance(message.get("method"), str)
            or not message["method"]
        ):
            raise McpProtocolError("MCP notification needs JSON-RPC without an ID")
        if self._negotiated_version is None:
            raise McpProtocolError("MCP legacy HTTP transport is not initialized")
        response = await self._post(message, cancellation=cancellation)
        if response.status != 202 or response.body:
            raise McpTransportError(
                "MCP legacy HTTP notification did not receive empty 202 Accepted"
            )

    async def _post(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None,
    ) -> McpHttpResponse:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        headers = dict(self.headers)
        headers.update(
            {
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            }
        )
        if self._negotiated_version is not None:
            headers["MCP-Protocol-Version"] = self._negotiated_version
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > self.max_request_bytes:
            raise McpTransportError("MCP legacy HTTP request exceeded its byte limit")
        response = await _await_with_cancellation(
            self.exchange.post(
                McpHttpRequest(self.endpoint, headers, body, self.max_response_bytes),
                cancellation=cancellation,
            ),
            cancellation,
        )
        if len(response.body) > self.max_response_bytes:
            raise McpTransportError("MCP legacy HTTP response exceeded its byte limit")
        return response


def _response_header(headers: Mapping[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.lower() == name), None)
