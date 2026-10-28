"""Actual editable templates, registered handlers and two-turn offline results."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from w_agent import (
    MessageRole, StopReason, ToolResultContent, ToolSideEffect, coding_agent,
    customer_support_agent, python_tool,
)


@pytest.fixture
def example():
    # Examples are source files, not a wheel-provided Python package.
    path = Path(__file__).parents[1] / "examples" / "basic_development.py"
    spec = importlib.util.spec_from_file_location("project_basic_development", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["support", "coding"])
async def test_actual_template_tool_roundtrip_and_owned_provider_close(example, mode):
    provider = example.OfflineToolModel(mode)
    definition = customer_support_agent(model="demo") if mode == "support" else coding_agent(model="demo")
    bindings = example.support_tools() if mode == "support" else example.coding_tools("def multiply(x, y): return x * y")
    permissions = frozenset({"knowledge.read" if mode == "support" else "workspace.read"})
    result = await example.run_with_provider(provider, definition, bindings, "Read approved sample data", permissions)
    assert result.stop_reason is StopReason.COMPLETED
    assert (result.steps, result.tool_calls) == (2, 1)
    assert provider.closed and provider.close_calls == 1 and len(provider.requests) == 2
    assert provider.requests[0].messages[0].role is MessageRole.SYSTEM
    assert provider.requests[0].messages[0].content[0].text == definition.system_prompt
    returned = [block for message in provider.requests[1].messages for block in message.content if isinstance(block, ToolResultContent)]
    assert len(returned) == 1 and not returned[0].is_error
    payload = json.loads(returned[0].content)
    if mode == "support":
        assert payload["documents"][0]["source"] == "sample:returns"
        assert payload["documents"][0]["text"] in result.output
    else:
        assert payload["source"] == "def multiply(x, y): return x * y"
        assert payload["source"] in result.output


@pytest.mark.asyncio
async def test_template_prompt_never_grants_missing_permission(example):
    calls = []
    def read_sample_module():
        calls.append(True)
        return {"source": "must not be reached"}
    binding = python_tool(read_sample_module, required_permissions=frozenset({"workspace.read"}))
    provider = example.OfflineToolModel("coding")
    result = await example.run_with_provider(provider, coding_agent(model="demo"), (binding,), "Read", frozenset())
    assert not calls and provider.closed
    assert result.stop_reason is StopReason.COMPLETED and "denied or failed" in result.output


@pytest.mark.asyncio
async def test_write_requires_call_approval_even_with_permission(example):
    calls = []
    def read_sample_module():
        calls.append(True)
        return {"source": "changed"}
    binding = python_tool(read_sample_module, side_effect=ToolSideEffect.WRITE,
                          required_permissions=frozenset({"workspace.write"}))
    provider = example.OfflineToolModel("coding")
    result = await example.run_with_provider(provider, coding_agent(model="demo"), (binding,), "Write", frozenset({"workspace.write"}))
    assert result.stop_reason is StopReason.NEEDS_APPROVAL
    assert result.pending_tool_call.id == "demo-read-1"
    assert not calls and provider.closed and len(provider.requests) == 1


@pytest.mark.asyncio
async def test_registration_failure_still_closes_owned_provider(example):
    provider = example.OfflineToolModel("coding")
    binding = example.coding_tools()[0]
    with pytest.raises(Exception):
        await example.run_with_provider(provider, coding_agent(model="demo"), (binding, binding), "Read", frozenset({"workspace.read"}))
    assert provider.closed and provider.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_handler_closes_owned_provider(example):
    async def read_sample_module():
        raise asyncio.CancelledError
    provider = example.OfflineToolModel("coding")
    with pytest.raises(asyncio.CancelledError):
        await example.run_with_provider(provider, coding_agent(model="demo"),
            (python_tool(read_sample_module),), "Read", frozenset())
    assert provider.closed and provider.close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["support", "coding"])
async def test_copyable_demo_main_flow(example, mode):
    result = await example.run_demo(mode)
    assert result.stop_reason is StopReason.COMPLETED and result.tool_calls == 1
