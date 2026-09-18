"""First-party MCP 2026-07-28 clients and standard transports."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlsplit

from w_agent.models import CancellationToken

from .mcp_adapter import McpRemoteTool


MCP_PROTOCOL_VERSION = "2026-07-28"
_PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
_CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
_HTTP_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_LOGGER = logging.getLogger(__name__)


class McpError(RuntimeError):
    """Base error for first-party MCP clients."""


class McpTransportError(McpError):
    """A bounded transport exchange failed."""


class McpProtocolError(McpError):
    """A peer returned an invalid MCP or JSON-RPC message."""


class McpRemoteError(McpError):
    """A peer returned a JSON-RPC error response."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"MCP request failed with JSON-RPC code {code}: {message}")
        self.code = code
        self.remote_message = message


class McpToolExecutionError(McpError):
    """The remote tool completed with ``isError: true``."""


class McpInputRequiredError(McpError):
    """The call needs an MRTR input exchange that this client does not automate."""

    def __init__(self, result: Mapping[str, Any]) -> None:
        super().__init__("MCP tool call requires additional input")
        self.result = MappingProxyType(dict(result))


@dataclass(frozen=True, slots=True)
class McpClientInfo:
    name: str = "w-agent"
    version: str = "2.0.0a3"

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("MCP client name and version must not be empty")


class McpJsonRpcTransport(Protocol):
    """Replaceable transport boundary used by :class:`McpClient`."""

    async def send(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...

    async def aclose(self) -> None: ...


class McpClient:
    """Small current-era MCP client for discovery and tool calls.

    Protocol revision 2026-07-28 is stateless: every request carries protocol,
    client identity, and capability metadata. Legacy initialization negotiation
    is intentionally not guessed by this client.
    """

    def __init__(
        self,
        transport: McpJsonRpcTransport,
        *,
        client_info: McpClientInfo | None = None,
        client_capabilities: Mapping[str, Any] | None = None,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        max_pages: int = 100,
        max_tools: int = 10_000,
    ) -> None:
        if not protocol_version.strip():
            raise ValueError("MCP protocol version must not be empty")
        if max_pages <= 0 or max_tools <= 0:
            raise ValueError("MCP discovery bounds must be positive")
        self.transport = transport
        self.client_info = client_info or McpClientInfo()
        self.client_capabilities = MappingProxyType(dict(client_capabilities or {}))
        self.protocol_version = protocol_version
        self.max_pages = max_pages
        self.max_tools = max_tools
        self._next_id = 1
        self._tool_schemas: dict[str, Mapping[str, Any]] = {}

    async def __aenter__(self) -> "McpClient":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.transport.aclose()

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not method.strip():
            raise ValueError("MCP method must not be empty")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        request_id = self._next_id
        self._next_id += 1
        request_params = dict(params or {})
        if "_meta" in request_params:
            raise ValueError("MCP request metadata is owned by the client")
        request_params["_meta"] = {
            _PROTOCOL_VERSION_KEY: self.protocol_version,
            _CLIENT_INFO_KEY: {
                "name": self.client_info.name,
                "version": self.client_info.version,
            },
            _CLIENT_CAPABILITIES_KEY: dict(self.client_capabilities),
        }
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": request_params,
        }
        response = await self.transport.send(
            message,
            cancellation=cancellation,
            tool_schema=tool_schema,
        )
        return _parse_rpc_response(response, request_id)

    async def list_tools(
        self,
        *,
        cancellation: CancellationToken | None = None,
    ) -> tuple[McpRemoteTool, ...]:
        tools: list[McpRemoteTool] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page in range(self.max_pages):
            params = {} if cursor is None else {"cursor": cursor}
            result = await self.request(
                "tools/list",
                params,
                cancellation=cancellation,
            )
            result_type = result.get("resultType")
            if result_type not in (None, "complete"):
                raise McpProtocolError("tools/list did not return a complete result")
            raw_tools = result.get("tools")
            if not isinstance(raw_tools, list):
                raise McpProtocolError("tools/list result needs a tools array")
            for raw_tool in raw_tools:
                remote = _parse_remote_tool(raw_tool)
                validator = getattr(self.transport, "validate_tool_schema", None)
                try:
                    if validator is not None:
                        validator(remote.input_schema)
                except McpProtocolError as exc:
                    if getattr(self.transport, "reject_invalid_tool_headers", False):
                        _LOGGER.warning(
                            "Ignoring invalid MCP HTTP tool %s: %s",
                            remote.name,
                            exc,
                        )
                        continue
                    raise
                if len(tools) >= self.max_tools:
                    raise McpProtocolError("MCP tool discovery exceeded its tool limit")
                tools.append(remote)
                self._tool_schemas[remote.name] = remote.input_schema
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tuple(tools)
            if not isinstance(next_cursor, str) or not next_cursor:
                raise McpProtocolError("tools/list returned an invalid nextCursor")
            if next_cursor in seen_cursors:
                raise McpProtocolError("tools/list repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise McpProtocolError("MCP tool discovery exceeded its page limit")

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
    ) -> Any:
        if not name.strip():
            raise ValueError("MCP tool name must not be empty")
        if getattr(self.transport, "requires_tool_schema", False) and name not in self._tool_schemas:
            await self.list_tools(cancellation=cancellation)
        result = await self.request(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
            cancellation=cancellation,
            tool_schema=self._tool_schemas.get(name),
        )
        result_type = result.get("resultType")
        if result_type == "input_required":
            raise McpInputRequiredError(result)
        if result_type not in (None, "complete"):
            raise McpProtocolError("tools/call returned an unknown result type")
        if result.get("isError") is True:
            raise McpToolExecutionError("remote MCP tool reported an execution error")
        return result


