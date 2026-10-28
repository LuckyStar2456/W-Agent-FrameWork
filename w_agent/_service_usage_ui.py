"""Explicit host lifecycle and safe operation-level usage visibility for UIs."""

from __future__ import annotations

import importlib
import inspect
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import MappingProxyType

from w_agent.service_usage import aggregate_service_usage
from w_agent.service_usage_runtime import LocalServiceUsageBinding, LocalServiceUsageConfig


class ServiceUsageEntryError(ValueError):
    """Fixed lifecycle/preflight failure; never infer permission to replay calls."""


@dataclass(frozen=True, slots=True)
class ServiceUsageOptions:
    entry: str | None = field(default=None, repr=False)
    confirm_code: bool = False
    confirm_record: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.confirm_code, self.confirm_record)):
            raise ServiceUsageEntryError("service usage confirmations must be booleans")
        if self.entry is None:
            if self.confirm_code or self.confirm_record:
                raise ServiceUsageEntryError("service usage confirmation requires an explicit entry")
            return
        if (not isinstance(self.entry, str) or len(self.entry) > 512
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", self.entry, flags=re.ASCII)):
            raise ServiceUsageEntryError("service usage entry must be an explicit module:factory")
        if not self.confirm_code or not self.confirm_record:
            raise ServiceUsageEntryError("service usage requires independent LOAD USAGE and RECORD USAGE consent")


@asynccontextmanager
async def service_usage_binding_scope(
    entry: str | None, *, selected: str | None, confirmed: bool = False, confirm_record: bool = False,
) -> AsyncIterator[Mapping[str, LocalServiceUsageBinding]]:
    """Borrow host-owned objects; no imports or writes before complete preflight."""
    options = ServiceUsageOptions(entry, confirmed, confirm_record)
    if options.entry is None:
        if selected is not None:
            raise ServiceUsageEntryError("selected service usage binding requires an authorized host entry")
        yield MappingProxyType({})
        return
    try:
        LocalServiceUsageConfig(selected)
    except (TypeError, ValueError):
        raise ServiceUsageEntryError("service usage host requires service_usage.binding selection") from None
    try:
        module, name = options.entry.split(":")
        context = getattr(importlib.import_module(module), name)()
        if inspect.iscoroutine(context):
            context.close()
            raise ValueError("context manager required")
        if any(not callable(getattr(context, method, None)) for method in ("__aenter__", "__aexit__")):
            raise ValueError("context manager required")
        catalog = await context.__aenter__()
    except Exception:
        raise ServiceUsageEntryError("service usage host setup failed; inspect state before retry") from None
    try:
        try:
            if not isinstance(catalog, Mapping) or not 1 <= len(catalog) <= 64:
                raise ValueError("bounded catalog required")
            bindings = dict(catalog)
            for key, binding in bindings.items():
                LocalServiceUsageConfig(key)
                if not isinstance(binding, LocalServiceUsageBinding):
                    raise ValueError("typed binding required")
            if selected not in bindings:
                raise ValueError("selected binding unavailable")
        except Exception:
            raise ServiceUsageEntryError("service usage host catalog invalid or selection missing") from None
        yield MappingProxyType(bindings)
    except BaseException as error:
        try:
            await context.__aexit__(type(error), error, error.__traceback__)
        except Exception:
            error.add_note("Service usage host cleanup also failed; inspect state, do not replay.")
        raise
    else:
        try:
            await context.__aexit__(None, None, None)
        except Exception:
            raise ServiceUsageEntryError("service usage host cleanup failed; operation may have completed; do not replay") from None


async def service_usage_summary(binding: LocalServiceUsageBinding | None) -> dict | None:
    """No records, source labels, evidence refs or prompts in the safe UI view."""
    if binding is None:
        return None
    scope = {"scope": "host-operation-not-this-run", "operation_id": binding.operation_id,
             "run_links_enabled": binding.links is not None,
             "runtime_observers": ["model"] + (["retrieval"] if binding.retrieval_source_ref is not None else []),
             "coverage": "supplied-records-only"}
    try:
        counts = {service: {"calls": 0, "records": 0} for service in ("model", "embedding", "retrieval", "rerank")}
        records = await binding.ledger.records(binding.operation_id)
        if any(record.operation_id != binding.operation_id for record in records):
            raise ValueError("ledger returned a different operation")
        # Reuse the exact same observation snapshot for all totals below.
        report = aggregate_service_usage(records)
        for record in records:
            counts[record.service]["records"] += 1
            if record.status != "not-incurred":
                counts[record.service]["calls"] += record.calls
        return {**scope, "status": "available", "records": report["records"],
                "observed_calls": report["observed_calls"], "services": counts,
                "known_usage": report["known_usage"], "cost_totals": report["cost_totals"],
                "usage_complete": report["usage_complete"], "cost_complete": report["cost_complete"],
                "units_complete": report["units_complete"],
                "incomplete_token_records": len(report["incomplete_token_records"]),
                "incomplete_cost_records": len(report["incomplete_cost_records"]),
                "incomplete_unit_records": len(report["incomplete_unit_records"]),
                "unresolved_records": len(report["unresolved_records"])}
    except Exception:
        return {**scope, "status": "unavailable", "message": "Usage display unavailable; operation outcome unchanged. Inspect ledger; do not replay."}
