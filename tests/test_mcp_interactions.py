import asyncio
import json
import sys

import pytest

from w_agent.models import CancellationToken
from w_agent.tools.mcp_client import McpClient, McpInputRequiredError, McpProtocolError, McpTransportError
from w_agent.tools.mcp_duplex import McpDuplexStdioTransport
from w_agent.tools.mcp_handlers import McpClientHandlers
from w_agent.tools.mcp_legacy import McpLegacyClient


class Rpc:
    def __init__(self, results):
        self.results = iter(results)
        self.messages = []

    async def send(self, message, **kwargs):
        self.messages.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], "result": next(self.results)}

    async def aclose(self):
        pass


def required(method="elicitation/create", state=" opaque+/= "):
    return {"resultType": "input_required", "requestState": state,
            "inputRequests": {"confirm": {"method": method, "params": {"message": "Confirm?"}}}}


@pytest.mark.asyncio
async def test_mrtr_preserves_original_params_and_opaque_state_with_fresh_id():
    calls = []

    async def handler(params):
        calls.append(params)
        return {"action": "decline"}

    transport = Rpc([required(), {"resultType": "complete", "content": []}])
    client = McpClient(transport, handlers=McpClientHandlers(elicitation=handler))
    assert (await client.call_tool("safe", {"x": 1}))["content"] == []
    first, retry = transport.messages
    assert first["id"] != retry["id"]
    assert retry["params"]["requestState"] == " opaque+/= "
    assert retry["params"]["inputResponses"] == {"confirm": {"action": "decline"}}
    assert retry["params"]["arguments"] == {"x": 1}
    assert first["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"] == {"elicitation": {"form": {}}}
    assert calls == [{"message": "Confirm?"}]


@pytest.mark.asyncio
async def test_mrtr_checks_all_handlers_before_any_callback():
    calls = []

    async def handler(params):
        calls.append(params)
        return {}

    result = required()
    result["inputRequests"]["hidden"] = {"method": "sampling/createMessage", "params": {}}
    transport = Rpc([result])
    client = McpClient(transport, handlers=McpClientHandlers(elicitation=handler))
    with pytest.raises(McpInputRequiredError):
        await client.call_tool("safe", {})
    assert calls == []
    assert len(transport.messages) == 1


@pytest.mark.asyncio
async def test_mrtr_round_bound_and_no_implicit_handler():
    async def handler(params):
        return {"action": "cancel"}

    transport = Rpc([required(), required()])
    client = McpClient(transport, handlers=McpClientHandlers(elicitation=handler), max_input_rounds=1)
    with pytest.raises(McpInputRequiredError):
        await client.call_tool("safe", {})
    assert len(transport.messages) == 2
    with pytest.raises(McpInputRequiredError):
        await McpClient(Rpc([required()])).call_tool("safe", {})


@pytest.mark.parametrize("capability", ["sampling", "elicitation", "roots"])
def test_capability_configuration_cannot_grant_handler_authority(capability):
    with pytest.raises(ValueError, match="explicit handler"):
        McpClient(Rpc([]), client_capabilities={capability: {}})


@pytest.mark.asyncio
async def test_mrtr_cancellation_interrupts_handler_without_retry():
    started = asyncio.Event()

    async def handler(params):
        started.set()
        await asyncio.Event().wait()

    token = CancellationToken()
    transport = Rpc([required()])
    client = McpClient(transport, handlers=McpClientHandlers(elicitation=handler))
    task = asyncio.create_task(client.call_tool("safe", {}, cancellation=token))
    await asyncio.wait_for(started.wait(), 2)
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(transport.messages) == 1