@dataclass(frozen=True, slots=True)
class McpHttpRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes
    max_response_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class McpHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


class McpHttpExchange(Protocol):
    async def post(
        self,
        request: McpHttpRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> McpHttpResponse: ...


class HttpxMcpExchange:
    """Optional HTTPX exchange with redirect and response-size bounds."""

    def __init__(self, *, timeout: float = 30, follow_redirects: bool = False) -> None:
        if timeout <= 0:
            raise ValueError("MCP HTTP timeout must be positive")
        self.timeout = timeout
        self.follow_redirects = follow_redirects

    async def post(
        self,
        request: McpHttpRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> McpHttpResponse:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "MCP HTTP requires the 'models' extra or a custom exchange"
            ) from exc
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=self.follow_redirects,
        ) as client:
            async with client.stream(
                "POST",
                request.url,
                headers=dict(request.headers),
                content=request.body,
            ) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    body.extend(chunk)
                    if len(body) > request.max_response_bytes:
                        raise McpTransportError("MCP HTTP response exceeded its byte limit")
                return McpHttpResponse(
                    response.status_code,
                    dict(response.headers),
                    bytes(body),
                )


class McpStreamableHttpTransport:
    """MCP 2026-07-28 Streamable HTTP JSON/SSE request transport."""

    requires_tool_schema = True
    reject_invalid_tool_headers = True

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str] | None = None,
        exchange: McpHttpExchange | None = None,
        protocol_version: str = MCP_PROTOCOL_VERSION,
        max_request_bytes: int = 4_194_304,
        max_response_bytes: int = 4_194_304,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MCP HTTP endpoint must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("MCP HTTP credentials must be supplied as headers")
        if parsed.fragment:
            raise ValueError("MCP HTTP endpoint must not contain a fragment")
        if max_request_bytes <= 0 or max_response_bytes <= 0:
            raise ValueError("MCP HTTP byte limits must be positive")
        fixed_headers = dict(headers or {})
        for name, value in fixed_headers.items():
            if not isinstance(name, str) or not _HTTP_TOKEN.fullmatch(name):
                raise ValueError("MCP HTTP static header name is invalid")
            if (
                not isinstance(value, str)
                or value != value.strip(" \t")
                or not _is_plain_header_value(value)
            ):
                raise ValueError(f"MCP HTTP static header {name!r} has an invalid value")
            lowered = name.lower()
            if lowered in {
                "accept",
                "content-type",
                "mcp-protocol-version",
                "mcp-method",
                "mcp-name",
            } or lowered.startswith("mcp-param-"):
                raise ValueError(f"MCP HTTP header {name!r} is transport-owned")
        self.endpoint = endpoint
        self.headers = MappingProxyType(fixed_headers)
        self.exchange = exchange or HttpxMcpExchange()
        self.protocol_version = protocol_version
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes

    async def aclose(self) -> None:
        close = getattr(self.exchange, "aclose", None)
        if close is not None:
            await close()

    def validate_tool_schema(self, schema: Mapping[str, Any]) -> None:
        _mcp_parameter_specs(schema)

    async def send(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, Mapping):
            raise McpProtocolError("MCP HTTP request needs method and params")
        metadata = params.get("_meta")
        message_version = (
            metadata.get(_PROTOCOL_VERSION_KEY)
            if isinstance(metadata, Mapping)
            else None
        )
        if message_version != self.protocol_version:
            raise McpProtocolError(
                "MCP HTTP transport and request protocol versions do not match"
            )
        headers = dict(self.headers)
        headers.update(
            {
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "MCP-Protocol-Version": self.protocol_version,
                "Mcp-Method": _encode_header_value(method),
            }
        )
        name = params.get("name") or params.get("uri")
        if name is not None:
            if not isinstance(name, str):
                raise McpProtocolError("MCP name or URI header source must be text")
            headers["Mcp-Name"] = _encode_header_value(name)
        if method == "tools/call" and tool_schema is not None:
            arguments = params.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise McpProtocolError("MCP tool arguments must be an object")
            headers.update(_mcp_argument_headers(tool_schema, arguments))
        body = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > self.max_request_bytes:
            raise McpTransportError("MCP HTTP request exceeded its byte limit")
        response = await _await_with_cancellation(
            self.exchange.post(
                McpHttpRequest(
                    self.endpoint,
                    headers,
                    body,
                    self.max_response_bytes,
                ),
                cancellation=cancellation,
            ),
            cancellation,
        )
        messages = _decode_http_messages(response)
        request_id = message.get("id")
        for candidate in messages:
            if candidate.get("id") == request_id:
                return candidate
        raise McpProtocolError("MCP HTTP response did not contain the request result")


