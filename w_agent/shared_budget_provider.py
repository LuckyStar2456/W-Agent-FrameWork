"""Provider decorator admitting every model attempt against a shared ledger."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from w_agent.models import (
    CancellationToken, FinishEvent, ModelDescriptor, ModelProvider, ModelRequest,
    ModelStreamValidator, StreamEvent, TokenUsage,
)
from w_agent.shared_budget import SharedBudgetAmount, SharedBudgetController, SharedBudgetError


class SharedBudgetMeter(Protocol):
    """Trusted host estimator and authoritative-usage pricer for one Provider.

    Bound must cover the routed input and full request output cap, including
    provider-specific hidden/reasoning tokens and all billable units. No default
    approximation is advertised as an upper bound. Callbacks must not invoke a
    paid model recursively. Cost identity must match the shared controller.
    """

    async def bound(self, request: ModelRequest) -> SharedBudgetAmount: ...

    async def actual(self, request: ModelRequest, usage: TokenUsage) -> SharedBudgetAmount: ...


@dataclass(frozen=True, slots=True)
class SharedBudgetModelProvider:
    """Wrap all participating routes with the same controller, including summaries.

    Listing/resolution are delegated without budget reservations. No inner client
    close or native-cursor delegation: hosts own lifecycle; cursor recovery needs
    a separately metered adapter. Pending reservations remain held if cleanup is
    interrupted. All admission/settlement failures are non-retryable.
    """

    provider: ModelProvider
    controller: SharedBudgetController
    meter: SharedBudgetMeter

    @property
    def catalog_probe_scope(self) -> str:
        return getattr(self.provider, "catalog_probe_scope", "unknown")

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return await self.provider.list_models()

    async def resolve(self, model: str) -> ModelDescriptor:
        return await self.provider.resolve(model)

    async def stream(self, request: ModelRequest, *, cancellation: CancellationToken | None = None) -> AsyncIterator[StreamEvent]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if type(request.max_output_tokens) is not int or request.max_output_tokens <= 0:
            raise SharedBudgetError("shared-output-cap-required")
        try:
            amount = await self.meter.bound(request)
            if not isinstance(amount, SharedBudgetAmount) or amount.usage.output_tokens < request.max_output_tokens:
                raise ValueError("missing reservation or output bound")
        except Exception:
            raise SharedBudgetError("shared-estimate-unavailable") from None
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        try:
            reservation = await self.controller.reserve(amount)
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("shared-reservation-failed") from None
        started = settled = False
        source = None
        try:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            started = True  # Even stream construction may perform external work.
            source = self.provider.stream(request, cancellation=cancellation)
            validator = ModelStreamValidator()
            finish = None
            async for event in source:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                validator.feed(event)
                if isinstance(event, FinishEvent):
                    finish = event  # Publish success only after EOF and accounting.
                else:
                    yield event
            response = validator.finish()
            closer = getattr(source, "aclose", None)
            if closer is not None:
                await closer()
            source = None
            if not response.usage_reported:
                raise SharedBudgetError("shared-usage-unavailable")
            try:
                actual = await self.meter.actual(request, response.usage)
                if not isinstance(actual, SharedBudgetAmount) or actual.usage != response.usage:
                    raise ValueError("meter must preserve reported usage")
                await self.controller.settle(reservation, actual)
                settled = True
            except Exception:
                raise SharedBudgetError("shared-settlement-failed") from None
            if (actual.usage.input_tokens > amount.usage.input_tokens
                    or actual.usage.output_tokens > amount.usage.output_tokens
                    or (actual.cost is not None and amount.cost is not None
                        and actual.cost.total > amount.cost.total)):
                raise SharedBudgetError("shared-bound-exceeded")
            yield finish
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("shared-call-uncertain") from None
        finally:
            try:
                try:
                    if not settled:
                        if started:
                            await self.controller.settle(reservation, None)
                        else:
                            await self.controller.release(reservation)
                except Exception:
                    raise SharedBudgetError("shared-cleanup-failed") from None
            finally:
                if source is not None:
                    closer = getattr(source, "aclose", None)
                    if closer is not None:
                        try:
                            await closer()
                        except Exception:
                            raise SharedBudgetError("shared-provider-close-failed") from None
