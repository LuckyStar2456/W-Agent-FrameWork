"""Explicit durable shared admission for trusted local SQLite files.

No model bodies, implicit migrations, expiration, automatic reconciliation or
execution leases. Cancellation may stop waiting after a worker has committed.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from w_agent.models import ModelCost, TokenUsage
from w_agent.shared_budget import (
    SharedBudgetAmount, SharedBudgetEntry, SharedBudgetError, SharedBudgetLimits,
    SharedBudgetReconciliation, SharedBudgetReservation, SharedBudgetSnapshot, _SharedBudgetState,
)

_APPLICATION_ID = 0x57415342
_SCHEMA_VERSION = 1
_RECONCILED_ENTRY_VERSION = 2
_MAX_ENTRY_BYTES = 16384
_MAX_LEDGER_BYTES = 32 * 1024 * 1024


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate budget field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite budget field")


def _load_json(payload: str) -> Any:
    return json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _amount_data(amount: SharedBudgetAmount | None) -> dict[str, Any] | None:
    if amount is None:
        return None
    cost = amount.cost
    return {
        "input_tokens": amount.usage.input_tokens,
        "output_tokens": amount.usage.output_tokens,
        "cached_input_tokens": amount.usage.cached_input_tokens,
        "cost": None if cost is None else {
            "currency": cost.currency, "price_table_version": cost.price_table_version,
            "input_cost": str(cost.input_cost), "output_cost": str(cost.output_cost),
            "cached_input_cost": str(cost.cached_input_cost),
        },
    }


def _amount(data: Any) -> SharedBudgetAmount | None:
    if data is None:
        return None
    if not isinstance(data, dict) or set(data) != {
        "input_tokens", "output_tokens", "cached_input_tokens", "cost",
    }:
        raise ValueError("invalid budget amount")
    cost = data["cost"]
    if cost is not None:
        if not isinstance(cost, dict) or set(cost) != {
            "currency", "price_table_version", "input_cost", "output_cost", "cached_input_cost",
        } or any(not isinstance(value, str) for value in cost.values()):
            raise ValueError("invalid budget cost")
        cost = ModelCost(**cost)
    return SharedBudgetAmount(
        TokenUsage(data["input_tokens"], data["output_tokens"], data["cached_input_tokens"]), cost,
    )


def _entry_data(entry: SharedBudgetEntry) -> dict[str, Any]:
    data = {
        "schema_version": _SCHEMA_VERSION,
        "reservation_id": entry.reservation.reservation_id,
        "reserved": _amount_data(entry.reservation.amount),
        "status": entry.status, "actual": _amount_data(entry.actual),
    }
    if entry.reconciliation is not None:
        decision = entry.reconciliation
        data["schema_version"] = _RECONCILED_ENTRY_VERSION
        data["reconciliation"] = {
            "reconciliation_id": decision.reconciliation_id,
            "expected_status": decision.expected_status, "outcome": decision.outcome,
            "evidence_ref": decision.evidence_ref, "actor_ref": decision.actor_ref,
        }
    return data


def _decode(payload: str) -> SharedBudgetEntry:
    data = _load_json(payload)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        raise ValueError("unsupported budget entry")
    version = data["schema_version"]
    fields = {"schema_version", "reservation_id", "reserved", "status", "actual"}
    if version == _RECONCILED_ENTRY_VERSION:
        fields.add("reconciliation")
    elif version != _SCHEMA_VERSION:
        raise ValueError("unsupported budget entry")
    if set(data) != fields:
        raise ValueError("invalid budget entry fields")
    reservation = SharedBudgetReservation(data["reservation_id"], _amount(data["reserved"]))
    actual = _amount(data["actual"])
    decision = None
    if version == _RECONCILED_ENTRY_VERSION:
        receipt = data["reconciliation"]
        if not isinstance(receipt, dict) or set(receipt) != {
            "reconciliation_id", "expected_status", "outcome", "evidence_ref", "actor_ref",
        }:
            raise ValueError("invalid reconciliation receipt")
        decision = SharedBudgetReconciliation(reservation=reservation, actual=actual, **receipt)
    entry = SharedBudgetEntry(
        reservation, data["status"], actual, decision,
    )
    if (entry.status not in ("pending", "settled", "unknown", "released")
            or (entry.status == "settled") != (entry.actual is not None)
            or _json(_entry_data(entry)) != _json(data)):
        raise ValueError("inconsistent budget entry")
    return entry


@dataclass(frozen=True, slots=True, init=False)
class SQLiteSharedBudget:
    """SharedBudgetController with serialized, persistent local admission.

    Explicit initialize() is required; construction performs no I/O. Reopening
    requires identical limits/capacity for the same budget_id. Each operation
    uses a short-lived worker-thread connection, not a model execution lock.
    Use on a trusted local filesystem with working SQLite file locks.
    """

    database_path: Path
    budget_id: str
    limits: SharedBudgetLimits
    max_reservations: int
    timeout: float

    def __init__(
        self, database_path: str | Path, budget_id: str, limits: SharedBudgetLimits, *,
        max_reservations: int = 10000, timeout: float = 1.0,
    ) -> None:
        _SharedBudgetState(limits, max_reservations=max_reservations)
        if not isinstance(budget_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", budget_id):
            raise ValueError("invalid shared budget identity")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or not 0 < timeout <= 60):
            raise ValueError("shared budget timeout must be between 0 and 60 seconds")
        if str(database_path) == ":memory:":
            raise ValueError("durable budget requires a file path")
        object.__setattr__(self, "database_path", Path(database_path).absolute())
        object.__setattr__(self, "budget_id", budget_id)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "max_reservations", max_reservations)
        object.__setattr__(self, "timeout", float(timeout))
        if len(self._config().encode("utf-8")) > _MAX_ENTRY_BYTES:
            raise ValueError("shared budget configuration exceeds storage limit")

    def _config(self) -> str:
        limits = self.limits
        return _json({
            "schema_version": _SCHEMA_VERSION, "max_reservations": self.max_reservations,
            "max_input_tokens": limits.max_input_tokens, "max_output_tokens": limits.max_output_tokens,
            "max_total_tokens": limits.max_total_tokens,
            "max_cost": None if limits.max_cost is None else str(limits.max_cost),
            "currency": limits.currency, "price_table_version": limits.price_table_version,
            "max_entry_bytes": _MAX_ENTRY_BYTES, "max_ledger_bytes": _MAX_LEDGER_BYTES,
        })

    def _connect(self, mode: str) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                               timeout=self.timeout, isolation_level=None)

    def _check_schema(self, db: sqlite3.Connection) -> None:
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION):
            raise SharedBudgetError("unsupported-shared-budget-database")

    def _check_budget(self, db: sqlite3.Connection) -> None:
        self._check_schema(db)
        row = db.execute(
            "SELECT substr(config, 1, ?), length(CAST(config AS BLOB)) "
            "FROM shared_budgets WHERE budget_id = ?", (_MAX_ENTRY_BYTES + 1, self.budget_id),
        ).fetchone()
        if (row is None or not isinstance(row[0], str) or type(row[1]) is not int
                or row[1] > _MAX_ENTRY_BYTES or _json(_load_json(row[0])) != self._config()):
            raise SharedBudgetError("shared-budget-configuration-mismatch")

    async def initialize(self) -> None:
        """Bind limits in a dedicated file; never create parent directories."""
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                objects = db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if objects is None:
                    if (db.execute("PRAGMA application_id").fetchone()[0] != 0
                            or db.execute("PRAGMA user_version").fetchone()[0] != 0):
                        raise SharedBudgetError("unsupported-shared-budget-database")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    db.execute("CREATE TABLE shared_budgets (budget_id TEXT PRIMARY KEY NOT NULL, config TEXT NOT NULL)")
                    db.execute("CREATE TABLE shared_tickets (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                               "budget_id TEXT NOT NULL, reservation_id TEXT NOT NULL, payload TEXT NOT NULL, "
                               "UNIQUE(budget_id, reservation_id))")
                self._check_schema(db)
                db.execute("INSERT OR IGNORE INTO shared_budgets VALUES (?, ?)", (self.budget_id, self._config()))
                self._check_budget(db)
                self._load_state(db)
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("shared-budget-initialization-failed") from None

    def _load_state(self, db: sqlite3.Connection) -> tuple[_SharedBudgetState, dict[str, int]]:
        """Recompute totals and breach flags, rather than trusting stored totals."""
        state = _SharedBudgetState(self.limits, max_reservations=self.max_reservations)
        sizes: dict[str, int] = {}
        total_bytes = 0
        rows = db.execute(
            "SELECT substr(reservation_id, 1, 129), substr(payload, 1, ?), length(CAST(payload AS BLOB)) "
            "FROM shared_tickets WHERE budget_id = ? ORDER BY sequence LIMIT ?",
            (_MAX_ENTRY_BYTES + 1, self.budget_id, self.max_reservations + 1),
        )
        try:
            for reservation_id, payload, size in rows:
                if (len(sizes) >= self.max_reservations or not isinstance(payload, str)
                        or type(size) is not int or size > _MAX_ENTRY_BYTES):
                    raise ValueError("invalid persisted ticket size")
                total_bytes += size
                if total_bytes > _MAX_LEDGER_BYTES:
                    raise ValueError("persisted ledger exceeds capacity")
                entry = _decode(payload)
                if entry.reservation.reservation_id != reservation_id or reservation_id in sizes:
                    raise ValueError("persisted ticket identity mismatch")
                state._validate(entry.reservation.amount)
                state._entries[reservation_id] = SharedBudgetEntry(entry.reservation, "pending")
                if entry.reconciliation is not None:
                    if entry.reconciliation.expected_status == "unknown":
                        state._settle(entry.reservation, None)
                    state._reconcile(entry.reconciliation, confirm_inactive=True)
                elif entry.status in ("unknown", "settled"):
                    state._settle(entry.reservation, entry.actual)
                elif entry.status == "released":
                    state._release(entry.reservation)
                sizes[reservation_id] = size
            zero_cost = None if self.limits.max_cost is None else ModelCost(
                self.limits.currency, self.limits.price_table_version, 0,
            )
            if not state._breached and state._exceeds(state._snapshot(), SharedBudgetAmount(TokenUsage(), zero_cost)):
                raise ValueError("persisted ledger exceeds configured limits")
            return state, sizes
        except Exception:
            raise SharedBudgetError("shared-budget-corrupt-ledger") from None

    def _operate(
        self, operation: str, reservation: SharedBudgetReservation | None = None,
        amount: SharedBudgetAmount | None = None,
        *, decision: SharedBudgetReconciliation | None = None, confirm_inactive: bool = False,
    ) -> SharedBudgetReservation | SharedBudgetSnapshot | SharedBudgetEntry | None:
        try:
            with closing(self._connect("ro" if operation == "snapshot" else "rw")) as db, db:
                db.execute("BEGIN" if operation == "snapshot" else "BEGIN IMMEDIATE")
                self._check_budget(db)
                state, sizes = self._load_state(db)
                if operation == "snapshot":
                    return state._snapshot()
                if operation == "reserve":
                    reservation = state._reserve(amount)
                elif operation == "settle":
                    state._settle(reservation, amount)
                elif operation == "release":
                    state._release(reservation)
                elif operation == "reconcile":
                    reconciled = state._reconcile(decision, confirm_inactive=confirm_inactive)
                    reservation = reconciled.reservation
                else:
                    raise ValueError("invalid budget operation")
                entry = state._entry(reservation)
                payload = _json(_entry_data(entry))
                size = len(payload.encode("utf-8"))
                if size > _MAX_ENTRY_BYTES or sum(sizes.values()) - sizes.get(reservation.reservation_id, 0) + size > _MAX_LEDGER_BYTES:
                    raise SharedBudgetError("shared-budget-storage-capacity")
                _decode(payload)
                if operation == "reserve":
                    db.execute("INSERT INTO shared_tickets (budget_id, reservation_id, payload) VALUES (?, ?, ?)",
                               (self.budget_id, reservation.reservation_id, payload))
                else:
                    db.execute("UPDATE shared_tickets SET payload = ? WHERE budget_id = ? AND reservation_id = ?",
                               (payload, self.budget_id, reservation.reservation_id))
                if operation == "reconcile":
                    return entry
                return reservation if operation == "reserve" else None
        except SharedBudgetError:
            raise
        except Exception:
            raise SharedBudgetError("shared-budget-storage-failed") from None

    async def reserve(self, amount: SharedBudgetAmount) -> SharedBudgetReservation:
        return cast(SharedBudgetReservation, await asyncio.to_thread(self._operate, "reserve", amount=amount))

    async def settle(self, reservation: SharedBudgetReservation, actual: SharedBudgetAmount | None) -> None:
        await asyncio.to_thread(self._operate, "settle", reservation, actual)

    async def release(self, reservation: SharedBudgetReservation) -> None:
        """Host assertion that a call never started, not a cancellation refund."""
        await asyncio.to_thread(self._operate, "release", reservation)

    async def snapshot(self) -> SharedBudgetSnapshot:
        return cast(SharedBudgetSnapshot, await asyncio.to_thread(self._operate, "snapshot"))

    async def reconcile(
        self, decision: SharedBudgetReconciliation, *, confirm_inactive: bool = False,
    ) -> SharedBudgetEntry:
        """Atomically store one final decision with the updated ticket.

        Evidence references are not fetched or authenticated. The host must stop
        all execution/writers for the ticket; database locks cannot ensure that.
        """
        if confirm_inactive is not True:
            raise SharedBudgetError("shared-reconciliation-confirmation-required")
        if not isinstance(decision, SharedBudgetReconciliation):
            raise SharedBudgetError("invalid-shared-reconciliation")
        return cast(SharedBudgetEntry, await asyncio.to_thread(
            self._operate, "reconcile", decision=decision, confirm_inactive=True,
        ))
