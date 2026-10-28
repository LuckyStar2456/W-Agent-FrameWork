"""Opt-in local SQLite persistence for prompt-free summary accounting.

Trusted local files only. This is neither an execution lease nor a shared budget.
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
from typing import Any

from w_agent.agents import RunResult, StopReason
from w_agent.models import ModelCost, TokenUsage
from w_agent.session_model_summary import SessionSummaryRunReport
from w_agent.session_usage import (
    SessionPreparationUsage, SessionUsageError, aggregate_session_preparation_usage,
)

_APPLICATION_ID = 0x57415355
_SCHEMA_VERSION = 1


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate accounting field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite accounting value")


def _decode(payload: str) -> SessionSummaryRunReport:
    """Validate persisted types, derived totals and fields, never trust flags."""
    envelope = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "report"}
            or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1):
        raise ValueError("unsupported accounting report")
    data = envelope["report"]
    if not isinstance(data, dict):
        raise ValueError("invalid accounting report")
    usage = data["usage"]
    if usage is not None:
        if not isinstance(usage, dict) or set(usage) != {
            "input_tokens", "output_tokens", "cached_input_tokens", "total_tokens",
        }:
            raise ValueError("invalid persisted usage")
        usage = TokenUsage(usage["input_tokens"], usage["output_tokens"], usage["cached_input_tokens"])
    cost = data["cost"]
    if cost is not None:
        if not isinstance(cost, dict) or set(cost) != {
            "currency", "price_table_version", "input_cost", "output_cost", "cached_input_cost", "total",
        } or any(not isinstance(value, str) for value in cost.values()):
            raise ValueError("invalid persisted cost")
        cost = ModelCost(cost["currency"], cost["price_table_version"], cost["input_cost"],
                         cost["output_cost"], cost["cached_input_cost"])
    report = SessionSummaryRunReport(
        data["run_id"], data["status"],
        StopReason(data["stop_reason"]) if data["stop_reason"] is not None else None,
        usage, data["model_calls"], data["reported_usage_calls"], cost, data["priced_usage_calls"],
    )
    # Comparing JSON, not Python dict equality, also rejects true in place of 1.
    if _json(report.to_dict()) != _json(data):
        raise ValueError("noncanonical or inconsistent accounting report")
    return report


@dataclass(frozen=True, slots=True, init=False)
class SQLiteSessionSummaryObserver:
    """Durable SessionSummaryObserver, scoped by an explicit local operation ID.

    Construction performs no database I/O. Call initialize() explicitly before
    record/reports/snapshot. Connections live only within worker-thread calls;
    concurrent writers serialize via SQLite transactions, including capacity
    checks. Persisted limits must match when reopening an operation.

    Cancellation stops waiting, not an already-started SQLite transaction. Reopen
    and inspect reports to reconcile; never infer that a model may be rerun.
    """

    database_path: Path
    operation_id: str
    max_runs: int
    max_report_bytes: int
    timeout: float

    def __init__(
        self, database_path: str | Path, operation_id: str, *, max_runs: int = 1024,
        max_report_bytes: int = 16384, timeout: float = 1.0,
    ) -> None:
        if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", operation_id):
            raise ValueError("invalid accounting operation identity")
        if type(max_runs) is not int or not 1 <= max_runs <= 10000:
            raise ValueError("accounting capacity must be between 1 and 10000")
        if type(max_report_bytes) is not int or not 512 <= max_report_bytes <= 65536:
            raise ValueError("accounting report limit must be between 512 and 65536 bytes")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("accounting lock timeout must be finite and between 0 and 60 seconds")
        if str(database_path) == ":memory:":
            raise ValueError("durable accounting requires a file path")
        object.__setattr__(self, "database_path", Path(database_path).absolute())
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "max_runs", max_runs)
        object.__setattr__(self, "max_report_bytes", max_report_bytes)
        object.__setattr__(self, "timeout", float(timeout))

    def _connect(self, mode: str) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                               timeout=self.timeout, isolation_level=None)

    def _check_schema(self, db: sqlite3.Connection) -> None:
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != _SCHEMA_VERSION):
            raise SessionUsageError("unsupported accounting database; no migration performed")

    def _check_operation(self, db: sqlite3.Connection) -> None:
        self._check_schema(db)
        limits = db.execute(
            "SELECT max_runs, max_report_bytes FROM summary_operations WHERE operation_id = ?",
            (self.operation_id,),
        ).fetchone()
        if limits != (self.max_runs, self.max_report_bytes):
            raise SessionUsageError("accounting operation absent or limits differ; initialize explicitly")

    async def initialize(self) -> None:
        """Create/open a dedicated database in an existing directory and bind limits."""
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                objects = db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone()
                if objects is None:
                    if (db.execute("PRAGMA application_id").fetchone()[0] != 0
                            or db.execute("PRAGMA user_version").fetchone()[0] != 0):
                        raise SessionUsageError("unsupported empty accounting database")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    db.execute("CREATE TABLE summary_operations (operation_id TEXT PRIMARY KEY NOT NULL, "
                               "max_runs INTEGER NOT NULL, max_report_bytes INTEGER NOT NULL)")
                    db.execute("CREATE TABLE summary_reports (sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                               "operation_id TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL, "
                               "UNIQUE(operation_id, run_id))")
                self._check_schema(db)
                db.execute("INSERT OR IGNORE INTO summary_operations VALUES (?, ?, ?)",
                           (self.operation_id, self.max_runs, self.max_report_bytes))
                self._check_operation(db)
        except (OSError, sqlite3.Error):
            raise SessionUsageError("accounting initialization failed; inspect the local store") from None

    def _row_report(self, row: tuple[Any, ...]) -> SessionSummaryRunReport:
        run_id, payload, size = row
        if not isinstance(payload, str) or type(size) is not int or size > self.max_report_bytes:
            raise ValueError("invalid persisted accounting size")
        report = _decode(payload)
        if report.run_id != run_id:
            raise ValueError("persisted accounting identity mismatch")
        return report

    async def record(self, report: SessionSummaryRunReport) -> None:
        try:
            if not isinstance(report, SessionSummaryRunReport):
                raise ValueError("typed report required")
            payload = _json({"schema_version": 1, "report": report.to_dict()})
            if len(payload.encode("utf-8")) > self.max_report_bytes:
                raise ValueError("report exceeds persistence limit")
            _decode(payload)
        except Exception:
            raise SessionUsageError("accounting report rejected before storage") from None
        await asyncio.to_thread(self._record, report, payload)

    def _record(self, report: SessionSummaryRunReport, payload: str) -> None:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check_operation(db)
                row = db.execute(
                    "SELECT substr(run_id, 1, 129), substr(payload, 1, ?), length(CAST(payload AS BLOB)) "
                    "FROM summary_reports WHERE operation_id = ? AND run_id = ?",
                    (self.max_report_bytes + 1, self.operation_id, report.run_id),
                ).fetchone()
                if row is not None:
                    previous = self._row_report(row)
                    if previous == report:
                        return
                    if previous.status != "started":
                        raise SessionUsageError("summary accounting conflict; terminal report retained")
                    db.execute("UPDATE summary_reports SET payload = ? WHERE operation_id = ? AND run_id = ?",
                               (payload, self.operation_id, report.run_id))
                else:
                    count = db.execute("SELECT COUNT(*) FROM summary_reports WHERE operation_id = ?",
                                       (self.operation_id,)).fetchone()[0]
                    if count >= self.max_runs:
                        raise SessionUsageError("summary accounting capacity reached; report not recorded")
                    db.execute("INSERT INTO summary_reports (operation_id, run_id, payload) VALUES (?, ?, ?)",
                               (self.operation_id, report.run_id, payload))
        except SessionUsageError:
            raise
        except Exception:
            raise SessionUsageError("accounting write failed; inspect reports before retrying") from None

    async def reports(self) -> tuple[SessionSummaryRunReport, ...]:
        """Read a bounded, consistent snapshot without creating a missing file."""
        return await asyncio.to_thread(self._reports)

    def _reports(self) -> tuple[SessionSummaryRunReport, ...]:
        try:
            with closing(self._connect("ro")) as db, db:
                db.execute("BEGIN")
                self._check_operation(db)
                rows = db.execute(
                    "SELECT substr(run_id, 1, 129), substr(payload, 1, ?), length(CAST(payload AS BLOB)) "
                    "FROM summary_reports WHERE operation_id = ? ORDER BY sequence LIMIT ?",
                    (self.max_report_bytes + 1, self.operation_id, self.max_runs + 1),
                )
                reports = []
                for row in rows:
                    if len(reports) >= self.max_runs:
                        raise ValueError("persisted operation exceeds capacity")
                    reports.append(self._row_report(row))
                if len({report.run_id for report in reports}) != len(reports):
                    raise ValueError("duplicate persisted accounting identity")
                return tuple(reports)
        except SessionUsageError:
            raise
        except Exception:
            raise SessionUsageError("accounting read failed; no totals returned") from None

    async def snapshot(self, main_result: RunResult | None = None) -> SessionPreparationUsage:
        """Combine durable summary reports with one explicit, non-persisted main result."""
        return aggregate_session_preparation_usage(await self.reports(), main_result)
