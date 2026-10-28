"""Explicit, prompt-free aggregation of summary Runs and one main Run result.

Accounting only: no model calls, budget reservations, implicit persistence,
currency conversions or modifications to RunResult/SessionManager statistics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from w_agent.agents import RunResult, StopReason
from w_agent.models import ModelCost, TokenUsage
from w_agent.session_model_summary import SessionSummaryRunReport


class SessionUsageError(ValueError):
    """Content-free rejection of invalid, conflicting or oversized accounting."""


@dataclass(frozen=True, slots=True)
class SessionPreparationUsage:
    """Known consumption at a snapshot, not final billing or execution completion.

    Totals are partial when completeness is false. Cost groups never mix
    currencies or price-table versions. Main results are supplied explicitly.
    """

    summary_run_ids: tuple[str, ...]
    main_run_id: str | None
    main_stop_reason: StopReason | None
    known_usage: TokenUsage
    known_model_calls: int
    known_reported_usage_calls: int
    known_priced_usage_calls: int
    cost_totals: tuple[ModelCost, ...]
    pending_summary_run_ids: tuple[str, ...]
    incomplete_usage_run_ids: tuple[str, ...]
    incomplete_cost_run_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("summary_run_ids", "pending_summary_run_ids", "incomplete_usage_run_ids", "incomplete_cost_run_ids"):
            values = tuple(getattr(self, name))
            if (any(not isinstance(value, str) or not value or len(value) > 128 for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError("invalid preparation Run identities")
            object.__setattr__(self, name, values)
        if self.main_run_id is None:
            if self.main_stop_reason is not None:
                raise ValueError("missing main Run cannot have a stop reason")
        elif (not isinstance(self.main_run_id, str) or not self.main_run_id or len(self.main_run_id) > 128
              or self.main_run_id in self.summary_run_ids or not isinstance(self.main_stop_reason, StopReason)):
            raise ValueError("invalid main Run identity or stop reason")
        known = set(self.summary_run_ids) | ({self.main_run_id} if self.main_run_id is not None else set())
        if (not set(self.incomplete_usage_run_ids) <= known or not set(self.incomplete_cost_run_ids) <= known
                or not set(self.pending_summary_run_ids) <= set(self.summary_run_ids)
                or not set(self.pending_summary_run_ids) <= set(self.incomplete_usage_run_ids)
                or not set(self.pending_summary_run_ids) <= set(self.incomplete_cost_run_ids)):
            raise ValueError("preparation completeness references invalid Runs")
        if not isinstance(self.known_usage, TokenUsage):
            raise ValueError("invalid preparation usage")
        values = (self.known_usage.input_tokens, self.known_usage.output_tokens, self.known_usage.cached_input_tokens,
                  self.known_model_calls, self.known_reported_usage_calls, self.known_priced_usage_calls)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("invalid preparation usage counters")
        if not self.known_priced_usage_calls <= self.known_reported_usage_calls <= self.known_model_calls:
            raise ValueError("inconsistent preparation usage counters")
        costs = tuple(self.cost_totals)
        if any(not isinstance(cost, ModelCost) for cost in costs):
            raise ValueError("invalid preparation costs")
        if len({(cost.currency, cost.price_table_version) for cost in costs}) != len(costs):
            raise ValueError("duplicate preparation cost groups")
        if self.known_priced_usage_calls and not costs:
            raise ValueError("priced preparation calls require cost groups")
        object.__setattr__(self, "cost_totals", costs)

    @property
    def usage_complete(self) -> bool:
        return self.main_run_id is not None and not self.incomplete_usage_run_ids

    @property
    def cost_complete(self) -> bool:
        return self.main_run_id is not None and not self.incomplete_cost_run_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary_run_ids": list(self.summary_run_ids), "main_run_id": self.main_run_id,
            "main_stop_reason": self.main_stop_reason.value if self.main_stop_reason is not None else None,
            "main_result_supplied": self.main_run_id is not None,
            "known_usage": {"input_tokens": self.known_usage.input_tokens,
                "output_tokens": self.known_usage.output_tokens,
                "cached_input_tokens": self.known_usage.cached_input_tokens,
                "total_tokens": self.known_usage.total_tokens},
            "known_model_calls": self.known_model_calls,
            "known_reported_usage_calls": self.known_reported_usage_calls,
            "known_priced_usage_calls": self.known_priced_usage_calls,
            "usage_complete": self.usage_complete, "cost_complete": self.cost_complete,
            "cost_totals": [{"currency": cost.currency, "price_table_version": cost.price_table_version,
                "input_cost": str(cost.input_cost), "output_cost": str(cost.output_cost),
                "cached_input_cost": str(cost.cached_input_cost), "total": str(cost.total)} for cost in self.cost_totals],
            "pending_summary_run_ids": list(self.pending_summary_run_ids),
            "incomplete_usage_run_ids": list(self.incomplete_usage_run_ids),
            "incomplete_cost_run_ids": list(self.incomplete_cost_run_ids),
        }


def aggregate_session_preparation_usage(
    reports: tuple[SessionSummaryRunReport, ...], main_result: RunResult | None = None,
) -> SessionPreparationUsage:
    """Combine unique latest summary reports with one cumulative main result.

    Supply only reports belonging to this operation. No association, authenticity
    or completeness of the supplied report set can be inferred by this function.
    """
    try:
        if not isinstance(reports, tuple) or any(not isinstance(item, SessionSummaryRunReport) for item in reports):
            raise ValueError("invalid summary reports")
        ids = tuple(item.run_id for item in reports)
        if len(set(ids)) != len(ids):
            raise ValueError("summary Run IDs must be unique")
        combined = reports
        if main_result is not None:
            if not isinstance(main_result, RunResult) or main_result.run_id in ids:
                raise ValueError("invalid or duplicate main Run identity")
            # Reuse strict numeric validation, without retaining the main Run's
            # messages, events, output or attempt bodies in the resulting view.
            main = SessionSummaryRunReport(
                main_result.run_id,
                "completed" if main_result.stop_reason == StopReason.COMPLETED else "rejected",
                main_result.stop_reason, main_result.usage, main_result.model_calls,
                main_result.reported_usage_calls, main_result.cost, main_result.priced_usage_calls,
            )
            combined += (main,)
        input_tokens = output_tokens = cached_tokens = 0
        model_calls = reported_calls = priced_calls = 0
        costs: dict[tuple[str, str], ModelCost] = {}
        for item in combined:
            if item.usage is not None:
                input_tokens += item.usage.input_tokens
                output_tokens += item.usage.output_tokens
                cached_tokens += item.usage.cached_input_tokens
                model_calls += item.model_calls
                reported_calls += item.reported_usage_calls
                priced_calls += item.priced_usage_calls
            if item.cost is not None:
                key = (item.cost.currency, item.cost.price_table_version)
                costs[key] = costs[key].add(item.cost) if key in costs else item.cost
        return SessionPreparationUsage(
            ids, main_result.run_id if main_result is not None else None,
            main_result.stop_reason if main_result is not None else None,
            TokenUsage(input_tokens, output_tokens, cached_tokens), model_calls, reported_calls, priced_calls,
            tuple(costs[key] for key in sorted(costs)),
            tuple(item.run_id for item in reports if item.status == "started"),
            tuple(item.run_id for item in combined if not item.usage_complete),
            tuple(item.run_id for item in combined if not item.cost_complete),
        )
    except Exception:
        raise SessionUsageError("invalid preparation accounting; no totals returned") from None


class InMemorySessionSummaryObserver:
    """Bounded, replaceable accounting sink for one host-defined operation.

    Updates started -> terminal exactly once; identical deliveries are idempotent.
    Conflicting terminal reports fail, never silently replace reported charges.
    The host creates one instance per association, or deliberately scopes reuse.
    """

    def __init__(self, *, max_runs: int = 1024) -> None:
        if type(max_runs) is not int or max_runs <= 0:
            raise ValueError("summary accounting capacity must be a positive integer")
        self.max_runs = max_runs
        self._reports: dict[str, SessionSummaryRunReport] = {}
        self._lock = asyncio.Lock()

    async def record(self, report: SessionSummaryRunReport) -> None:
        if not isinstance(report, SessionSummaryRunReport):
            raise SessionUsageError("summary accounting requires a typed report")
        async with self._lock:
            prior = self._reports.get(report.run_id)
            if prior == report:
                return
            if prior is not None and prior.status != "started":
                raise SessionUsageError("summary accounting conflict; terminal report retained")
            if prior is None and len(self._reports) >= self.max_runs:
                raise SessionUsageError("summary accounting capacity reached; report not recorded")
            self._reports[report.run_id] = report

    async def reports(self) -> tuple[SessionSummaryRunReport, ...]:
        """Return an immutable snapshot in first-observed Run order."""
        async with self._lock:
            return tuple(self._reports.values())

    async def snapshot(self, main_result: RunResult | None = None) -> SessionPreparationUsage:
        """Main result is not stored: resumed cumulative results replace, not add."""
        return aggregate_session_preparation_usage(await self.reports(), main_result)