class McpStdioTransport:
    """Shell-free newline-delimited MCP transport over a child process."""

    requires_tool_schema = False
    reject_invalid_tool_headers = False

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        environment: Mapping[str, str] | None = None,
        inherit_environment: bool = True,
        request_timeout: float = 30,
        shutdown_timeout: float = 3,
        max_message_bytes: int = 4_194_304,
    ) -> None:
        resolved = tuple(command)
        if not resolved or any(not isinstance(part, str) or not part for part in resolved):
            raise ValueError("MCP stdio command must contain non-empty argv strings")
        if request_timeout <= 0 or shutdown_timeout <= 0 or max_message_bytes <= 0:
            raise ValueError("MCP stdio bounds must be positive")
        self.command = resolved
        self.cwd = os.fspath(cwd) if cwd is not None else None
        self.environment = MappingProxyType(dict(environment or {}))
        self.inherit_environment = inherit_environment
        self.request_timeout = request_timeout
        self.shutdown_timeout = shutdown_timeout
        self.max_message_bytes = max_message_bytes
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "McpStdioTransport":
        await self._ensure_started()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.aclose()

    async def send(
        self,
        message: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
        tool_schema: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        del tool_schema
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if b"\n" in encoded or len(encoded) > self.max_message_bytes:
            raise McpTransportError("MCP stdio request exceeded framing bounds")
        async with self._lock:
            process = await self._ensure_started()
            if process.stdin is None or process.stdout is None:
                raise McpTransportError("MCP stdio process streams are unavailable")
            process.stdin.write(encoded + b"\n")
            await process.stdin.drain()
            try:
                return await asyncio.wait_for(
                    self._read_response(process, message.get("id"), cancellation),
                    timeout=self.request_timeout,
                )
            except TimeoutError as exc:
                await self._send_cancel(process, message.get("id"), "request timed out")
                raise McpTransportError("MCP stdio request timed out") from exc
            except asyncio.CancelledError:
                await self._send_cancel(process, message.get("id"), "request cancelled")
                raise

    async def aclose(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), self.shutdown_timeout)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), self.shutdown_timeout)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        environment = (
            {**os.environ, **self.environment}
            if self.inherit_environment
            else dict(self.environment)
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=self.cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=self.max_message_bytes + 1,
            )
        except OSError as exc:
            raise McpTransportError("MCP stdio server could not be started") from exc
        return self._process

    async def _read_response(
        self,
        process: asyncio.subprocess.Process,
        request_id: Any,
        cancellation: CancellationToken | None,
    ) -> Mapping[str, Any]:
        assert process.stdout is not None
        while True:
            read_task = asyncio.create_task(process.stdout.readline())
            cancel_task = (
                asyncio.create_task(cancellation.wait())
                if cancellation is not None
                else None
            )
            waiting = {read_task}
            if cancel_task is not None:
                waiting.add(cancel_task)
            try:
                done, _pending = await asyncio.wait(
                    waiting,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                for task in waiting:
                    task.cancel()
                await asyncio.gather(*waiting, return_exceptions=True)
                raise
            if cancel_task is not None and cancel_task in done:
                read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)
                raise asyncio.CancelledError
            if cancel_task is not None:
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)
            try:
                line = read_task.result()
            except ValueError as exc:
                raise McpTransportError("MCP stdio response exceeded its byte limit") from exc
            if not line:
                raise McpTransportError("MCP stdio server closed before responding")
            if len(line) > self.max_message_bytes + 1:
                raise McpTransportError("MCP stdio response exceeded its byte limit")
            try:
                candidate = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise McpProtocolError("MCP stdio server returned invalid JSON") from exc
            if not isinstance(candidate, Mapping):
                raise McpProtocolError("MCP stdio message must be an object")
            if "id" not in candidate:
                continue
            if candidate.get("id") != request_id:
                raise McpProtocolError("MCP stdio response ID did not match request")
            return candidate

    async def _send_cancel(
        self,
        process: asyncio.subprocess.Process,
        request_id: Any,
        reason: str,
    ) -> None:
        if process.stdin is None or process.stdin.is_closing() or request_id is None:
            return
        message = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": request_id, "reason": reason},
        }
        try:
            process.stdin.write(
                json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            return


def _parse_rpc_response(
    response: Mapping[str, Any],
    request_id: int,
) -> Mapping[str, Any]:
    if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
        raise McpProtocolError("MCP response has invalid JSON-RPC identity")
    if "error" in response:
        error = response["error"]
        if not isinstance(error, Mapping):
            raise McpProtocolError("MCP JSON-RPC error must be an object")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, int) or isinstance(code, bool) or not isinstance(message, str):
            raise McpProtocolError("MCP JSON-RPC error fields are invalid")
        raise McpRemoteError(code, message)
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise McpProtocolError("MCP response needs an object result")
    return MappingProxyType(dict(result))


