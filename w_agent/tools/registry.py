"""Scoped tool registration on the shared W-Agent registry."""

from __future__ import annotations

from w_agent.kernel import Contribution, Registration, Registry, ScopePath
from w_agent.models import ToolDefinition

from .types import ToolBinding, ToolHandler, ToolSideEffect


TOOL_CAPABILITY = "tool.binding"


class ToolRegistry:
    """Register definitions and handlers without coupling either to policy."""

    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        side_effect: ToolSideEffect = ToolSideEffect.READ,
        required_permissions: frozenset[str] = frozenset(),
        version: str = "0",
        scope: ScopePath | None = None,
        owner: str | None = None,
    ) -> Registration:
        binding = ToolBinding(
            definition,
            handler,
            side_effect,
            required_permissions,
        )
        return self.registry.register(
            Contribution(
                capability=TOOL_CAPABILITY,
                provider=binding,
                name=definition.name,
                version=version,
                scope=scope or ScopePath.application(),
                owner=owner,
                metadata={
                    "side_effect": side_effect.value,
                    "required_permissions": tuple(sorted(required_permissions)),
                },
            )
        )

    def register_binding(
        self,
        binding: ToolBinding,
        *,
        version: str = "0",
        scope: ScopePath | None = None,
        owner: str | None = None,
    ) -> Registration:
        """Register a binding produced by a public adapter such as python_tool."""

        return self.register(
            binding.definition,
            binding.handler,
            side_effect=binding.side_effect,
            required_permissions=binding.required_permissions,
            version=version,
            scope=scope,
            owner=owner,
        )

    def binding(
        self,
        name: str,
        *,
        scope: ScopePath | None = None,
        version: str | None = None,
    ) -> ToolBinding:
        return self.registry.resolve(
            TOOL_CAPABILITY,
            scope or ScopePath.application(),
            name=name,
            version=version,
        )

    def bindings(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[ToolBinding, ...]:
        resolved_scope = scope or ScopePath.application()
        contributions = self.registry.list(TOOL_CAPABILITY, resolved_scope)
        names = sorted({contribution.name for contribution in contributions})
        return tuple(self.binding(name, scope=resolved_scope) for name in names)

    def definitions(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[ToolDefinition, ...]:
        return tuple(binding.definition for binding in self.bindings(scope=scope))
