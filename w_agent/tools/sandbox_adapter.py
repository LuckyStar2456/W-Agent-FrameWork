"""Bind sandbox commands to the common policy-enforced tool runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from w_agent.models import ToolDefinition
from w_agent.sandbox import SandboxCommand, SandboxProvider, SandboxSpec

from .types import ToolBinding, ToolExecutionContext, ToolSideEffect


SandboxCommandBuilder = Callable[[Mapping[str, Any]], SandboxCommand]


def sandbox_command_tool(
    name: str,
    description: str,
    input_schema: Mapping[str, Any],
    *,
    provider: SandboxProvider,
    sandbox: SandboxSpec,
    command_builder: SandboxCommandBuilder,
    side_effect: ToolSideEffect = ToolSideEffect.WRITE,
    required_permissions: frozenset[str] = frozenset({"sandbox.execute"}),
) -> ToolBinding:
    """Open a sandbox for one tool call and always close its handle."""

    definition = ToolDefinition(name, description, dict(input_schema))

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        command = command_builder(arguments)
        if not isinstance(command, SandboxCommand):
            raise TypeError("sandbox command_builder must return SandboxCommand")
        handle = await provider.open(
            sandbox,
            cancellation=context.cancellation,
        )
        try:
            result = await handle.execute(
                command,
                cancellation=context.cancellation,
            )
            return {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        finally:
            await handle.close()

    return ToolBinding(
        definition,
        handler,
        side_effect,
        required_permissions,
        metadata={"adapter": "sandbox-command"},
    )
