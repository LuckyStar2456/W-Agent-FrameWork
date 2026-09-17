import asyncio
import json
import sys

import pytest

from w_agent import (
    MCP_PROTOCOL_VERSION,
    CancellationToken,
    McpClient,
    McpHttpResponse,
    McpProtocolError,
    McpRemoteError,
    McpStdioTransport,
    McpStreamableHttpTransport,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolOutcome,
    ToolRegistry,
    discover_mcp_bindings,
)


class FakeRpcTransport:
    requires_tool_schema = False

    def __init__(self, results):
        self.results = list(results)
        self.messages = []
        self.schemas = []
        self.closed = False

    async def send(self, message, *, cancellation=None, tool_schema=None):
        self.messages.append(message)
        self.schemas.append(tool_schema)
        result = self.results.pop(0)
        if "error" in result:
            return {"jsonrpc": "2.0", "id": message["id"], **result}
        return {"jsonrpc": "2.0", "id": message["id"], "result": result}

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_mcp_client_paginates_discovery_and_sends_current_metadata():
    transport = FakeRpcTransport(
        [
            {
                "resultType": "complete",
                "tools": [
                    {
                        "name": "search",
                        "description": "Search.",
                        "inputSchema": {"type": "object"},
                    }
                ],
                "nextCursor": "page-2",
            },
            {
                "resultType": "complete",
                "tools": [
                    {
                        "name": "save",
                        "description": "Save.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"value": {"type": "string"}},
                        },
                        "outputSchema": {"type": "object"},
                        "annotations": {"destructiveHint": False},
                    }
                ],
            },
        ]
    )
    client = McpClient(transport)

    tools = await client.list_tools()

    assert [tool.name for tool in tools] == ["search", "save"]
    assert tools[1].output_schema == {"type": "object"}
    assert transport.messages[1]["params"]["cursor"] == "page-2"
    metadata = transport.messages[0]["params"]["_meta"]
    assert metadata["io.modelcontextprotocol/protocolVersion"] == MCP_PROTOCOL_VERSION
    assert metadata["io.modelcontextprotocol/clientInfo"]["name"] == "w-agent"
    assert metadata["io.modelcontextprotocol/clientCapabilities"] == {}


@pytest.mark.asyncio
async def test_mcp_discovery_returns_explicit_policy_enforced_bindings():
    transport = FakeRpcTransport(
        [
            {
                "tools": [
                    {
                        "name": "search",
                        "description": "Search.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    }
                ]
            },
            {
                "resultType": "complete",
                "content": [{"type": "text", "text": "found"}],
                "isError": False,
            },
        ]
    )
    client = McpClient(transport)
    bindings = await discover_mcp_bindings(client, local_name_prefix="docs_")
    registry = ToolRegistry()
    assert registry.bindings() == ()
    registry.register_binding(bindings[0])
    executor = ToolExecutor(registry)
    call = ToolCall("mcp-1", "docs_search", {"query": "agent"})

    denied = await executor.execute(call)
    assert denied.outcome == ToolOutcome.DENIED
    result = await executor.execute(
        call,
        ToolExecutionContext(
            permissions=frozenset({"mcp.call"}),
            approved_call_ids=frozenset({"mcp-1"}),
        ),
    )

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.data["content"][0]["text"] == "found"
    assert transport.messages[-1]["method"] == "tools/call"
    assert transport.messages[-1]["params"]["name"] == "search"


@pytest.mark.asyncio
async def test_mcp_client_surfaces_json_rpc_error_code():
    client = McpClient(
        FakeRpcTransport([{"error": {"code": -32601, "message": "missing"}}])
    )

    with pytest.raises(McpRemoteError) as raised:
        await client.list_tools()

    assert raised.value.code == -32601


class FakeHttpExchange:
    def __init__(self, *, use_sse=False, invalid_tool=False):
        self.requests = []
        self.use_sse = use_sse
        self.invalid_tool = invalid_tool

    async def post(self, request, *, cancellation=None):
        self.requests.append(request)
        message = json.loads(request.body)
        if message["method"] == "tools/list":
            tools = [
                {
                    "name": "lookup",
                    "description": "Lookup.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "region": {
                                "type": "string",
                                "x-mcp-header": "Region",
                            },
                            "query": {"type": "string"},
                        },
                    },
                }
            ]
            if self.invalid_tool:
                tools.insert(
                    0,
                    {
                        "name": "invalid",
                        "inputSchema": {
                            "type": "object",
                            "items": {
                                "type": "string",
                                "x-mcp-header": "Bad",
                            },
                        },
                    },
                )
            result = {"resultType": "complete", "tools": tools}
        else:
            result = {
                "resultType": "complete",
                "content": [{"type": "text", "text": "ok"}],
                "isError": False,
            }
        payload = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        if self.use_sse and message["method"] == "tools/call":
            notification = json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/progress"}
            )
            body = (
                f": keepalive\n\ndata: {notification}\n\n"
                f"data: {json.dumps(payload)}\n\n"
            ).encode()
            return McpHttpResponse(200, {"content-type": "text/event-stream"}, body)
        return McpHttpResponse(
            200,
            {"content-type": "application/json; charset=utf-8"},
            json.dumps(payload).encode(),
        )


