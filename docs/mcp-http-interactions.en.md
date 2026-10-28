# Live MCP HTTP interactions

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](mcp-http-interactions.md)

Workspace implementation, not released. Choose a protocol explicitly; neither transport discovers endpoints, changes protocols, follows redirects, reconnects, or replays a request. Existing buffered HTTP transports remain available and unchanged. These transports require HTTPX (the `models` extra); an injected `httpx.AsyncClient` is borrowed and is not closed by the transport. The default client disables environment proxies and redirects. Endpoint credentials, TLS, proxy settings and application authority remain host decisions.

## Modern POST subscriptions

`McpStreamingHttpTransport` implements **2026-07-28** POST JSON and incremental SSE responses. Modern HTTP has no GET listener, session ID, independent server request, or Last-Event-ID recovery. Sampling/elicitation/roots interactions continue through the existing MRTR client path. See the official [2026 HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http) and [subscription pattern](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions).

```python
from contextlib import aclosing
from w_agent.tools import McpClient, McpStreamingHttpTransport

async with McpClient(McpStreamingHttpTransport(
    "http://127.0.0.1:8000/mcp",
    idle_timeout=60,
    max_stream_seconds=3600,
)) as client:
    async with aclosing(client.listen({"toolsListChanged": True})) as events:
        async for event in events:
            # First event acknowledges the accepted filter subset.
            if event["method"] == "notifications/tools/list_changed":
                tools = await client.list_tools()
                break
```

Acknowledgment/filter/correlation checks reuse `McpClient.listen`. Change notifications invalidate the tool-schema cache before application delivery. Ordinary requests can run concurrently on separate HTTP streams. Protocol version, method, name/URI, and schema-declared tool argument headers use the existing encoding rules. Closing the subscription response cancels modern HTTP listening; it does **not** POST a cancellation notification. On disconnect or an exceeded bound the iterator fails. Refetch current state before explicitly creating a fresh subscription; there is no gap-free delivery claim.

## Explicit legacy callbacks and GET notifications

`McpLegacyDuplexHttpTransport` supports only **2025-11-25**, with the initialization lifecycle, session header propagation, server requests on POST SSE, and an explicitly opened GET SSE listener. It does not implement the older two-endpoint HTTP+SSE discovery transport. These behaviors follow the [2025 transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

```python
from contextlib import aclosing
from w_agent.tools import (
    McpClientHandlers, McpLegacyClient, McpLegacyDuplexHttpTransport,
)

async def decline(params):
    return {"action": "decline"}  # Host owns presentation, approval and validation.

transport = McpLegacyDuplexHttpTransport("http://127.0.0.1:8000/mcp")
async with McpLegacyClient(
    transport, supported_versions=("2025-11-25",),
    handlers=McpClientHandlers(elicitation=decline),
) as client:
    await client.initialize()
    result = await client.call_tool("safe", {})
    await client.subscribe_resource("file:///safe")
    try:
        async with aclosing(transport.listen_notifications()) as events:
            async for event in events:
                if event["method"] == "notifications/resources/updated":
                    break
    finally:
        await client.unsubscribe_resource("file:///safe")
```

Callbacks are handled and their replies POSTed to the same fixed endpoint, requiring empty HTTP 202 acceptance. Unknown methods return a protocol error; registered handlers do not grant implicit model, filesystem, URL-opening, or approval authority. The legacy client blocks interactive callbacks before initialization. Notification callbacks run before notifications are yielded; keep callbacks short. Separate HTTP requests are possible from a callback subject to the shared stream limit (callback replies themselves need one additional stream).

Session header changes, malformed headers, 404 expiry, GET rejection, malformed messages, and premature disconnect fail explicitly. The transport never initializes a replacement session or retries a tool. A legacy interrupted POST attempts one bounded `notifications/cancelled` POST; acceptance is not assumed. Closing a GET stream does not unsubscribe resources or DELETE a session; manage subscriptions explicitly. Server request IDs are remembered within the transport lifetime and must remain unique, avoiding repeated callback side effects; reaching the callback ID bound fails closed. This is a deliberately stricter no-replay boundary, not persisted deduplication across transport instances.

## Resource bounds and lifecycle

Defaults: request deadline 30 seconds, idle read deadline 60 seconds, stream read lifetime 3600 seconds, request body 4 MiB, individual message/SSE line 1 MiB, total decoded stream 64 MiB, 10,000 SSE messages, and 16 concurrent HTTP exchanges. All bounds are configurable within validated finite limits. Each next network read enforces the remaining lifetime; an iterator paused by the host does not read or schedule keepalives and must be explicitly closed. The stream limit still includes paused iterators. Use `aclosing` on early exit and close the client/transport during host shutdown.

Duplicate JSON keys, non-finite values, JSON batches, mismatched response IDs, endpoint-discovery events, incomplete frames, and modern independent server requests are rejected. SSE comments and cursor fields are consumed within byte bounds but never activate replay. Cancellation interrupts outstanding reads and handlers. Exceptions do not include response bodies or endpoint credentials. An HTTP/network failure may leave the remote operation outcome unknown; do not infer that cancellation rolled back a remote side effect.

## Verification and remaining scope

`python -m pytest tests/test_mcp_http_duplex.py tests/test_mcp_client.py tests/test_mcp_interactions.py -q`: **62 passed** in the existing isolated Python 3.11 environment. The 26 new tests include real temporary **127.0.0.1-only** HTTP servers for incremental modern subscription/concurrent requests and legacy session/callback/GET interaction. Servers, sockets and connection tasks are closed in test cleanup. Other cases use mock HTTPX streams. No external or paid service was contacted.

Not implemented/accepted here: automatic reconnect, cursor replay, 2024 endpoint discovery, session DELETE, OAuth discovery, resumable Tasks, external-server interoperability certification, and platform UI notification presentation. There is no new automatic authorization policy or sandbox. This is an opt-in library transport, not a hosted service.
