"""Bounded live HTTP streams with explicit 2026/2025 protocol boundaries."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from .mcp_client import (
    MCP_PROTOCOL_VERSION, McpProtocolError, McpStreamableHttpTransport,
    McpTransportError, _await_with_cancellation, _encode_header_value,
    _mcp_argument_headers,
)


def _bounded_int(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("invalid MCP HTTP stream bound")


def _seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
        raise ValueError("invalid MCP HTTP timeout")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise McpProtocolError("Duplicate MCP JSON field")
        value[key] = item
    return value


def _constant(_value):
    raise McpProtocolError("Non-finite MCP JSON value")


def _identity(value):
    if not ((type(value) is int and -(2**53) < value < 2**53)
            or (isinstance(value, str) and 1 <= len(value.encode("utf-8")) <= 256)):
        raise McpProtocolError("Invalid MCP JSON-RPC ID")
    return (type(value), value)


def _message(raw: bytes) -> Mapping[str, Any]:
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
        if not isinstance(result, dict) or result.get("jsonrpc") != "2.0":
            raise ValueError
        if "method" in result:
            if (not isinstance(result["method"], str) or not result["method"]
                    or not isinstance(result.get("params", {}), Mapping)
                    or "result" in result or "error" in result):
                raise ValueError
            if "id" in result:
                _identity(result["id"])
        else:
            _identity(result.get("id"))
            if ("result" in result) == ("error" in result):
                raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise McpProtocolError("Invalid MCP HTTP JSON-RPC message") from None


class McpStreamingHttpTransport(McpStreamableHttpTransport):
    """2026-07-28 POST JSON/SSE, including live subscriptions/listen.

    No GET, session IDs, independent server requests, redirects, replay or native
    cursor recovery. Injected HTTPX clients are borrowed; the default is owned.
    Stream consumers must aclose on early exit. Every stream has explicit bounds.
    """

    _legacy = False

    def __init__(
        self, endpoint: str, *, headers: Mapping[str, str] | None = None,
        client=None, request_timeout: float = 30, idle_timeout: float = 60,
        max_stream_seconds: float = 3600, max_request_bytes: int = 4_194_304,
        max_message_bytes: int = 1_048_576, max_stream_bytes: int = 67_108_864,
        max_messages: int = 10000, max_streams: int = 16,
    ) -> None:
        for value in (request_timeout, idle_timeout, max_stream_seconds):
            _seconds(value)
        for value, bound in ((max_request_bytes, 16_777_216), (max_message_bytes, 16_777_216),
                             (max_stream_bytes, 268_435_456), (max_messages, 100000), (max_streams, 128)):
            _bounded_int(value, bound)
        if max_message_bytes > max_stream_bytes:
            raise ValueError("message bound exceeds stream bound")
        super().__init__(endpoint, headers=headers, max_request_bytes=max_request_bytes,
                         max_response_bytes=max_message_bytes)
        if any(name.lower() in {"host", "content-length", "transfer-encoding", "last-event-id"}
               for name in self.headers):
            raise ValueError("MCP framing and cursor headers are transport-owned")
        self.request_timeout, self.idle_timeout = request_timeout, idle_timeout
        self.max_stream_seconds, self.max_message_bytes = max_stream_seconds, max_message_bytes
        self.max_stream_bytes, self.max_messages, self.max_streams = max_stream_bytes, max_messages, max_streams
        self._http_client = client
        self._owns_client = client is None
        self._closed = False
        self._responses: set = set()
        self._deadlines: dict = {}
        self._io_tasks: set[asyncio.Task] = set()
        self._active = 0
        self._request_ids: set = set()
        self._notification_handler = None

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler

    def _check_open(self):
        if self._closed:
            raise McpTransportError("MCP HTTP transport is closed; no replay")

    async def _io(self, awaitable, cancellation=None, *, timeout=None):
        task = asyncio.ensure_future(awaitable)
        self._io_tasks.add(task)
        try:
            self._check_open()
            async with asyncio.timeout(timeout or self.idle_timeout):
                return await _await_with_cancellation(task, cancellation)
        except TimeoutError:
            raise McpTransportError("MCP HTTP stream timed out; no replay") from None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._io_tasks.discard(task)

    def _client(self):
        if self._http_client is None:
            try:
                import httpx
            except ImportError:
                raise McpTransportError("MCP live HTTP requires the models extra") from None
            self._http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False,
                                                timeout=self.idle_timeout)
        return self._http_client

    @asynccontextmanager
    async def _open(self, method, headers, body=b"", *, cancellation=None):
        self._check_open()
        if self._active >= self.max_streams:
            raise McpTransportError("MCP concurrent HTTP stream limit reached")
        self._active += 1
        response = None
        try:
            client = self._client()
            request = client.build_request(method, self.endpoint, headers=headers, content=body)
            response = await self._io(client.send(request, stream=True, follow_redirects=False),
                                      cancellation, timeout=self.request_timeout)
            self._responses.add(response)
            self._deadlines[response] = asyncio.get_running_loop().time() + self.max_stream_seconds
            if not 200 <= response.status_code < 300:
                raise McpTransportError(f"MCP HTTP status {response.status_code}; no fallback or replay")
            yield response
        except (McpProtocolError, McpTransportError, asyncio.CancelledError, GeneratorExit):
            raise
        except Exception:
            raise McpTransportError("MCP HTTP exchange failed; outcome may be unknown") from None
        finally:
            if response is not None:
                self._responses.discard(response)
                self._deadlines.pop(response, None)
                await response.aclose()
            self._active -= 1

    def _body(self, message):
        try:
            data = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise McpProtocolError("MCP outgoing message is not bounded JSON") from None
        if len(data) > self.max_request_bytes:
            raise McpTransportError("MCP request exceeded byte limit")
        return data

    def _headers(self, message, tool_schema=None):
        method, params = message.get("method"), message.get("params", {})
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method or not isinstance(params, Mapping):
            raise McpProtocolError("MCP HTTP request needs method and params")
        _identity(message.get("id"))
        meta = params.get("_meta", {})
        if not isinstance(meta, Mapping) or meta.get("io.modelcontextprotocol/protocolVersion") != MCP_PROTOCOL_VERSION:
            raise McpProtocolError("MCP HTTP protocol version mismatch")
        headers = {**self.headers, "accept": "application/json, text/event-stream", "content-type": "application/json",
                   "MCP-Protocol-Version": MCP_PROTOCOL_VERSION, "Mcp-Method": _encode_header_value(method)}
        name = params.get("name") if "name" in params else params.get("uri")
        if name is not None:
            if not isinstance(name, str):
                raise McpProtocolError("MCP name/URI must be text")
            headers["Mcp-Name"] = _encode_header_value(name)
        if method == "tools/call" and tool_schema is not None:
            arguments = params.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise McpProtocolError("MCP arguments must be an object")
            headers.update(_mcp_argument_headers(tool_schema, arguments))
        return headers

    async def _chunks(self, response, cancellation):
        iterator = response.aiter_bytes().__aiter__()
        total = 0
        while True:
            self._check_open()
            try:
                remaining = self._deadlines[response] - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise McpTransportError("MCP stream lifetime exceeded; no replay")
                chunk = await self._io(anext(iterator), cancellation, timeout=min(self.idle_timeout, remaining))
            except StopAsyncIteration:
                return
            total += len(chunk)
            if total > self.max_stream_bytes:
                raise McpTransportError("MCP stream exceeded total byte limit")
            yield chunk

    async def _frames(self, response, cancellation):
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            data = bytearray()
            async for chunk in self._chunks(response, cancellation):
                data.extend(chunk)
                if len(data) > self.max_message_bytes:
                    raise McpTransportError("MCP JSON response exceeded message limit")
            yield _message(bytes(data))
            return
        if content_type != "text/event-stream":
            raise McpProtocolError("Unsupported MCP response content type")
        buffer, lines = bytearray(), []
        frame_bytes = count = 0
        previous_cr = False
        async for chunk in self._chunks(response, cancellation):
            if previous_cr and chunk.startswith(b"\n"):
                chunk = chunk[1:]
            previous_cr = chunk.endswith(b"\r")
            buffer.extend(chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
            while b"\n" in buffer:
                line, _, rest = buffer.partition(b"\n")
                buffer = bytearray(rest)
                if len(line) > self.max_message_bytes:
                    raise McpTransportError("MCP SSE line exceeded message limit")
                if not line:
                    if lines:
                        data = b"\n".join(lines)
                        if data.strip():
                            count += 1
                            if count > self.max_messages:
                                raise McpTransportError("MCP SSE event limit reached")
                            yield _message(data)
                    lines, frame_bytes = [], 0
                elif line.startswith(b"data:") or line == b"data":
                    value = bytes(line.partition(b":")[2])
                    if value.startswith(b" "):
                        value = value[1:]
                    frame_bytes += len(value) + 1
                    if frame_bytes > self.max_message_bytes:
                        raise McpTransportError("MCP SSE frame exceeded message limit")
                    lines.append(value)
                elif line.startswith(b"event:") and bytes(line.partition(b":")[2].strip()) not in {b"", b"message"}:
                    raise McpProtocolError("Unsupported MCP SSE event type; no endpoint discovery")
                # Comments, id and retry fields are bounded but never trigger replay.
            if len(buffer) > self.max_message_bytes:
                raise McpTransportError("MCP SSE partial line exceeded message limit")
        if buffer or lines:
            raise McpTransportError("MCP SSE ended with an incomplete frame")

    async def stream(self, message, *, cancellation=None, tool_schema=None) -> AsyncIterator[Mapping[str, Any]]:
        headers, body = self._headers(message, tool_schema), self._body(message)
        identity = _identity(message.get("id"))
        if identity in self._request_ids:
            raise McpProtocolError("Duplicate active MCP request ID")
        self._request_ids.add(identity)
        finished = False
        try:
            async with self._open("POST", headers, body, cancellation=cancellation) as response:
                await self._accept_response_headers(response, message)
                async for item in self._frames(response, cancellation):
                    if "method" in item:
                        if "id" in item:
                            await self._server_request(item, cancellation)
                        else:
                            yield item
                    else:
                        if _identity(item["id"]) != identity:
                            raise McpProtocolError("MCP response ID does not match its HTTP request")
                        finished = True
                        yield item
                        return
                raise McpTransportError("MCP HTTP stream ended before response; no replay")
        except TimeoutError:
            raise McpTransportError("MCP stream lifetime exceeded; no replay") from None
        finally:
            self._request_ids.discard(identity)
            if self._legacy and not finished and message.get("method") != "initialize" and not self._closed:
                try:
                    await self.send_notification({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": message["id"]}})
                except (Exception, asyncio.CancelledError):
                    pass  # Cancellation acknowledgement is never assumed.

    async def _accept_response_headers(self, response, message):
        pass

    async def _server_request(self, message, cancellation):
        raise McpProtocolError("Independent server requests are forbidden in MCP 2026; use MRTR")

    async def send(self, message, *, cancellation=None, tool_schema=None):
        iterator = self.stream(message, cancellation=cancellation, tool_schema=tool_schema)
        try:
            async with asyncio.timeout(self.request_timeout):
                async for item in iterator:
                    if "method" not in item:
                        return item
                    if self._notification_handler is not None:
                        await self._io(self._notification_handler(item), cancellation, timeout=self.request_timeout)
        except TimeoutError:
            raise McpTransportError("MCP request timeout; no replay") from None
        finally:
            await iterator.aclose()
        raise McpTransportError("MCP result missing")

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        # A host handler may close its transport; never cancel/await itself.
        current = asyncio.current_task()
        tasks = tuple(task for task in self._io_tasks if task is not current)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(response.aclose() for response in tuple(self._responses)), return_exceptions=True)
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()


class McpLegacyDuplexHttpTransport(McpStreamingHttpTransport):
    """Explicit 2025-11-25 POST callbacks and opt-in standalone GET SSE.

    Initialize through McpLegacyClient first; GET is never opened implicitly.
    Session expiry/disconnect never initiates a new session or retries a tool.
    """

    _legacy = True
    requires_tool_schema = False
    reject_invalid_tool_headers = False

    def __init__(self, endpoint, **kwargs):
        super().__init__(endpoint, **kwargs)
        self.protocol_version = "2025-11-25"
        self._negotiated = False
        self._session_id = None
        self._request_handler = None
        self._seen_server_ids: set = set()

    def validate_tool_schema(self, schema):
        pass

    def set_protocol_version(self, version):
        if version != "2025-11-25":
            raise McpProtocolError("Duplex HTTP implements only explicit MCP 2025-11-25")
        self._negotiated = True

    def set_request_handler(self, handler):
        self._request_handler = handler

    def _legacy_headers(self):
        headers = {**self.headers, "accept": "application/json, text/event-stream", "content-type": "application/json"}
        if self._negotiated:
            headers["MCP-Protocol-Version"] = self.protocol_version
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _headers(self, message, tool_schema=None):
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method:
            raise McpProtocolError("Invalid legacy MCP request")
        _identity(message.get("id"))
        if (method == "initialize") == self._negotiated:
            raise McpProtocolError("Legacy MCP initialization state mismatch")
        return self._legacy_headers()

    async def _accept_response_headers(self, response, message):
        values = response.headers.get_list("mcp-session-id")
        if not values:
            return
        if len(values) != 1 or not 1 <= len(values[0]) <= 1024 or any(not 0x21 <= ord(char) <= 0x7E for char in values[0]):
            raise McpProtocolError("Invalid legacy MCP session header")
        if message.get("method") == "initialize" and self._session_id is None:
            self._session_id = values[0]
        elif values[0] != self._session_id:
            raise McpProtocolError("Legacy MCP session changed unexpectedly")

    async def _oneway(self, message, cancellation=None, *, allow_initializing=False):
        if not self._negotiated and not allow_initializing:
            raise McpProtocolError("Legacy MCP session is not initialized")
        async with asyncio.timeout(self.request_timeout):
            async with self._open("POST", self._legacy_headers(), self._body(message), cancellation=cancellation) as response:
                if response.status_code != 202:
                    raise McpProtocolError("MCP response/notification requires empty 202")
                await self._accept_response_headers(response, message)
                async for chunk in self._chunks(response, cancellation):
                    if chunk:
                        raise McpProtocolError("MCP response/notification requires empty 202")

    async def send_notification(self, message, *, cancellation=None):
        if message.get("jsonrpc") != "2.0" or "id" in message or not isinstance(message.get("method"), str):
            raise McpProtocolError("Invalid legacy MCP notification")
        await self._oneway(message, cancellation)

    async def _server_request(self, message, cancellation):
        identity = _identity(message["id"])
        if identity in self._seen_server_ids or len(self._seen_server_ids) >= self.max_messages:
            raise McpProtocolError("Duplicate server request ID or callback limit reached")
        self._seen_server_ids.add(identity)
        if self._request_handler is None:
            reply = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Client handler disabled"}}
        else:
            reply = await self._io(self._request_handler(message), cancellation, timeout=self.request_timeout)
        validated = _message(self._body(reply))
        if "method" in validated or _identity(validated["id"]) != identity:
            raise McpProtocolError("Invalid MCP callback response")
        await self._oneway(reply, cancellation, allow_initializing=True)

    async def listen_notifications(self, *, cancellation=None):
        """Explicit one-shot GET lifetime; yield notifications after client handling."""
        if not self._negotiated:
            raise McpProtocolError("Initialize legacy client before opening GET stream")
        headers = self._legacy_headers()
        headers["accept"] = "text/event-stream"
        headers.pop("content-type", None)
        try:
            async with self._open("GET", headers, cancellation=cancellation) as response:
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/event-stream":
                    raise McpProtocolError("Legacy GET requires SSE")
                await self._accept_response_headers(response, {})
                async for item in self._frames(response, cancellation):
                    if "method" not in item:
                        raise McpProtocolError("Legacy standalone GET cannot carry responses without replay")
                    if "id" in item:
                        await self._server_request(item, cancellation)
                    else:
                        if self._notification_handler is not None:
                            await self._io(self._notification_handler(item), cancellation, timeout=self.request_timeout)
                        yield item
                raise McpTransportError("Legacy GET stream disconnected; refetch state before a new stream")
        except TimeoutError:
            raise McpTransportError("Legacy GET lifetime exceeded; no automatic reconnect") from None
