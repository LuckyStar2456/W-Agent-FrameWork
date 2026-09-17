"""MCP client adapter built on a transport-neutral public protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from w_agent.models import CancellationToken, ToolDefinition

from .types import ToolBinding, ToolExecutionContext, ToolSideEffect


@dataclass(frozen=True, slots=True)
class McpRemoteTool:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=lambda: {"type": "object"})

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("MCP remote tool name must not be empty")
        object.__setattr__(
            self,
            "input_schema",
            MappingProxyType(dict(self.input_schema)),
        )


class McpToolClient(Protocol):
    """Minimum client surface implemented by stdio, HTTP, or custom MCP plugins."""

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        cancellation: CancellationToken | None = None,
    ) -> Any: ...


def mcp_tool(
    remote: McpRemoteTool,
    client: McpToolClient,
    *,
    local_name: str | None = None,
    side_effect: ToolSideEffect = ToolSideEffect.EXTERNAL,
    required_permissions: frozenset[str] = frozenset({"mcp.call"}),
) -> ToolBinding:
    """Bind one discovered MCP tool to the common W-Agent tool runtime."""

    definition = ToolDefinition(
        local_name or remote.name,
        remote.description,
        dict(remote.input_schema),
    )

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        if context.cancellation is not None:
            context.cancellation.raise_if_cancelled()
        return await client.call_tool(
            remote.name,
            arguments,
            cancellation=context.cancellation,
        )

    return ToolBinding(
        definition,
        handler,
        side_effect,
        required_permissions,
        metadata={"adapter": "mcp", "remote_name": remote.name},
    )