def _parse_remote_tool(raw: Any) -> McpRemoteTool:
    if not isinstance(raw, Mapping):
        raise McpProtocolError("MCP tool definition must be an object")
    name = raw.get("name")
    description = raw.get("description", "")
    schema = raw.get("inputSchema")
    if not isinstance(name, str) or not name.strip():
        raise McpProtocolError("MCP tool name must be non-empty text")
    if not isinstance(description, str) or not isinstance(schema, Mapping):
        raise McpProtocolError("MCP tool description or input schema is invalid")
    if schema.get("type") not in (None, "object"):
        raise McpProtocolError("MCP tool input schema root must be an object")
    output_schema = raw.get("outputSchema")
    if output_schema is not None and not isinstance(output_schema, Mapping):
        raise McpProtocolError("MCP tool output schema must be an object")
    annotations = raw.get("annotations", {})
    if not isinstance(annotations, Mapping):
        raise McpProtocolError("MCP tool annotations must be an object")
    title = raw.get("title")
    if title is not None and not isinstance(title, str):
        raise McpProtocolError("MCP tool title must be text")
    return McpRemoteTool(
        name,
        description,
        dict(schema),
        title=title,
        output_schema=dict(output_schema) if output_schema is not None else None,
        annotations=dict(annotations),
    )


