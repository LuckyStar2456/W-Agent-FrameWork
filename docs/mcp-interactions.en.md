# Explicit MCP interactions and stdio subscriptions

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](mcp-interactions.md)

Workspace implementation; not released. `McpClient` keeps the stateless 2026-07-28 lifecycle; `McpLegacyClient` explicitly uses the 2025 initialization lifecycle. Neither silently switches protocols.

## Handlers and MRTR

```python
from w_agent.tools.mcp_client import McpClient
from w_agent.tools.mcp_duplex import McpDuplexStdioTransport
from w_agent.tools.mcp_handlers import McpClientHandlers

async def decline(params):
    # The application owns presentation, approval, and validation.
    return {"action": "decline"}

async with McpClient(
    McpDuplexStdioTransport(("python", "-m", "your_mcp_server")),
    handlers=McpClientHandlers(elicitation=decline),
    max_input_rounds=10,
    max_input_requests=32,
) as client:
    result = await client.call_tool("your_tool", {})
```

`sampling`, `elicitation`, and `roots` accept application-owned async callables receiving a params object and returning a protocol result object. They do not automatically invoke a model, open URLs, inspect directories, authorize tools, or approve operations. Declaring these capabilities without corresponding handlers fails. Elicitation defaults to form-only; URL support requires explicit `client_capabilities={"elicitation": {"form": {}, "url": {}}}`. Sampling tools require explicit `sampling.tools`. Applications own request/result schema validation, sampling budgets, approval, and redaction; this layer validates envelopes and declared interaction modes.

For modern `tools/call`, `prompts/get`, and `resources/read`, an `input_required` result is checked as a complete batch before callbacks execute. Each retry carries a fresh request ID, the original call arguments, keyed `inputResponses`, and the exact opaque `requestState`. Missing handlers, disabled fulfillment (`max_input_rounds=0`), or exhausted rounds raise `McpInputRequiredError`, preserving the unfinished result. Cancellation interrupts the active handler and prevents the next round.

Legacy clients use the same handlers with `McpDuplexStdioTransport` or the explicit 2025-11-25 `McpLegacyDuplexHttpTransport`. Interactive handlers cannot run before initialization; unknown methods return `-32601`, and callback exceptions return `-32603` without exception details. The original buffered legacy HTTP transport still rejects interactive handler configuration; see [live HTTP interactions](mcp-http-interactions.en.md) for the new transport. `subscribe_resource(uri)` and `unsubscribe_resource(uri)` require negotiated `resources.subscribe` support.

## Notifications

```python
from contextlib import aclosing

# Modern McpClient with McpDuplexStdioTransport.
async with aclosing(client.listen({"toolsListChanged": True})) as events:
    async for event in events:
        # First event is the acknowledged filter subset.
        if event["method"] == "notifications/tools/list_changed":
            tools = await client.list_tools()
            break
```

Subscriptions and ordinary calls may run concurrently. Subscription IDs route frames on the shared channel. Acknowledgment must precede changes, and the server cannot expand the requested filter. Tool-list changes invalidate cached schemas before callback delivery; no tool is automatically discovered or registered. Graceful completion ends iteration; disconnect raises. Use `aclosing` or `await events.aclose()` on early exit to send cancellation. Applications explicitly decide when to reconnect and refetch state.

`notification_handler` receives ordinary legacy stdio notifications in receive order. Keep it short, enqueue application work, and do not await a new request on the same client from this callback. Subscription iterator consumers may make requests. The duplex transport bounds pending requests, active server handlers, and queued frames. Overflow or malformed messages fail explicitly. Closing cleans up readers, handlers, and the subprocess. Process exit never triggers automatic restart or tool replay.

## Verification and limits

Run `py -3.11 -m pytest tests/test_mcp_client.py tests/test_mcp_interactions.py -q`. Coverage includes mock MRTR and real local stdio processes exercising legacy server requests, notifications, resource subscriptions, concurrent modern subscriptions/tool requests, cancellation, disconnect, and subscription scope rejection. No external model or paid tool is called.

Persistent 2026 POST subscriptions and explicit 2025 GET/server requests are available through [live HTTP transports](mcp-http-interactions.en.md), with their own related acceptance. 2024 endpoint-pair HTTP+SSE, automatic recovery, Tasks extensions, and external-server interoperability acceptance remain outside this increment. The original `McpStdioTransport` remains a simple request/response transport; persistent stdio notifications require the duplex variant. Sampling and Roots are deprecated by the 2026 specification but retained for compatibility; new applications should favor direct model integration and explicit resource parameters.

Sources: [2026 schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2026-07-28/schema.json), [2026 subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions), [2025 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [2026 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/).
