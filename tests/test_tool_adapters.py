import json
import sys
import asyncio

import pytest

from w_agent import (
    CancellationToken,
    HttpToolRequest,
    HttpToolResponse,
    McpRemoteTool,
    ToolCall,
    ToolExecutionContext,
    ToolExecutor,
    ToolOutcome,
    ToolRegistry,
    command_tool,
    http_tool,
    mcp_tool,
)


STRING_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


class FakeHttpTransport:
    def __init__(self, response=None):
        self.response = response or HttpToolResponse(
            200,
            {"content-type": "application/json"},
            b'{"ok":true}',
        )
        self.requests = []
        self.cancellations = []

    async def send(self, request, *, cancellation=None):
        self.requests.append(request)
        self.cancellations.append(cancellation)
        return self.response


@pytest.mark.asyncio
async def test_http_tool_uses_policy_fixed_endpoint_and_default_json_mapping():
    transport = FakeHttpTransport()
    binding = http_tool(
        "remote_write",
        "Write to a fixed service.",
        STRING_SCHEMA,
        url="https://service.invalid/items",
        headers={"x-client": "w-agent"},
        transport=transport,
    )
    tools = ToolRegistry()
    tools.register_binding(binding)
    executor = ToolExecutor(tools)
    call = ToolCall("http-1", "remote_write", {"value": "hello"})

    denied = await executor.execute(call)
    assert denied.outcome == ToolOutcome.DENIED
    pending = await executor.execute(
        call,
        ToolExecutionContext(permissions=frozenset({"network.http"})),
    )
    assert pending.outcome == ToolOutcome.NEEDS_APPROVAL

    token = CancellationToken()
    result = await executor.execute(
        call,
        ToolExecutionContext(
            permissions=frozenset({"network.http"}),
            approved_call_ids=frozenset({"http-1"}),
            cancellation=token,
        ),
    )

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.data == {"status": 200, "data": {"ok": True}}
    request = transport.requests[0]
    assert request.url == "https://service.invalid/items"
    assert request.method == "POST"
    assert request.query == {}
    assert request.json_body == {"value": "hello"}
    assert request.headers == {"x-client": "w-agent"}
    assert transport.cancellations == [token]


@pytest.mark.asyncio
async def test_http_tool_supports_custom_mapping_and_sanitizes_remote_failures():
    transport = FakeHttpTransport(
        HttpToolResponse(503, {"content-type": "text/plain"}, b"secret body")
    )
    binding = http_tool(
        "lookup",
        "Lookup.",
        STRING_SCHEMA,
        url="https://unused.invalid",
        transport=transport,
        request_builder=lambda arguments: HttpToolRequest(
            "GET",
            "https://service.invalid/search",
            query={"q": arguments["value"]},
        ),
    )
    tools = ToolRegistry()
    tools.register_binding(binding)
    result = await ToolExecutor(tools).execute(
        ToolCall("http-2", "lookup", {"value": "term"}),
        ToolExecutionContext(
            permissions=frozenset({"network.http"}),
            approved_call_ids=frozenset({"http-2"}),
        ),
    )

    assert result.outcome == ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.code == "tool-execution-failed"
    assert "secret body" not in result.failure.message
    assert transport.requests[0].query == {"q": "term"}


@pytest.mark.asyncio
async def test_command_tool_is_shell_free_and_policy_enforced():
    binding = command_tool(
        "echo_argument",
        "Echo one literal argument.",
        STRING_SCHEMA,
        executable=sys.executable,
        argument_builder=lambda arguments: (
            "-c",
            "import json,sys; print(json.dumps(sys.argv[1]))",
            arguments["value"],
        ),
    )
    tools = ToolRegistry()
    tools.register_binding(binding)
    executor = ToolExecutor(tools)
    call = ToolCall("command-1", "echo_argument", {"value": "hello; exit 99"})

    pending = await executor.execute(
        call,
        ToolExecutionContext(permissions=frozenset({"process.execute"})),
    )
    assert pending.outcome == ToolOutcome.NEEDS_APPROVAL
    result = await executor.execute(
        call,
        ToolExecutionContext(
            permissions=frozenset({"process.execute"}),
            approved_call_ids=frozenset({"command-1"}),
        ),
    )

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert json.loads(result.data["stdout"]) == "hello; exit 99"
    assert result.data["exit_code"] == 0


