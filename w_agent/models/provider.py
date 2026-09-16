"""Model provider protocol and registry integration."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol

from w_agent.kernel import Contribution, Registration, Registry, ScopePath

from .types import ModelDescriptor, ModelRequest, StreamEvent


MODEL_PROVIDER_CAPABILITY = "model.provider"


class CancellationToken:
    """Cooperative cancellation signal passed across provider boundaries."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise asyncio.CancelledError


class ModelProvider(Protocol):
    """Provider adapter interface implemented by first- and third-party plugins."""

    async def list_models(self) -> tuple[ModelDescriptor, ...]: ...

    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]: ...


class ModelRegistry:
    """Register and resolve model providers through the kernel Registry."""

    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def register(
        self,
        name: str,
        provider: ModelProvider,
        *,
        version: str = "0",
        scope: ScopePath | None = None,
        owner: str | None = None,
    ) -> Registration:
        """Register one named provider route."""

        return self.registry.register(
            Contribution(
                capability=MODEL_PROVIDER_CAPABILITY,
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
    ) -> ModelProvider:
        """Resolve one provider route."""

        return self.registry.resolve(
            MODEL_PROVIDER_CAPABILITY,
            scope or ScopePath.application(),
            name=name,
            version=version,
        )

    def providers(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[tuple[str, ModelProvider], ...]:
        """Return the highest visible version of every provider name."""

        resolved_scope = scope or ScopePath.application()
        contributions = self.registry.list(MODEL_PROVIDER_CAPABILITY, resolved_scope)
        names = sorted({contribution.name for contribution in contributions})
        return tuple(
            (name, self.provider(name, scope=resolved_scope)) for name in names
        )

    async def list_models(
        self,
        *,
        scope: ScopePath | None = None,
    ) -> tuple[ModelDescriptor, ...]:
        """List models from all visible providers concurrently."""

        providers = self.providers(scope=scope)
        if not providers:
            return ()
        catalogs = await asyncio.gather(
            *(provider.list_models() for _, provider in providers)
        )
        return tuple(model for catalog in catalogs for model in catalog)
