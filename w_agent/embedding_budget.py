"""Opt-in embedding reservations sharing the existing model-budget controller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol

from w_agent.embeddings import AsyncEmbeddingProvider, EmbeddingError, EmbeddingResult
from w_agent.knowledge_context import _text
from w_agent.shared_budget import SharedBudgetAmount, SharedBudgetController, SharedBudgetError
from w_agent.vector_retrieval import _integer


class EmbeddingBudgetMeter(Protocol):
    """Trusted estimator/pricer bound to the exact provider, model and parameters.

    Bounds must cover all billable units; character counts are not advertised as
    token upper bounds. Callbacks must not recursively invoke paid models.
    """

    async def bound(self, text: str) -> SharedBudgetAmount: ...

    async def actual(self, text: str, result: EmbeddingResult) -> SharedBudgetAmount: ...


@dataclass(frozen=True, slots=True)
class SharedBudgetTextEmbedder:
    """Settle before returning a vector; unknown outcomes hold reservations.

    Shares memory/SQLite controllers with explicitly wrapped summary/main calls.
    No implicit client close, persistent initialization, pricing or UI wiring.
    """

    provider: AsyncEmbeddingProvider = field(repr=False)
    controller: SharedBudgetController = field(repr=False)
    meter: EmbeddingBudgetMeter = field(repr=False)
    max_input_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        _integer(self.max_input_bytes, 1024 * 1024)
        for value, methods in ((self.provider, ("embed_result",)), (self.controller, ("reserve", "settle", "release")),
                               (self.meter, ("bound", "actual"))):
            if any(not callable(getattr(value, method, None)) for method in methods):
                raise ValueError("embedding budget collaborators are invalid")

    async def embed(self, text: str) -> tuple[float, ...]:
        return (await self.embed_result(text)).vector

    async def embed_result(self, text: str) -> EmbeddingResult:
        try:
            _text(text, self.max_input_bytes)
            bound = await self.meter.bound(text)
            if not isinstance(bound, SharedBudgetAmount) or bound.usage.output_tokens != 0:
                raise ValueError("embedding bound is invalid")
        except Exception:
            raise SharedBudgetError("embedding-estimate-unavailable") from None
        try:
            reservation = await self.controller.reserve(bound)
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("embedding-reservation-failed") from None
        settled = False
        try:
            result = await self.provider.embed_result(text)
            if not isinstance(result, EmbeddingResult) or result.usage is None:
                raise SharedBudgetError("embedding-usage-unavailable")
            try:
                actual = await self.meter.actual(text, result)
                if not isinstance(actual, SharedBudgetAmount) or actual.usage != result.usage:
                    raise ValueError("embedding meter must preserve reported usage")
                await self.controller.settle(reservation, actual)
                settled = True
            except Exception:
                raise SharedBudgetError("embedding-settlement-failed") from None
            if (actual.usage.input_tokens > bound.usage.input_tokens
                    or (actual.cost is not None and bound.cost is not None and actual.cost.total > bound.cost.total)):
                raise SharedBudgetError("embedding-bound-exceeded")
            return result
        except (Exception, asyncio.CancelledError) as error:
            if not settled:
                try:
                    if isinstance(error, EmbeddingError) and not error.may_have_called:
                        await self.controller.release(reservation)
                    else:
                        await self.controller.settle(reservation, None)
                except (Exception, asyncio.CancelledError):
                    pass  # A stranded pending ticket still holds its reservation.
            if isinstance(error, (SharedBudgetError, asyncio.CancelledError)):
                raise
            raise SharedBudgetError("embedding-call-uncertain") from None
