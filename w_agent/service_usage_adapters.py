"""Opt-in observation adapters; existing shared controllers still own budgets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Awaitable, Callable, TypeVar
from uuid import uuid4

from w_agent.models import ModelCost, TokenUsage
from w_agent.service_usage import (
    ServiceUsageError, ServiceUsageLedger, ServiceUsageRecord, ServiceUsageUnit,
    service_usage_from_budget_entry,
)
from w_agent.shared_budget import SharedBudgetAmount, SharedBudgetController, SharedBudgetEntry, SharedBudgetReservation

T = TypeVar("T")


class ObservedSharedBudgetController:
    """Decorate one shared budget for model OR embedding observations.

    Two decorators may share the same underlying controller/ledger. An underlying
    successful settlement is retained before observation; cleanup cannot downgrade
    it to unknown or invoke the controller again. Stores are not atomically joined.
    """

    def __init__(
        self, controller: SharedBudgetController, ledger: ServiceUsageLedger, *,
        operation_id: str, service: str, source_ref: str, meter_version: str,
    ) -> None:
        if service not in {"model", "embedding"}:
            raise ValueError("token budget observation supports model or embedding")
        ServiceUsageRecord(operation_id, "validation", service, source_ref, meter_version)
        self.controller, self.ledger = controller, ledger
        self.operation_id, self.service = operation_id, service
        self.source_ref, self.meter_version = source_ref, meter_version
        self._entries: dict[str, SharedBudgetEntry] = {}
        self._lock = asyncio.Lock()

    async def _report(self, entry: SharedBudgetEntry) -> None:
        try:
            await self.ledger.record(service_usage_from_budget_entry(
                entry, operation_id=self.operation_id, service=self.service,
                source_ref=self.source_ref, meter_version=self.meter_version,
            ))
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-observation-failed-inspect-budget-and-ledger") from None

    async def reserve(self, amount: SharedBudgetAmount) -> SharedBudgetReservation:
        async with self._lock:
            reservation = await self.controller.reserve(amount)
            entry = SharedBudgetEntry(reservation, "pending")
            self._entries[reservation.reservation_id] = entry
            try:
                await self._report(entry)  # No provider can be entered before this returns.
            except (Exception, asyncio.CancelledError):
                try:
                    await self.controller.release(reservation)
                    released = SharedBudgetEntry(reservation, "released")
                    self._entries[reservation.reservation_id] = released
                    await self._report(released)
                except (Exception, asyncio.CancelledError):
                    pass  # Inspect both stores; no paid call has been authorized yet.
                raise
            return reservation

    async def settle(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount | None) -> None:
        async with self._lock:
            entry = self._entry(reservation)
            if entry.status != "pending":
                # Provider-wrapper cleanup sends None after an observation error.
                # Reflush known truth, but NEVER downgrade or settle the budget twice.
                if entry.status == "settled" and (actual is None or actual == entry.actual):
                    await self._report(entry)
                    return
                if entry.status == "unknown" and actual is None:
                    await self._report(entry)
                    return
                raise ServiceUsageError("service-usage-settlement-conflict")
            await self.controller.settle(reservation, actual)
            updated = SharedBudgetEntry(reservation, "unknown" if actual is None else "settled", actual)
            self._entries[reservation.reservation_id] = updated
            await self._report(updated)

    async def release(self, reservation: SharedBudgetReservation) -> None:
        async with self._lock:
            entry = self._entry(reservation)
            if entry.status == "released":
                await self._report(entry)
                return
            if entry.status != "pending":
                raise ServiceUsageError("service-usage-release-conflict")
            await self.controller.release(reservation)
            updated = SharedBudgetEntry(reservation, "released")
            self._entries[reservation.reservation_id] = updated
            await self._report(updated)

    def _entry(self, reservation: SharedBudgetReservation) -> SharedBudgetEntry:
        if not isinstance(reservation, SharedBudgetReservation):
            raise ServiceUsageError("service-usage-reservation-invalid")
        entry = self._entries.get(reservation.reservation_id)
        if entry is None or entry.reservation != reservation:
            raise ServiceUsageError("service-usage-reservation-not-observed")
        return entry


@dataclass(frozen=True, slots=True)
class ServiceUsageMeasurement:
    """Host-reported actuals; None means unknown, never automatically free."""

    usage: TokenUsage | None = None
    usage_complete: bool = False
    cost: ModelCost | None = None
    cost_complete: bool = False
    units: tuple[ServiceUsageUnit, ...] = ()
    units_complete: bool = False


async def observe_service_call(
    call: Callable[[], Awaitable[T]], ledger: ServiceUsageLedger, *,
    operation_id: str, service: str, source_ref: str, meter_version: str,
    measurement: Callable[[T], ServiceUsageMeasurement] | None = None,
    token_scope: str = "expected",
) -> T:
    """Durably start before callback; no automatic retry, reservation or pricing.

    Every invocation gets a fresh identity. Do not wrap both a composite service
    and its same-cost children. Callback/meter code is host-trusted, not sandboxed.
    """
    started = ServiceUsageRecord(operation_id, uuid4().hex, service, source_ref, meter_version, token_scope=token_scope)
    try:
        await ledger.record(started)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ServiceUsageError("service-usage-start-failed-call-not-entered") from None
    try:
        result = await call()
        actual = measurement(result) if measurement is not None else ServiceUsageMeasurement()
        if not isinstance(actual, ServiceUsageMeasurement):
            raise ValueError
        completed = replace(started, status="completed", usage=actual.usage, usage_complete=actual.usage_complete,
                            cost=actual.cost, cost_complete=actual.cost_complete,
                            units=actual.units, units_complete=actual.units_complete)
        await ledger.record(completed)
        return result
    except (Exception, asyncio.CancelledError) as error:
        try:
            await ledger.record(replace(started, status="unknown"))
        except (Exception, asyncio.CancelledError):
            pass  # A persisted started/completed record must remain inspectable.
        if isinstance(error, asyncio.CancelledError):
            raise
        raise ServiceUsageError("service-call-or-observation-failed-no-automatic-retry") from None


@dataclass(frozen=True, slots=True)
class ObservedKnowledgeRetriever:
    retriever: object = field(repr=False)
    ledger: ServiceUsageLedger = field(repr=False)
    operation_id: str
    source_ref: str
    meter_version: str
    measurement: Callable[[tuple], ServiceUsageMeasurement] | None = field(default=None, repr=False)
    token_scope: str = "expected"

    async def retrieve(self, query: str, *, limit: int):
        return await observe_service_call(
            lambda: self.retriever.retrieve(query, limit=limit), self.ledger,
            operation_id=self.operation_id, service="retrieval", source_ref=self.source_ref,
            meter_version=self.meter_version, measurement=self.measurement, token_scope=self.token_scope,
        )


@dataclass(frozen=True, slots=True)
class ObservedKnowledgeReranker:
    reranker: object = field(repr=False)
    ledger: ServiceUsageLedger = field(repr=False)
    operation_id: str
    source_ref: str
    meter_version: str
    measurement: Callable[[tuple], ServiceUsageMeasurement] | None = field(default=None, repr=False)
    token_scope: str = "expected"

    async def rerank(self, query: str, documents: tuple, *, limit: int):
        return await observe_service_call(
            lambda: self.reranker.rerank(query, documents, limit=limit), self.ledger,
            operation_id=self.operation_id, service="rerank", source_ref=self.source_ref,
            meter_version=self.meter_version, measurement=self.measurement, token_scope=self.token_scope,
        )
