"""Prompt-free cross-service observation, separate from admission budgets."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from decimal import Context, localcontext
from typing import Protocol

from w_agent.models import ModelCost, TokenUsage
from w_agent.shared_budget import SharedBudgetEntry, SharedBudgetError


class ServiceUsageError(SharedBudgetError):
    """Non-retryable observation failure; paid work must not be repeated."""


def _label(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise ValueError("service usage requires bounded opaque labels")


def _count(value: int) -> None:
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("invalid service usage counter")


@dataclass(frozen=True, slots=True)
class ServiceUsageUnit:
    name: str
    count: int

    def __post_init__(self) -> None:
        _label(self.name)
        _count(self.count)


@dataclass(frozen=True, slots=True)
class ServiceUsageRecord:
    """One attempt or cumulative model Run, never both for the same operation.

    Labels must be host-selected opaque identifiers, not query text, credentials
    or endpoints. Unknown quantities are absent; known subtotals may be partial.
    """

    operation_id: str
    record_id: str
    service: str
    source_ref: str
    meter_version: str
    status: str = "started"
    granularity: str = "attempt"
    token_scope: str = "expected"
    calls: int = 1
    usage: TokenUsage | None = None
    usage_complete: bool = False
    cost: ModelCost | None = None
    cost_complete: bool = False
    units: tuple[ServiceUsageUnit, ...] = ()
    units_complete: bool = False
    reconciliation_ref: str | None = None

    def __post_init__(self) -> None:
        for value in (self.operation_id, self.record_id, self.source_ref, self.meter_version):
            _label(value)
        if self.service not in {"model", "embedding", "retrieval", "rerank"}:
            raise ValueError("invalid service kind")
        if self.status not in {"started", "completed", "unknown", "not-incurred"}:
            raise ValueError("invalid service observation status")
        if self.granularity not in {"attempt", "run"} or (self.granularity == "run" and self.service != "model"):
            raise ValueError("invalid observation granularity")
        if self.token_scope not in {"expected", "not-applicable"}:
            raise ValueError("invalid token applicability")
        _count(self.calls)
        if any(type(value) is not bool for value in (self.usage_complete, self.cost_complete, self.units_complete)):
            raise ValueError("invalid completeness flag")
        if self.usage is not None:
            if not isinstance(self.usage, TokenUsage) or self.token_scope != "expected":
                raise ValueError("invalid service token usage")
            for value in (self.usage.input_tokens, self.usage.output_tokens, self.usage.cached_input_tokens):
                _count(value)
            if self.usage.cached_input_tokens > self.usage.input_tokens:
                raise ValueError("invalid cached token usage")
        if self.cost is not None:
            if not isinstance(self.cost, ModelCost):
                raise ValueError("invalid service cost")
            _label(self.cost.currency)
            _label(self.cost.price_table_version)
            if any(len(value.as_tuple().digits) > 28 or not -28 <= value.as_tuple().exponent <= 28
                   or value.adjusted() > 28
                   for value in (self.cost.input_cost, self.cost.output_cost, self.cost.cached_input_cost)):
                raise ValueError("service cost exceeds size limit")
        if (not isinstance(self.units, tuple) or len(self.units) > 32
                or any(not isinstance(unit, ServiceUsageUnit) for unit in self.units)
                or len({unit.name for unit in self.units}) != len(self.units)):
            raise ValueError("invalid service usage units")
        if self.reconciliation_ref is not None:
            _label(self.reconciliation_ref)
        if self.status in {"started", "unknown", "not-incurred"}:
            if (self.usage is not None or self.cost is not None or self.units
                    or self.usage_complete or self.cost_complete or self.units_complete):
                raise ValueError("non-completed observations cannot claim actual quantities")
        elif ((self.usage_complete and self.token_scope == "expected" and self.usage is None)
              or (self.cost_complete and self.cost is None)):
            raise ValueError("complete dimensions require actual quantities")

    def to_dict(self) -> dict:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["usage"] = None if self.usage is None else {
            "input_tokens": self.usage.input_tokens, "output_tokens": self.usage.output_tokens,
            "cached_input_tokens": self.usage.cached_input_tokens,
        }
        result["cost"] = None if self.cost is None else {
            "currency": self.cost.currency, "price_table_version": self.cost.price_table_version,
            "input_cost": str(self.cost.input_cost), "output_cost": str(self.cost.output_cost),
            "cached_input_cost": str(self.cost.cached_input_cost),
        }
        result["units"] = [{"name": item.name, "count": item.count} for item in self.units]
        return result


def _encode(record: ServiceUsageRecord) -> str:
    return json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(payload: str) -> ServiceUsageRecord:
    value = json.loads(payload)
    if not isinstance(value, dict) or set(value) != set(ServiceUsageRecord.__dataclass_fields__):
        raise ValueError("invalid service record fields")
    data = dict(value)
    if data["usage"] is not None:
        data["usage"] = TokenUsage(**data["usage"])
    if data["cost"] is not None:
        data["cost"] = ModelCost(**data["cost"])
    data["units"] = tuple(ServiceUsageUnit(**item) for item in data["units"])
    record = ServiceUsageRecord(**data)
    if _encode(record) != payload:
        raise ValueError("noncanonical service record")
    return record


def _transition(previous: ServiceUsageRecord | None, current: ServiceUsageRecord) -> None:
    if previous is None or previous == current:
        return
    identity = ("operation_id", "record_id", "service", "source_ref", "meter_version", "granularity", "token_scope", "calls")
    if any(getattr(previous, key) != getattr(current, key) for key in identity):
        raise ServiceUsageError("service-usage-identity-conflict")
    if previous.status == "started":
        return
    if previous.status == "unknown" and current.status in {"completed", "not-incurred"} and current.reconciliation_ref:
        return
    raise ServiceUsageError("service-usage-terminal-conflict")


def _compatible(records: tuple[ServiceUsageRecord, ...], current: ServiceUsageRecord) -> None:
    if any(item.service == current.service and item.granularity != current.granularity for item in records):
        raise ServiceUsageError("service-usage-mixed-run-and-attempt-accounting")


class ServiceUsageLedger(Protocol):
    """Idempotent observations; this protocol does not authorize calls or budgets."""

    async def record(self, record: ServiceUsageRecord) -> None: ...

    async def records(self, operation_id: str) -> tuple[ServiceUsageRecord, ...]: ...


class InMemoryServiceUsageLedger:
    def __init__(self, *, max_records: int = 10000) -> None:
        if type(max_records) is not int or not 1 <= max_records <= 100000:
            raise ValueError("invalid service ledger capacity")
        self.max_records = max_records
        self._records: dict[tuple[str, str], ServiceUsageRecord] = {}
        self._granularities: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def record(self, record: ServiceUsageRecord) -> None:
        if not isinstance(record, ServiceUsageRecord):
            raise ServiceUsageError("service-usage-record-invalid")
        async with self._lock:
            key = (record.operation_id, record.record_id)
            group = (record.operation_id, record.service)
            if group in self._granularities and self._granularities[group] != record.granularity:
                raise ServiceUsageError("service-usage-mixed-run-and-attempt-accounting")
            _transition(self._records.get(key), record)
            if key not in self._records and len(self._records) >= self.max_records:
                raise ServiceUsageError("service-usage-capacity-exceeded")
            self._records[key] = record
            self._granularities[group] = record.granularity

    async def records(self, operation_id: str) -> tuple[ServiceUsageRecord, ...]:
        _label(operation_id)
        async with self._lock:
            return tuple(item for item in self._records.values() if item.operation_id == operation_id)


def aggregate_service_usage(records: tuple[ServiceUsageRecord, ...]) -> dict:
    """Known subtotals only; completeness covers supplied records, not unseen calls."""
    if (not isinstance(records, tuple) or len(records) > 100000
            or any(not isinstance(item, ServiceUsageRecord) for item in records)
            or len({item.operation_id for item in records}) > 1
            or len({item.record_id for item in records}) != len(records)):
        raise ServiceUsageError("service-usage-aggregation-invalid")
    counts = [0, 0, 0]
    granularities: dict[str, str] = {}
    for item in records:
        if item.service in granularities and granularities[item.service] != item.granularity:
            raise ServiceUsageError("service-usage-mixed-run-and-attempt-accounting")
        granularities[item.service] = item.granularity
    costs: dict[tuple[str, str], ModelCost] = {}
    units: dict[tuple[str, str, str, str], int] = {}
    incomplete_tokens, incomplete_cost, incomplete_units, unresolved = [], [], [], []
    for item in records:
        if item.status == "not-incurred":
            continue
        if item.status in {"started", "unknown"}:
            unresolved.append(item.record_id)
        if item.token_scope == "expected" and not item.usage_complete:
            incomplete_tokens.append(item.record_id)
        if not item.cost_complete:
            incomplete_cost.append(item.record_id)
        if not item.units_complete:
            incomplete_units.append(item.record_id)
        if item.usage is not None:
            for i, value in enumerate((item.usage.input_tokens, item.usage.output_tokens, item.usage.cached_input_tokens)):
                counts[i] += value
        if item.cost is not None:
            key = (item.cost.currency, item.cost.price_table_version)
            with localcontext(Context(prec=80, Emin=-999, Emax=999)):
                costs[key] = costs[key].add(item.cost) if key in costs else item.cost
        for unit in item.units:
            key = (item.service, item.source_ref, item.meter_version, unit.name)
            units[key] = units.get(key, 0) + unit.count
    with localcontext(Context(prec=80, Emin=-999, Emax=999)):
        cost_totals = [{"currency": key[0], "price_table_version": key[1], "total": str(costs[key].total)} for key in sorted(costs)]
    return {
        "operation_id": records[0].operation_id if records else None,
        "records": len(records), "observed_calls": sum(item.calls for item in records if item.status != "not-incurred"),
        "known_usage": {"input_tokens": counts[0], "output_tokens": counts[1], "cached_input_tokens": counts[2], "total_tokens": counts[0] + counts[1]},
        "cost_totals": cost_totals,
        "unit_totals": [{"service": key[0], "source_ref": key[1], "meter_version": key[2], "unit": key[3], "count": value} for key, value in sorted(units.items())],
        "incomplete_token_records": incomplete_tokens, "incomplete_cost_records": incomplete_cost,
        "incomplete_unit_records": incomplete_units, "unresolved_records": unresolved,
        "usage_complete": bool(records) and not incomplete_tokens and not unresolved,
        "cost_complete": bool(records) and not incomplete_cost and not unresolved,
        "units_complete": bool(records) and not incomplete_units and not unresolved,
        "coverage": "supplied-records-only",
    }


def service_usage_from_budget_entry(
    entry: SharedBudgetEntry, *, operation_id: str, source_ref: str, meter_version: str, service: str,
) -> ServiceUsageRecord:
    """Project an existing reservation without reserving or billing again."""
    if not isinstance(entry, SharedBudgetEntry):
        raise ValueError("typed budget entry required")
    actual = entry.actual
    return ServiceUsageRecord(
        operation_id, entry.reservation.reservation_id, service, source_ref, meter_version,
        status={"pending": "started", "unknown": "unknown", "settled": "completed", "released": "not-incurred"}[entry.status],
        usage=actual.usage if actual else None, usage_complete=actual is not None,
        cost=actual.cost if actual else None, cost_complete=actual is not None and actual.cost is not None,
        units_complete=actual is not None,
        reconciliation_ref=entry.reconciliation.reconciliation_id if entry.reconciliation else None,
    )


def service_usage_from_run(result, *, operation_id: str, source_ref: str, meter_version: str,
                           confirm_final: bool = False) -> ServiceUsageRecord:
    """Import one explicitly final cumulative Run, never an approval checkpoint."""
    from w_agent.agents import RunResult, StopReason
    if not isinstance(result, RunResult) or confirm_final is not True or result.stop_reason == StopReason.NEEDS_APPROVAL:
        raise ValueError("explicitly final non-checkpoint Run result required")
    for value in (result.model_calls, result.reported_usage_calls, result.priced_usage_calls):
        _count(value)
    if (not isinstance(result.stop_reason, StopReason)
            or not result.priced_usage_calls <= result.reported_usage_calls <= result.model_calls):
        raise ValueError("invalid cumulative Run accounting")
    return ServiceUsageRecord(
        operation_id, result.run_id, "model", source_ref, meter_version, status="completed", granularity="run",
        calls=result.model_calls, usage=result.usage,
        usage_complete=result.reported_usage_calls == result.model_calls,
        cost=result.cost, cost_complete=result.cost is not None and result.priced_usage_calls == result.model_calls,
        units_complete=True,
    )
