"""Explicit admission budgets shared by model Provider wrappers.

Reservations depend on host-supplied upper bounds, not inferred billing truth.
The memory backend is process-local; storage backends reuse private transitions.
No tenant routing, background work or automatic reconciliation.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from w_agent.models import ModelCost, ModelError, ModelFailure, ModelFailureKind, TokenUsage


class SharedBudgetError(ModelError):
    """Non-retryable, prompt-free shared admission/accounting failure."""

    def __init__(self, code: str) -> None:
        super().__init__(ModelFailure(ModelFailureKind.CONFIGURATION, code,
                                     "shared model budget rejected the operation; inspect its ledger"))


@dataclass(frozen=True, slots=True)
class SharedBudgetAmount:
    usage: TokenUsage
    cost: ModelCost | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.usage, TokenUsage) or any(
            type(value) is not int or value < 0 for value in (
                self.usage.input_tokens, self.usage.output_tokens, self.usage.cached_input_tokens,
            )
        ) or self.usage.cached_input_tokens > self.usage.input_tokens:
            raise ValueError("shared budget needs valid token counters")
        if self.cost is not None and not isinstance(self.cost, ModelCost):
            raise ValueError("shared budget needs a typed cost")


@dataclass(frozen=True, slots=True)
class SharedBudgetLimits:
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost: Decimal | str | int | None = None
    currency: str | None = None
    price_table_version: str | None = None

    def __post_init__(self) -> None:
        for value in (self.max_input_tokens, self.max_output_tokens, self.max_total_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("shared token limits must be non-negative integers")
        if self.max_cost is None:
            if self.currency is not None or self.price_table_version is not None:
                raise ValueError("shared price identity requires a cost limit")
        else:
            if (not isinstance(self.currency, str) or not isinstance(self.price_table_version, str)
                    or isinstance(self.max_cost, bool)):
                raise ValueError("shared cost limit requires a price identity")
            cost = ModelCost(self.currency, self.price_table_version, self.max_cost)
            object.__setattr__(self, "currency", cost.currency)
            object.__setattr__(self, "price_table_version", cost.price_table_version)
            object.__setattr__(self, "max_cost", cost.total)
        if all(value is None for value in (
            self.max_input_tokens, self.max_output_tokens, self.max_total_tokens, self.max_cost,
        )):
            raise ValueError("shared budget needs at least one limit")


@dataclass(frozen=True, slots=True)
class SharedBudgetReservation:
    reservation_id: str
    amount: SharedBudgetAmount

    def __post_init__(self) -> None:
        if (not isinstance(self.reservation_id, str) or not self.reservation_id
                or len(self.reservation_id) > 128 or not isinstance(self.amount, SharedBudgetAmount)):
            raise ValueError("invalid shared reservation")


@dataclass(frozen=True, slots=True)
class SharedBudgetReconciliation:
    """One host decision backed by independently retained billing evidence.

    References are opaque labels, not evidence bodies or authentication. A
    decision is final: known settlements and prior decisions cannot be revised.
    not-incurred asserts no accounted tokens AND no costs, not merely free usage.
    """

    reconciliation_id: str
    reservation: SharedBudgetReservation
    expected_status: str
    outcome: str  # settled / not-incurred
    evidence_ref: str
    actor_ref: str
    actual: SharedBudgetAmount | None = None

    def __post_init__(self) -> None:
        for value in (self.reconciliation_id, self.evidence_ref, self.actor_ref):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
                raise ValueError("reconciliation requires bounded opaque references")
        if not isinstance(self.reservation, SharedBudgetReservation):
            raise ValueError("reconciliation requires a typed reservation")
        if self.expected_status not in ("pending", "unknown"):
            raise ValueError("only unresolved reservations can be reconciled")
        if self.outcome == "settled":
            if not isinstance(self.actual, SharedBudgetAmount):
                raise ValueError("settled reconciliation requires known actual usage")
        elif self.outcome != "not-incurred" or self.actual is not None:
            raise ValueError("not-incurred reconciliation must not include actual usage")


@dataclass(frozen=True, slots=True)
class SharedBudgetEntry:
    reservation: SharedBudgetReservation
    status: str  # pending / settled / unknown / released
    actual: SharedBudgetAmount | None = None
    reconciliation: SharedBudgetReconciliation | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.reservation, SharedBudgetReservation)
                or self.status not in ("pending", "settled", "unknown", "released")
                or (self.status == "settled" and not isinstance(self.actual, SharedBudgetAmount))
                or (self.status != "settled" and self.actual is not None)):
            raise ValueError("invalid shared budget entry")
        decision = self.reconciliation
        if decision is not None:
            if (not isinstance(decision, SharedBudgetReconciliation)
                    or decision.reservation != self.reservation or decision.actual != self.actual
                    or self.status != ("settled" if decision.outcome == "settled" else "released")):
                raise ValueError("reconciliation does not match its entry")


@dataclass(frozen=True, slots=True)
class SharedBudgetSnapshot:
    entries: tuple[SharedBudgetEntry, ...]
    known_usage: TokenUsage
    held_usage: TokenUsage
    known_cost: Decimal | None
    held_cost: Decimal | None
    limits: SharedBudgetLimits
    breached: bool

    @property
    def blocked(self) -> bool:
        return self.breached or any(entry.status == "unknown" for entry in self.entries)


class SharedBudgetController(Protocol):
    """A host-controlled ledger; implementations own atomic admission/settlement."""

    async def reserve(self, amount: SharedBudgetAmount) -> SharedBudgetReservation: ...

    async def settle(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount | None) -> None: ...

    async def release(self, reservation: SharedBudgetReservation) -> None: ...


class SharedBudgetReconciler(Protocol):
    """Optional host-only capability, deliberately separate from model admission.

    confirm_inactive is a host assertion, not an execution lease. Stop/drain all
    writers of the target ticket and inspect independent evidence before use.
    """

    async def reconcile(
        self, decision: SharedBudgetReconciliation, *, confirm_inactive: bool = False,
    ) -> SharedBudgetEntry: ...


class _SharedBudgetState:
    """Synchronous transitions; callers own locking, persistence and isolation."""

    def __init__(self, limits: SharedBudgetLimits, *, max_reservations: int = 10000) -> None:
        if not isinstance(limits, SharedBudgetLimits):
            raise ValueError("shared budget requires typed limits")
        if type(max_reservations) is not int or not 1 <= max_reservations <= 100000:
            raise ValueError("invalid shared reservation capacity")
        self._limits = limits
        self._max_reservations = max_reservations
        self._entries: dict[str, SharedBudgetEntry] = {}
        self._reconciliation_ids: dict[str, str] = {}
        self._breached = False

    def _validate(self, amount: SharedBudgetAmount) -> None:
        if not isinstance(amount, SharedBudgetAmount):
            raise SharedBudgetError("invalid-shared-amount")
        limits = self._limits
        if limits.max_cost is not None:
            if (amount.cost is None or amount.cost.currency != limits.currency
                    or amount.cost.price_table_version != limits.price_table_version):
                raise SharedBudgetError("shared-price-mismatch")
        elif amount.cost is not None:
            raise SharedBudgetError("unexpected-shared-cost")

    def _snapshot(self) -> SharedBudgetSnapshot:
        known = [0, 0, 0]
        held = [0, 0, 0]
        known_cost = held_cost = Decimal(0)
        for entry in self._entries.values():
            amount = entry.actual if entry.status == "settled" else entry.reservation.amount
            if entry.status == "released":
                continue
            tokens = known if entry.status == "settled" else held
            for index, value in enumerate((amount.usage.input_tokens, amount.usage.output_tokens,
                                           amount.usage.cached_input_tokens)):
                tokens[index] += value
            if amount.cost is not None:
                if entry.status == "settled":
                    known_cost += amount.cost.total
                else:
                    held_cost += amount.cost.total
        priced = self._limits.max_cost is not None
        return SharedBudgetSnapshot(tuple(self._entries.values()), TokenUsage(*known), TokenUsage(*held),
                                    known_cost if priced else None, held_cost if priced else None,
                                    self._limits, self._breached)

    def _exceeds(self, view: SharedBudgetSnapshot, additional: SharedBudgetAmount) -> bool:
        usage = additional.usage
        counts = (
            (view.known_usage.input_tokens + view.held_usage.input_tokens + usage.input_tokens,
             self._limits.max_input_tokens),
            (view.known_usage.output_tokens + view.held_usage.output_tokens + usage.output_tokens,
             self._limits.max_output_tokens),
            (view.known_usage.total_tokens + view.held_usage.total_tokens + usage.total_tokens,
             self._limits.max_total_tokens),
        )
        return any(limit is not None and total > limit for total, limit in counts) or (
            self._limits.max_cost is not None
            and view.known_cost + view.held_cost + additional.cost.total > self._limits.max_cost
        )

    def _reserve(self, amount: SharedBudgetAmount) -> SharedBudgetReservation:
        self._validate(amount)
        view = self._snapshot()
        if view.blocked:
            raise SharedBudgetError("shared-budget-needs-reconciliation")
        if len(self._entries) >= self._max_reservations:
            raise SharedBudgetError("shared-reservation-capacity")
        if self._exceeds(view, amount):
            raise SharedBudgetError("shared-budget-exhausted")
        reservation = SharedBudgetReservation(uuid4().hex, amount)
        self._entries[reservation.reservation_id] = SharedBudgetEntry(reservation, "pending")
        return reservation

    def _entry(self, reservation: SharedBudgetReservation) -> SharedBudgetEntry:
        if not isinstance(reservation, SharedBudgetReservation):
            raise SharedBudgetError("invalid-shared-reservation")
        entry = self._entries.get(reservation.reservation_id)
        if entry is None or entry.reservation != reservation:
            raise SharedBudgetError("unknown-shared-reservation")
        return entry

    def _settle(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount | None) -> None:
        if actual is not None:
            self._validate(actual)
        entry = self._entry(reservation)
        target = SharedBudgetEntry(reservation, "unknown" if actual is None else "settled", actual)
        if entry == target:
            return
        if entry.status != "pending":
            raise SharedBudgetError("shared-settlement-conflict")
        self._entries[reservation.reservation_id] = target
        if actual is not None:
            self._mark_breach(reservation, actual)

    def _mark_breach(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount) -> None:
        reserved = reservation.amount
        if (actual.usage.input_tokens > reserved.usage.input_tokens
                or actual.usage.output_tokens > reserved.usage.output_tokens
                or (actual.cost is not None and actual.cost.total > reserved.cost.total)):
            self._breached = True

    def _release(self, reservation: SharedBudgetReservation) -> None:
        entry = self._entry(reservation)
        if entry.status == "released":
            return
        if entry.status != "pending":
            raise SharedBudgetError("shared-release-conflict")
        self._entries[reservation.reservation_id] = SharedBudgetEntry(reservation, "released")

    def _reconcile(
        self, decision: SharedBudgetReconciliation, *, confirm_inactive: bool = False,
    ) -> SharedBudgetEntry:
        if confirm_inactive is not True:
            raise SharedBudgetError("shared-reconciliation-confirmation-required")
        if not isinstance(decision, SharedBudgetReconciliation):
            raise SharedBudgetError("invalid-shared-reconciliation")
        entry = self._entry(decision.reservation)
        if entry.reconciliation == decision:
            return entry
        if (entry.reconciliation is not None or entry.status != decision.expected_status
                or decision.reconciliation_id in self._reconciliation_ids):
            raise SharedBudgetError("shared-reconciliation-conflict")
        if decision.actual is not None:
            self._validate(decision.actual)
        target = SharedBudgetEntry(
            decision.reservation, "settled" if decision.outcome == "settled" else "released",
            decision.actual, decision,
        )
        # No mutation before all decision/identity/price checks have succeeded.
        if decision.actual is not None:
            self._mark_breach(decision.reservation, decision.actual)
        self._entries[decision.reservation.reservation_id] = target
        self._reconciliation_ids[decision.reconciliation_id] = decision.reservation.reservation_id
        return target


class InMemorySharedBudget(_SharedBudgetState):
    """Single-event-loop ledger with atomic capacity checks and terminal tombstones.

    Unknown usage blocks new calls until explicit host reconciliation. Exceeded
    estimates are recorded, never discarded; all later admissions are blocked.
    """

    def __init__(self, limits: SharedBudgetLimits, *, max_reservations: int = 10000) -> None:
        super().__init__(limits, max_reservations=max_reservations)
        self._lock = asyncio.Lock()

    async def reserve(self, amount: SharedBudgetAmount) -> SharedBudgetReservation:
        async with self._lock:
            return self._reserve(amount)

    async def settle(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount | None) -> None:
        async with self._lock:
            self._settle(reservation, actual)

    async def release(self, reservation: SharedBudgetReservation) -> None:
        """Only the host may assert a call never started; not a cancellation refund."""
        async with self._lock:
            self._release(reservation)

    async def snapshot(self) -> SharedBudgetSnapshot:
        async with self._lock:
            return self._snapshot()

    async def reconcile(
        self, decision: SharedBudgetReconciliation, *, confirm_inactive: bool = False,
    ) -> SharedBudgetEntry:
        """Apply one final host decision; never infer inactivity or billing truth."""
        async with self._lock:
            return self._reconcile(decision, confirm_inactive=confirm_inactive)
