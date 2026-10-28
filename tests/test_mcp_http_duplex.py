import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from w_agent.models import CancellationToken
from w_agent.tools import (
    McpClient, McpClientHandlers, McpLegacyClient, McpLegacyDuplexHttpTransport,
    McpProtocolError, McpStreamingHttpTransport, McpTransportError,
)


def frame(value):
    return b"data: " + json.dumps(value).encode() + b"\r\n\r\n"


def request(method="ping", identity=1):
    return {"jsonrpc": "2.0", "id": identity, "method": method,
            "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}}


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, stall=False):
        self.chunks, self.stall, self.closed = chunks, stall, False
        self.waiting = asyncio.Event()

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.stall:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@asynccontextmanager
async def mock_transport(stream, *, legacy=False, status=200, **kwargs):
    calls = []

    async def handler(req):
        calls.append(req)
        if req.content and "id" not in json.loads(req.content):
            return httpx.Response(202)
        return httpx.Response(status, headers={"content-type": "text/event-stream"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        kind = McpLegacyDuplexHttpTransport if legacy else McpStreamingHttpTransport
        transport = kind("http://localhost/mcp", client=http, **kwargs)
        if legacy:
            transport.set_protocol_version("2025-11-25")
        try:
            yield transport, calls, http
        finally:
            await transport.aclose()


@pytest.mark.asyncio
async def test_modern_incremental_subscription_and_explicit_close():
    meta = {"io.modelcontextprotocol/subscriptionId": 1}
    ack = {"jsonrpc": "2.0", "method": "notifications/subscriptions/acknowledged",
           "params": {"_meta": meta, "notifications": {"toolsListChanged": True}}}
    update = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed", "params": {"_meta": meta}}
    data = frame(ack) + frame(update)
    stream = Stream([data[:7], data[7:19], data[19:]], stall=True)
    async with mock_transport(stream) as (transport, calls, http):
        client = McpClient(transport)
        listener = client.listen({"toolsListChanged": True})
        assert await anext(listener) == ack
        assert await anext(listener) == update
        await listener.aclose()
        assert stream.closed
        assert len(calls) == 1
        assert calls[0].headers["mcp-method"] == "subscriptions/listen"
        assert calls[0].headers["mcp-protocol-version"] == "2026-07-28"
        assert "mcp-session-id" not in calls[0].headers
        await transport.aclose()
        assert not http.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("close_transport", [False, True])
async def test_cancel_pending_read_closes_without_modern_cancel_post(close_transport):
    stream = Stream([], stall=True)
    async with mock_transport(stream) as (transport, calls, _):
        token = CancellationToken()
        pending = asyncio.create_task(transport.send(request(), cancellation=token))
        await asyncio.wait_for(stream.waiting.wait(), 2)
        if close_transport:
            await transport.aclose()
        else:
            token.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stream.closed
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,error", [
    (frame({"jsonrpc": "2.0", "id": "server", "method": "roots/list"}), "Independent"),
    (frame({"jsonrpc": "2.0", "id": 2, "result": {}}), "does not match"),
    (b'data: {"jsonrpc":"2.0","id":1,"id":1,"result":{}}\n\n', "Duplicate"),
    (b"event: endpoint\ndata: /elsewhere\n\n", "event type"),
])
async def test_invalid_modern_messages_fail_without_retry(payload, error):
    async with mock_transport(Stream([payload])) as (transport, calls, _):
        with pytest.raises(McpProtocolError, match=error):
            await transport.send(request())
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,chunks,error", [
    ({"max_message_bytes": 30}, [b"data:" + b"x" * 31], "line"),
    ({"max_stream_bytes": 100, "max_message_bytes": 100}, [b":" + b"x" * 99 + b"\n"], "total byte"),
    ({"max_messages": 1}, [frame({"jsonrpc": "2.0", "method": "notice"}) * 2], "event limit"),
    ({}, [b'data: {"jsonrpc":"2.0"}'], "incomplete"),
    ({}, [], "before response"),
])
async def test_stream_bounds_and_disconnect(kwargs, chunks, error):
    async with mock_transport(Stream(chunks), **kwargs) as (transport, calls, _):
        with pytest.raises(McpTransportError, match=error):
            await transport.send(request())
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_idle_timeout_and_active_stream_bound():
    stream = Stream([], stall=True)
    async with mock_transport(stream, max_streams=1, idle_timeout=0.03) as (transport, calls, _):
        pending = asyncio.create_task(transport.send(request()))
        await stream.waiting.wait()
        with pytest.raises(McpTransportError, match="concurrent"):
            await transport.send(request(identity=2))
        with pytest.raises(McpTransportError, match="timed out"):
            await pending
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 404, 405, 503])
async def test_http_status_does_not_retry_or_fallback(status):
    async with mock_transport(Stream([]), status=status) as (transport, calls, _):
        with pytest.raises(McpTransportError, match=str(status)):
            await transport.send(request())
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_legacy_cancel_posts_explicit_notification_once():
    stream = Stream([], stall=True)
    async with mock_transport(stream, legacy=True) as (transport, calls, _):
        token = CancellationToken()
        pending = asyncio.create_task(transport.send(request(), cancellation=token))
        await stream.waiting.wait()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stream.closed
        assert [json.loads(call.content).get("method") for call in calls] == ["ping", "notifications/cancelled"]
        assert json.loads(calls[1].content)["params"] == {"requestId": 1}


