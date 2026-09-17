"""Scoped sandbox providers on the shared W-Agent registry."""

from __future__ import annotations

from w_agent.kernel import Contribution, Registration, Registry, ScopePath

from .types import SandboxProvider


SANDBOX_PROVIDER_CAPABILITY = "sandbox.provider"


class SandboxRegistry:
    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def register(
        self,
        name: str,
        provider: SandboxProvider,
        *,
        version: str = "0",
        scope: ScopePath | None = None,
        owner: str | None = None,
    ) -> Registration:
        return self.registry.register(
            Contribution(
                capability=SANDBOX_PROVIDER_CAPABILITY,
                provider=provider,
                name=name,
                version=version,
                scope=scope or ScopePath.application(),
                owner=owner,
            )
        )

    def provider(
        self,
        name: str,
        *,
        scope: ScopePath | None = None,
        version: str | None = None,
    ) -> SandboxProvider:
        return self.registry.resolve(
            SANDBOX_PROVIDER_CAPABILITY,
            scope or ScopePath.application(),
            name=name,
            version=version,
        )

    def providers(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[tuple[str, SandboxProvider], ...]:
        resolved_scope = scope or ScopePath.application()
        contributions = self.registry.list(
            SANDBOX_PROVIDER_CAPABILITY,
            resolved_scope,
        )
        names = sorted({contribution.name for contribution in contributions})
        return tuple(
            (name, self.provider(name, scope=resolved_scope)) for name in names
        )