@pytest.mark.asyncio
async def test_streamable_http_discovers_filters_and_mirrors_required_headers():
    exchange = FakeHttpExchange(use_sse=True, invalid_tool=True)
    transport = McpStreamableHttpTransport(
        "https://mcp.example.test/mcp",
        headers={"authorization": "Bearer local-secret"},
        exchange=exchange,
    )
    client = McpClient(transport)

    tools = await client.list_tools()
    result = await client.call_tool(
        "lookup",
        {"region": "杭州", "query": "agent"},
    )

    assert [tool.name for tool in tools] == ["lookup"]
    assert result["content"][0]["text"] == "ok"
    request = exchange.requests[-1]
    assert request.headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION
    assert request.headers["Mcp-Method"] == "tools/call"
    assert request.headers["Mcp-Name"] == "lookup"
    assert request.headers["Mcp-Param-Region"].startswith("=?base64?")
    assert request.headers["authorization"] == "Bearer local-secret"
    assert "local-secret" not in request.body.decode()


@pytest.mark.asyncio
async def test_stdio_transport_runs_shell_free_server_and_closes_cleanly():
    server = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "tools/list":
        result = {"resultType": "complete", "tools": [{"name": "echo", "description": "Echo.", "inputSchema": {"type": "object"}}]}
    elif request.get("method") == "tools/call":
        result = {"resultType": "complete", "content": [{"type": "text", "text": request["params"]["arguments"].get("text", "")}], "isError": False}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
"""
    transport = McpStdioTransport((sys.executable, "-u", "-c", server))
    async with McpClient(transport) as client:
        tools = await client.list_tools()
        result = await client.call_tool("echo", {"text": "hello; exit 9"})

    assert [tool.name for tool in tools] == ["echo"]
    assert result["content"][0]["text"] == "hello; exit 9"


def test_streamable_http_rejects_transport_owned_static_headers():
    with pytest.raises(ValueError, match="transport-owned"):
        McpStreamableHttpTransport(
            "https://mcp.example.test/mcp",
            headers={"Mcp-Method": "spoof"},
        )


@pytest.mark.asyncio
async def test_streamable_http_cancellation_stops_custom_exchange():
    class BlockingExchange:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = False

        async def post(self, request, *, cancellation=None):
            self.started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    exchange = BlockingExchange()
    client = McpClient(
        McpStreamableHttpTransport(
            "https://mcp.example.test/mcp",
            exchange=exchange,
        )
    )
    token = CancellationToken()
    pending = asyncio.create_task(client.list_tools(cancellation=token))
    await exchange.started.wait()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending

    assert exchange.cancelled is True


@pytest.mark.asyncio
async def test_mcp_client_rejects_repeated_pagination_cursor():
    transport = FakeRpcTransport(
        [
            {"tools": [], "nextCursor": "same"},
            {"tools": [], "nextCursor": "same"},
        ]
    )

    with pytest.raises(McpProtocolError, match="repeated"):
        await McpClient(transport).list_tools()