@pytest.mark.asyncio
async def test_legacy_duplicate_callback_never_reexecutes_handler():
    executed, replies = [], []
    message = {"jsonrpc": "2.0", "id": "server", "method": "ping"}

    async def callback(message):
        executed.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], "result": {}}

    async def exchange(req):
        value = json.loads(req.content)
        if value.get("method") == "ping":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream([frame(message) * 2]))
        replies.append(value)
        return httpx.Response(202)

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as http:
        transport = McpLegacyDuplexHttpTransport("http://localhost/mcp", client=http)
        transport.set_protocol_version("2025-11-25")
        transport.set_request_handler(callback)
        try:
            with pytest.raises(McpProtocolError, match="Duplicate"):
                await transport.send(request())
            assert len(executed) == 1
            assert len([reply for reply in replies if "result" in reply]) == 1
        finally:
            await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["changed", "bad session"])
async def test_legacy_session_rotation_and_invalid_header_fail(header):
    async def exchange(req):
        message = json.loads(req.content)
        if "id" not in message:
            return httpx.Response(202)
        return httpx.Response(200, headers={"content-type": "application/json", "mcp-session-id": header},
                              json={"jsonrpc": "2.0", "id": message["id"], "result": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(exchange)) as http:
        transport = McpLegacyDuplexHttpTransport("http://localhost/mcp", client=http)
        transport.set_protocol_version("2025-11-25")
        transport._session_id = "original"
        try:
            with pytest.raises(McpProtocolError, match="session"):
                await transport.send(request())
            assert transport._session_id == "original"
        finally:
            await transport.aclose()


@pytest.mark.asyncio
async def test_legacy_get_response_forbidden_and_no_reconnect():
    async with mock_transport(Stream([frame({"jsonrpc": "2.0", "id": 1, "result": {}})]), legacy=True) as (transport, calls, _):
        events = transport.listen_notifications()
        with pytest.raises(McpProtocolError, match="cannot carry responses"):
            await anext(events)
        assert len(calls) == 1
        assert calls[0].method == "GET"


def test_explicit_protocol_and_header_boundary():
    legacy = McpLegacyDuplexHttpTransport("http://localhost/mcp")
    with pytest.raises(McpProtocolError, match="2025-11-25"):
        legacy.set_protocol_version("2025-06-18")
    for name in ("Last-Event-ID", "Host", "Mcp-Session-Id", "MCP-Protocol-Version"):
        with pytest.raises(ValueError):
            McpStreamingHttpTransport("http://localhost/mcp", headers={name: "unsafe"})


@pytest.mark.asyncio
async def test_notification_handler_can_close_transport_without_self_await():
    stream = Stream([frame({"jsonrpc": "2.0", "method": "notice"})], stall=True)
    async with mock_transport(stream) as (transport, calls, _):
        async def shutdown(_message):
            await transport.aclose()

        transport.set_notification_handler(shutdown)
        with pytest.raises(McpTransportError, match="closed"):
            await asyncio.wait_for(transport.send(request()), 2)
        assert stream.closed
        assert len(calls) == 1


@asynccontextmanager
async def loopback_server(handle):
    tasks, writers, calls, failures = set(), set(), [], []

    async def accepted(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        writers.add(writer)
        try:
            first = await reader.readline()
            method, path, _ = first.decode().strip().split(" ")
            headers = {}
            while (line := await reader.readline()) != b"\r\n":
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            body = await reader.readexactly(int(headers.get("content-length", "0")))
            value = json.loads(body) if body else None
            calls.append((method, path, headers, value))
            await handle(method, headers, value, reader, writer)
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as error:
            failures.append(error)
        finally:
            writer.close()
            await writer.wait_closed()
            writers.discard(writer)
            tasks.discard(task)

    server = await asyncio.start_server(accepted, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp", calls
    finally:
        server.close()
        await server.wait_closed()
        for writer in tuple(writers):
            writer.close()
        active = tuple(tasks)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        assert not server.sockets
        assert failures == []


async def reply(writer, payload=None, *, sse=False, session=None, status=200):
    body = payload if sse else (json.dumps(payload).encode() if payload is not None else b"")
    headers = f"HTTP/1.1 {status} OK\r\nContent-Type: {'text/event-stream' if sse else 'application/json'}\r\nConnection: close\r\n"
    if session:
        headers += f"Mcp-Session-Id: {session}\r\n"
    if not sse:
        headers += f"Content-Length: {len(body)}\r\n"
    writer.write(headers.encode() + b"\r\n" + body)
    await writer.drain()


@pytest.mark.asyncio
async def test_real_http_modern_subscription_is_live_with_parallel_request():
    disconnected = asyncio.Event()

    async def handle(method, headers, message, reader, writer):
        assert method == "POST"
        assert headers["mcp-protocol-version"] == "2026-07-28"
        if message["method"] == "subscriptions/listen":
            ack = {"jsonrpc": "2.0", "method": "notifications/subscriptions/acknowledged",
                   "params": {"_meta": {"io.modelcontextprotocol/subscriptionId": message["id"]},
                              "notifications": {"toolsListChanged": True}}}
            await reply(writer, frame(ack), sse=True)
            await reader.read()
            disconnected.set()
        else:
            await reply(writer, {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": []}})

    async with loopback_server(handle) as (endpoint, calls):
        async with McpClient(McpStreamingHttpTransport(endpoint)) as client:
            listener = client.listen({"toolsListChanged": True})
            assert (await asyncio.wait_for(anext(listener), 2))["method"].endswith("acknowledged")
            assert await client.list_tools() == ()
            await listener.aclose()
            await asyncio.wait_for(disconnected.wait(), 2)
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_real_legacy_http_post_callbacks_get_notifications_and_session():
    answered = asyncio.Event()
    callback_replies, notices = [], []

    async def handle(method, headers, message, reader, writer):
        if message and message.get("method") == "initialize":
            await reply(writer, {"jsonrpc": "2.0", "id": message["id"], "result": {
                "protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {"subscribe": True}},
                "serverInfo": {"name": "local", "version": "1"}}}, session="safe-session")
            return
        assert headers["mcp-session-id"] == "safe-session"
        assert headers["mcp-protocol-version"] == "2025-11-25"
        if method == "GET":
            await reply(writer, frame({"jsonrpc": "2.0", "id": "get-ping", "method": "ping"}) +
                        frame({"jsonrpc": "2.0", "method": "notifications/resources/updated",
                               "params": {"uri": "file:///safe"}}), sse=True)
            await reader.read()
        elif "method" not in message:
            callback_replies.append(message)
            answered.set()
            await reply(writer, status=202)
        elif message["method"] == "tools/call":
            await reply(writer, frame({"jsonrpc": "2.0", "id": "question", "method": "elicitation/create",
                                      "params": {"message": "Confirm?"}}), sse=True)
            await asyncio.wait_for(answered.wait(), 2)
            writer.write(frame({"jsonrpc": "2.0", "id": message["id"], "result": {"content": []}}))
            await writer.drain()
        else:
            await reply(writer, status=202)

    async def decline(params):
        return {"action": "decline"}

    async def notice(message):
        notices.append(message)

    async with loopback_server(handle) as (endpoint, calls):
        transport = McpLegacyDuplexHttpTransport(endpoint)
        async with McpLegacyClient(transport, supported_versions=("2025-11-25",),
                                   handlers=McpClientHandlers(elicitation=decline), notification_handler=notice) as client:
            assert (await client.call_tool("safe", {}))["content"] == []
            assert callback_replies[0]["result"] == {"action": "decline"}
            listener = transport.listen_notifications()
            assert (await asyncio.wait_for(anext(listener), 2))["params"]["uri"] == "file:///safe"
            await listener.aclose()
            assert callback_replies[1] == {"jsonrpc": "2.0", "id": "get-ping", "result": {}}
            assert len(notices) == 1
        assert all(path == "/mcp" for _, path, _, _ in calls)
        assert sum(method == "GET" for method, _, _, _ in calls) == 1