LEGACY_SERVER = r'''
import json, sys
def send(value):
    print(json.dumps(value), flush=True)
pending = None
for line in sys.stdin:
    m = json.loads(line)
    method = m.get("method")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":m["id"],"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{},"resources":{"subscribe":True}},"serverInfo":{"name":"test","version":"1"}}})
    elif method == "tools/call":
        pending = m["id"]
        send({"jsonrpc":"2.0","id":"srv-1","method":"elicitation/create","params":{"message":"Confirm?"}})
    elif m.get("id") == "srv-1":
        send({"jsonrpc":"2.0","method":"notifications/tools/list_changed"})
        send({"jsonrpc":"2.0","id":pending,"result":{"content":[],"structuredContent":{"reply":m}}})
    elif method in ("resources/subscribe", "resources/unsubscribe"):
        send({"jsonrpc":"2.0","id":m["id"],"result":{}})
'''


@pytest.mark.asyncio
async def test_legacy_stdio_server_request_notification_and_resource_subscription():
    notifications = []

    async def handler(params):
        return {"action": "decline"}

    async def notice(message):
        notifications.append(message)

    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", LEGACY_SERVER))
    async with McpLegacyClient(transport, handlers=McpClientHandlers(elicitation=handler), notification_handler=notice) as client:
        result = await client.call_tool("safe", {})
        assert result["structuredContent"]["reply"]["result"] == {"action": "decline"}
        assert notifications[0]["method"] == "notifications/tools/list_changed"
        assert await client.subscribe_resource("file:///safe") == {}
        assert await client.unsubscribe_resource("file:///safe") == {}
    assert transport._process is None


@pytest.mark.asyncio
async def test_legacy_unregistered_request_returns_method_not_found():
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", LEGACY_SERVER))
    async with McpLegacyClient(transport) as client:
        result = await client.call_tool("safe", {})
        assert result["structuredContent"]["reply"]["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_legacy_callback_failure_does_not_disclose_secret():
    async def fail(params):
        raise RuntimeError("private-secret")

    reply = await McpClientHandlers(elicitation=fail).respond({"id": 1, "method": "elicitation/create"})
    assert reply["error"]["code"] == -32603
    assert "private-secret" not in json.dumps(reply)


SUB_SERVER = r'''
import json, sys
sub = None
def send(value):
    print(json.dumps(value), flush=True)
def notification(method, **params):
    send({"jsonrpc":"2.0","method":method,"params":{"_meta":{"io.modelcontextprotocol/subscriptionId":sub},**params}})
for line in sys.stdin:
    m=json.loads(line)
    if m.get("method") == "subscriptions/listen":
        sub=m["id"]
        notification("notifications/subscriptions/acknowledged", notifications={"toolsListChanged":True})
    elif m.get("method") == "tools/list":
        notification("notifications/tools/list_changed")
        send({"jsonrpc":"2.0","id":m["id"],"result":{"tools":[]}})
        send({"jsonrpc":"2.0","id":sub,"result":{"resultType":"complete","_meta":{"io.modelcontextprotocol/subscriptionId":sub}}})
'''


@pytest.mark.asyncio
async def test_modern_stdio_subscription_allows_concurrent_requests_and_graceful_end():
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", SUB_SERVER))
    async with McpClient(transport) as client:
        stream = client.listen({"toolsListChanged": True})
        ack = await asyncio.wait_for(anext(stream), 2)
        assert ack["method"].endswith("acknowledged")
        client._tool_schemas["stale"] = {}
        assert await client.list_tools() == ()
        assert (await anext(stream))["method"] == "notifications/tools/list_changed"
        assert client._tool_schemas == {}
        with pytest.raises(StopAsyncIteration):
            await anext(stream)


class StreamRpc(Rpc):
    async def stream(self, message, **kwargs):
        self.closed = False
        try:
            for event in self.results:
                yield event
        finally:
            self.closed = True


def event(method, **params):
    return {"jsonrpc": "2.0", "method": method, "params": {"_meta": {"io.modelcontextprotocol/subscriptionId": 1}, **params}}


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [
    [event("notifications/tools/list_changed")],
    [event("notifications/subscriptions/acknowledged", notifications={"resourcesListChanged": True})],
    [event("notifications/subscriptions/acknowledged", notifications={"toolsListChanged": True}), event("notifications/resources/updated", uri="file:///secret")],
])
async def test_subscription_rejects_invalid_order_or_unrequested_events(events):
    transport = StreamRpc(events)
    with pytest.raises(McpProtocolError):
        async for _ in McpClient(transport).listen({"toolsListChanged": True}):
            pass
    assert transport.closed