def _decode_http_messages(response: McpHttpResponse) -> tuple[Mapping[str, Any], ...]:
    content_type = next(
        (
            value.split(";", 1)[0].strip().lower()
            for name, value in response.headers.items()
            if name.lower() == "content-type"
        ),
        "",
    )
    if content_type == "application/json":
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise McpProtocolError("MCP HTTP response contained invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise McpProtocolError("MCP HTTP JSON response must be an object")
        return (payload,)
    if content_type == "text/event-stream":
        return _parse_sse(response.body)
    if not 200 <= response.status < 300:
        raise McpTransportError(f"MCP HTTP server returned status {response.status}")
    raise McpProtocolError("MCP HTTP response used an unsupported content type")


def _parse_sse(body: bytes) -> tuple[Mapping[str, Any], ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise McpProtocolError("MCP SSE response was not UTF-8") from exc
    messages: list[Mapping[str, Any]] = []
    data_lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line:
            if data_lines:
                messages.append(_parse_sse_data("\n".join(data_lines)))
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        event_field, _, value = line.partition(":")
        if event_field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        messages.append(_parse_sse_data("\n".join(data_lines)))
    if not messages:
        raise McpProtocolError("MCP SSE response contained no JSON-RPC messages")
    return tuple(messages)


def _parse_sse_data(data: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise McpProtocolError("MCP SSE event contained invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise McpProtocolError("MCP SSE JSON-RPC message must be an object")
    return payload


def _mcp_parameter_specs(
    schema: Mapping[str, Any],
) -> tuple[tuple[tuple[str, ...], str, str], ...]:
    found: list[tuple[tuple[str, ...], str, str]] = []
    names: set[str] = set()

    def visit(value: Any, location: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            if "x-mcp-header" in value:
                valid_path = (
                    len(location) >= 2
                    and len(location) % 2 == 0
                    and all(location[index] == "properties" for index in range(0, len(location), 2))
                )
                header_name = value["x-mcp-header"]
                value_type = value.get("type")
                if not valid_path:
                    raise McpProtocolError("x-mcp-header is not on a reachable property")
                if not isinstance(header_name, str) or not _HTTP_TOKEN.fullmatch(header_name):
                    raise McpProtocolError("x-mcp-header name is invalid")
                if value_type not in {"string", "integer", "boolean"}:
                    raise McpProtocolError("x-mcp-header property type is invalid")
                normalized = header_name.lower()
                if normalized in names:
                    raise McpProtocolError("x-mcp-header names must be unique")
                names.add(normalized)
                property_path = tuple(location[index] for index in range(1, len(location), 2))
                found.append((property_path, header_name, value_type))
            for key, nested in value.items():
                if key != "x-mcp-header":
                    visit(nested, (*location, str(key)))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, (*location, str(index)))

    visit(schema, ())
    return tuple(found)


def _mcp_argument_headers(
    schema: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> dict[str, str]:
    headers: dict[str, str] = {}
    for path, name, value_type in _mcp_parameter_specs(schema):
        value: Any = arguments
        missing = False
        for part in path:
            if not isinstance(value, Mapping) or part not in value:
                missing = True
                break
            value = value[part]
        if missing or value is None:
            continue
        if value_type == "string" and not isinstance(value, str):
            raise McpProtocolError("x-mcp-header string argument has the wrong type")
        if value_type == "boolean":
            if not isinstance(value, bool):
                raise McpProtocolError("x-mcp-header boolean argument has the wrong type")
            rendered = "true" if value else "false"
        elif value_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise McpProtocolError("x-mcp-header integer argument has the wrong type")
            if not -(2**53) + 1 <= value <= 2**53 - 1:
                raise McpProtocolError("x-mcp-header integer argument is outside the safe range")
            rendered = str(value)
        else:
            rendered = value
        headers[f"Mcp-Param-{name}"] = _encode_header_value(rendered)
    return headers


def _encode_header_value(value: str) -> str:
    plain = (
        bool(value)
        and value == value.strip(" \t")
        and _is_plain_header_value(value)
        and not (value.startswith("=?base64?") and value.endswith("?="))
    )
    if plain:
        return value
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"=?base64?{encoded}?="


def _is_plain_header_value(value: str) -> bool:
    return all(
        character == "\t" or 0x20 <= ord(character) <= 0x7E
        for character in value
    )


async def _await_with_cancellation(
    awaitable: Any,
    cancellation: CancellationToken | None,
) -> Any:
    operation = asyncio.ensure_future(awaitable)
    if cancellation is None:
        return await operation
    cancelled = asyncio.create_task(cancellation.wait())
    try:
        done, _pending = await asyncio.wait(
            {operation, cancelled},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled in done:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise asyncio.CancelledError
        return operation.result()
    except BaseException:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        raise
    finally:
        cancelled.cancel()
        await asyncio.gather(cancelled, return_exceptions=True)