@pytest.mark.asyncio
async def test_command_tool_bounds_output_and_normalizes_nonzero_exit():
    tools = ToolRegistry()
    tools.register_binding(
        command_tool(
            "too_much",
            "Produce bounded output.",
            {"type": "object", "additionalProperties": False},
            executable=sys.executable,
            argument_builder=lambda arguments: ("-c", "print('x' * 5000)"),
            max_output_bytes=100,
        )
    )
    tools.register_binding(
        command_tool(
            "fails",
            "Exit non-zero.",
            {"type": "object", "additionalProperties": False},
            executable=sys.executable,
            argument_builder=lambda arguments: ("-c", "raise SystemExit(7)"),
        )
    )
    context = ToolExecutionContext(
        permissions=frozenset({"process.execute"}),
        approved_call_ids=frozenset({"large-1", "fail-1"}),
    )

    too_large = await ToolExecutor(tools).execute(
        ToolCall("large-1", "too_much", {}),
        context,
    )
    failed = await ToolExecutor(tools).execute(
        ToolCall("fail-1", "fails", {}),
        context,
    )

    assert too_large.outcome == ToolOutcome.FAILED
    assert too_large.failure is not None
    assert too_large.failure.code == "tool-execution-failed"
    assert failed.outcome == ToolOutcome.FAILED
    assert failed.failure is not None
    assert "7" not in failed.failure.message


@pytest.mark.asyncio
async def test_command_tool_cancellation_terminates_child_process():
    tools = ToolRegistry()
    tools.register_binding(
        command_tool(
            "wait",
            "Wait until cancelled.",
            {"type": "object", "additionalProperties": False},
            executable=sys.executable,
            argument_builder=lambda arguments: (
                "-c",
                "import time; time.sleep(30)",
            ),
        )
    )
    token = CancellationToken()
    pending = asyncio.create_task(
        ToolExecutor(tools, timeout=5).execute(
            ToolCall("wait-1", "wait", {}),
            ToolExecutionContext(
                permissions=frozenset({"process.execute"}),
                approved_call_ids=frozenset({"wait-1"}),
                cancellation=token,
            ),
        )
    )
    await asyncio.sleep(0.1)
    token.cancel()

    result = await pending
    assert result.outcome == ToolOutcome.CANCELLED


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments, *, cancellation=None):
        self.calls.append((name, dict(arguments), cancellation))
        return {"remote": name, "arguments": dict(arguments)}


@pytest.mark.asyncio
async def test_mcp_tool_adapts_remote_definition_through_common_runtime():
    client = FakeMcpClient()
    binding = mcp_tool(
        McpRemoteTool("search", "Search remotely.", STRING_SCHEMA),
        client,
        local_name="knowledge_search",
    )
    assert binding.definition.name == "knowledge_search"
    assert binding.metadata["remote_name"] == "search"
    tools = ToolRegistry()
    tools.register_binding(binding)
    result = await ToolExecutor(tools).execute(
        ToolCall("mcp-1", "knowledge_search", {"value": "agent"}),
        ToolExecutionContext(
            permissions=frozenset({"mcp.call"}),
            approved_call_ids=frozenset({"mcp-1"}),
        ),
    )

    assert result.outcome == ToolOutcome.SUCCEEDED
    assert result.data == {
        "remote": "search",
        "arguments": {"value": "agent"},
    }
    assert client.calls == [("search", {"value": "agent"}, None)]
