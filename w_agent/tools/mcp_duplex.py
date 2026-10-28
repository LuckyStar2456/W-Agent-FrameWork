"""Bounded duplex stdio transport for legacy callbacks and modern subscriptions."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from .mcp_client import (
    McpProtocolError, McpStdioTransport, McpTransportError, _await_with_cancellation,
)

_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"


class McpDuplexStdioTransport(McpStdioTransport):
    """One reader routes replies, subscription events, and explicit callbacks.

    Queues are bounded; overload fails the connection instead of losing events.
    A disconnected process is never restarted or a tool request replayed.
    """

    def __init__(self, command, *, max_pending: int = 64, max_queued: int = 128, **kwargs):
        super().__init__(command, **kwargs)
        if max_pending <= 0 or max_queued <= 0:
            raise ValueError("MCP duplex bounds must be positive")
        self.max_pending = max_pending
        self.max_queued = max_queued
        self._routes: dict[Any, asyncio.Queue] = {}
        self._reader: asyncio.Task | None = None
        self._callbacks: set[asyncio.Task] = set()
        self._request_handler = None
        self._notification_handler = None
        self._failure: BaseException | None = None
        self._closed = False

    def set_request_handler(self, handler) -> None:
        self._request_handler = handler

    def set_notification_handler(self, handler) -> None:
        self._notification_handler = handler

    async def _start_reader(self) -> None:
        if self._closed or self._failure is not None:
            raise McpTransportError("MCP duplex transport is closed or disconnected")
        async with self._lock:
            process = await self._ensure_started()
            if self._reader is None:
                self._reader = asyncio.create_task(self._pump(process))

    async def _write(self, message) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > self.max_message_bytes:
            raise McpTransportError("MCP stdio message exceeded framing bounds")
        async with self._lock:
            process = self._process
            if process is None or process.stdin is None or process.stdin.is_closing():
                raise McpTransportError("MCP stdio input is closed")
            try:
                process.stdin.write(encoded + b"\n")
                await asyncio.wait_for(process.stdin.drain(), self.request_timeout)
            except (BrokenPipeError, ConnectionResetError, TimeoutError) as exc:
                raise McpTransportError("MCP stdio write failed") from exc

    async def send_notification(self, message, *, cancellation=None) -> None:
        if message.get("jsonrpc") != "2.0" or "id" in message or not isinstance(message.get("method"), str):
            raise McpProtocolError("Invalid MCP notification")
        await self._start_reader()
        await _await_with_cancellation(self._write(message), cancellation)

    async def stream(self, message, *, cancellation=None) -> AsyncIterator[Mapping[str, Any]]:
        await self._start_reader()
        request_id = message.get("id")
        if request_id in self._routes or len(self._routes) >= self.max_pending:
            raise McpTransportError("MCP duplicate ID or pending request limit reached")
        queue: asyncio.Queue = asyncio.Queue(self.max_queued)
        self._routes[request_id] = queue
        complete = False
        try:
            await _await_with_cancellation(self._write(message), cancellation)
            while True:
                item = await _await_with_cancellation(queue.get(), cancellation)
                if isinstance(item, BaseException):
                    raise item
                if "id" in item and "method" not in item:
                    complete = True
                yield item
                if complete:
                    return
        finally:
            self._routes.pop(request_id, None)
            if not complete and not self._closed and self._failure is None:
                await self._write({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                   "params": {"requestId": request_id, "reason": "client closed request"}})

    async def send(self, message, *, cancellation=None, tool_schema=None):
        del tool_schema
        stream = self.stream(message, cancellation=cancellation)
        try:
            async with asyncio.timeout(self.request_timeout):
                async for item in stream:
                    if "id" in item and "method" not in item:
                        return item
        except TimeoutError as exc:
            raise McpTransportError("MCP stdio request timed out") from exc
        finally:
            await stream.aclose()
        raise McpTransportError("MCP response stream ended unexpectedly")

    def _fail(self, exc: BaseException) -> None:
        self._failure = exc
        for queue in self._routes.values():
            # Preserve replies already received before EOF. Overflow must fail
            # explicitly rather than silently dropping just one change event.
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
            queue.put_nowait(exc)

    async def _serve_request(self, message) -> None:
        try:
            if self._request_handler is None:
                response = {"jsonrpc": "2.0", "id": message["id"],
                            "error": {"code": -32601, "message": "Server requests disabled"}}
            else:
                response = await asyncio.wait_for(self._request_handler(message), self.request_timeout)
            await self._write(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(McpTransportError(f"MCP callback exchange failed: {type(exc).__name__}"))

    async def _pump(self, process) -> None:
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    raise McpTransportError("MCP stdio server disconnected")
                if len(line) > self.max_message_bytes + 1:
                    raise McpTransportError("MCP stdio message exceeded framing bounds")
                message = json.loads(line)
                if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
                    raise McpProtocolError("Invalid MCP stdio JSON-RPC message")
                if "method" in message and "id" in message:
                    if len(self._callbacks) >= self.max_pending:
                        raise McpTransportError("MCP callback limit reached")
                    task = asyncio.create_task(self._serve_request(message))
                    self._callbacks.add(task)
                    task.add_done_callback(self._callbacks.discard)
                elif "method" in message:
                    params = message.get("params", {})
                    if not isinstance(params, Mapping):
                        raise McpProtocolError("Invalid MCP notification params")
                    meta = params.get("_meta", {})
                    subscription_id = meta.get(_SUBSCRIPTION_ID) if isinstance(meta, Mapping) else None
                    if subscription_id in self._routes:
                        self._routes[subscription_id].put_nowait(message)
                    elif subscription_id is None and self._notification_handler is not None:
                        # Notification callbacks must not make nested requests; they
                        # run in receive order as an explicit cache invalidation barrier.
                        await self._notification_handler(message)
                elif message.get("id") in self._routes:
                    self._routes[message["id"]].put_nowait(message)
                # Late replies to cancelled requests are intentionally ignored.
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc if isinstance(exc, (McpProtocolError, McpTransportError))
                       else McpProtocolError(f"MCP receive failure: {type(exc).__name__}"))

    async def aclose(self) -> None:
        self._closed = True
        self._fail(McpTransportError("MCP duplex transport closed"))
        tasks = list(self._callbacks)
        if self._reader is not None:
            tasks.append(self._reader)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await super().aclose()