@pytest.mark.asyncio
async def test_subscription_disconnect_is_not_graceful_completion():
    transport = StreamRpc([event("notifications/subscriptions/acknowledged", notifications={})])
    with pytest.raises(McpTransportError, match="disconnected"):
        async for _ in McpClient(transport).listen({"toolsListChanged": True}):
            pass
    assert transport.closed


@pytest.mark.asyncio
async def test_stdio_early_subscription_close_sends_cancel_and_keeps_transport_alive():
    server = r'''
import json, sys
cancelled = False
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "subscriptions/listen":
        print(json.dumps({"jsonrpc":"2.0","method":"notifications/subscriptions/acknowledged","params":{"_meta":{"io.modelcontextprotocol/subscriptionId":m["id"]},"notifications":{}}}),flush=True)
    elif m.get("method") == "notifications/cancelled":
        cancelled = True
    elif m.get("method") == "tools/list":
        print(json.dumps({"jsonrpc":"2.0","id":m["id"],"result":{"tools":[],"cancelled":cancelled}}),flush=True)
'''
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", server))
    async with McpClient(transport) as client:
        stream = client.listen({"toolsListChanged": True})
        await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()
        assert (await client.request("tools/list"))["cancelled"] is True


@pytest.mark.asyncio
async def test_duplex_response_followed_by_eof_is_preserved_without_replay():
    server = 'import sys,json; m=json.loads(sys.stdin.readline()); print(json.dumps({"jsonrpc":"2.0","id":m["id"],"result":{"tools":[]}}),flush=True)'
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", server))
    async with McpClient(transport) as client:
        assert await client.list_tools() == ()
        await asyncio.sleep(0.1)
        with pytest.raises(McpTransportError, match="disconnected"):
            await client.list_tools()


@pytest.mark.asyncio
async def test_mrtr_rejects_undeclared_elicitation_mode_before_callback():
    called = []

    async def handler(params):
        called.append(params)
        return {"action": "accept"}

    result = required()
    result["inputRequests"]["confirm"]["params"]["mode"] = "url"
    client = McpClient(Rpc([result]), handlers=McpClientHandlers(elicitation=handler))
    with pytest.raises(McpProtocolError, match="undeclared"):
        await client.call_tool("safe", {})
    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    {"resultType": "input_required"},
    {"resultType": "input_required", "requestState": None},
    {"resultType": "input_required", "inputRequests": []},
])
async def test_mrtr_rejects_malformed_input_required(result):
    with pytest.raises(McpProtocolError):
        await McpClient(Rpc([result])).call_tool("safe", {})


@pytest.mark.asyncio
async def test_subscription_ack_timeout_cancels_and_cleans_route():
    server = 'import sys; [None for line in sys.stdin]'
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", server), request_timeout=0.2)
    async with McpClient(transport) as client:
        stream = client.listen({"toolsListChanged": True})
        with pytest.raises(McpTransportError, match="acknowledgment timed out"):
            await anext(stream)
        assert transport._routes == {}


@pytest.mark.asyncio
async def test_subscription_queue_overflow_fails_without_silent_event_loss():
    server = r'''
import sys,json
m=json.loads(sys.stdin.readline())
for n in range(50):
    print(json.dumps({"jsonrpc":"2.0","method":"notifications/tools/list_changed","params":{"_meta":{"io.modelcontextprotocol/subscriptionId":m["id"]}}}),flush=True)
for line in sys.stdin:
    pass
'''
    transport = McpDuplexStdioTransport((sys.executable, "-u", "-c", server), max_queued=1)
    async with McpClient(transport) as client:
        with pytest.raises(McpProtocolError):
            async for _ in client.listen({"toolsListChanged": True}):
                pass
