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
    title: str | None = None
    output_schema: Mapping[str, Any] | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("MCP remote tool name must not be empty")
        object.__setattr__(
            self,
            "input_schema",
            MappingProxyType(dict(self.input_schema)),
        )
        if self.title is not None and not isinstance(self.title, str):
            raise TypeError("MCP remote tool title must be text")
        if self.output_schema is not None:
            object.__setattr__(
                self,
                "output_schema",
                MappingProxyType(dict(self.output_schema)),
            )
        object.__setattr__(
            self,
            "annotations",
            MappingProxyType(dict(self.annotations)),
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


class McpToolDiscoveryClient(McpToolClient, Protocol):
    async def list_tools(
        self,
        *,
        cancellation: CancellationToken | None = None,
    ) -> tuple[McpRemoteTool, ...]: ...


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


async def discover_mcp_bindings(
    client: McpToolDiscoveryClient,
    *,
    local_name_prefix: str = "",
    side_effect: ToolSideEffect = ToolSideEffect.EXTERNAL,
    required_permissions: frozenset[str] = frozenset({"mcp.call"}),
    cancellation: CancellationToken | None = None,
) -> tuple[ToolBinding, ...]:
    """Discover remote definitions and return bindings without registering them.

    Registration stays explicit so discovery never grants model visibility,
    permissions, or execution authority by itself.
    """

    remotes = await client.list_tools(cancellation=cancellation)
    bindings: list[ToolBinding] = []
    names: set[str] = set()
    for remote in remotes:
        local_name = f"{local_name_prefix}{remote.name}"
        if local_name in names:
            raise ValueError(f"duplicate discovered MCP tool name: {local_name}")
        names.add(local_name)
        bindings.append(
            mcp_tool(
                remote,
                client,
                local_name=local_name,
                side_effect=side_effect,
                required_permissions=required_permissions,
            )
        )
    return tuple(bindings)
