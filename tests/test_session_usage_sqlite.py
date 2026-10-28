"""SQLite accounting regressions."""

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from w_agent import (
    AgentSessionHistorySummarizer, MessageRole, ModelMessage, ModelCost, RunResult,
    SessionHistoryTurn, SessionSummaryError, SessionSummaryRunReport, SessionUsageError,
    SQLiteSessionSummaryObserver, StopReason, TokenUsage,
)


def terminal(run_id="summary"):
    return SessionSummaryRunReport(run_id, "completed", StopReason.COMPLETED,
        TokenUsage(10, 2, 3), 1, 1, ModelCost("USD", "v1", "0.01", "0.02"), 1)


def main(usage=TokenUsage(20, 5)):
    return RunResult("main", StopReason.COMPLETED, "PRIVATE_OUTPUT", (), (), 1, 0,
                     usage=usage, model_calls=1, reported_usage_calls=1,
                     cost=ModelCost("USD", "v1", "0.04"), priced_usage_calls=1)


@pytest.mark.asyncio
async def test_summary_adapter_requires_durable_started_report_before_loop(tmp_path):
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation")

    class Loop:
        calls = 0

        async def run(self, definition, context):
            self.calls += 1
            assert (await observer.reports())[0].status == "started"
            return RunResult(context.run_id, StopReason.COMPLETED, "summary", (), (), 1, 0,
                             usage=TokenUsage(10, 2), model_calls=1, reported_usage_calls=1)

    loop = Loop()
    summarizer = AgentSessionHistorySummarizer(loop, observer)
    turns = (SessionHistoryTurn("old", (ModelMessage.text(MessageRole.USER, "PRIVATE_INPUT"),)),)
    with pytest.raises(SessionSummaryError, match="observer failed"):
        await summarizer.summarize(turns)
    assert loop.calls == 0
    await observer.initialize()
    assert await summarizer.summarize(turns) == "summary"
    reports = await observer.reports()
    assert len(reports) == 1 and reports[0].status == "completed"
    assert reports[0].usage_complete and not reports[0].cost_complete
    with closing(sqlite3.connect(observer.database_path)) as db:
        assert "PRIVATE_INPUT" not in db.execute("SELECT payload FROM summary_reports").fetchone()[0]


@pytest.mark.asyncio
async def test_locked_store_fails_without_silent_fallback(tmp_path):
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation", timeout=0.01)
    await observer.initialize()
    with closing(sqlite3.connect(observer.database_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(SessionUsageError, match="write failed"):
            await observer.record(terminal())
        db.rollback()
    assert await observer.reports() == ()


@pytest.mark.asyncio
async def test_explicit_initialization_reopen_and_scoped_totals(tmp_path):
    path = tmp_path / "usage.sqlite3"
    observer = SQLiteSessionSummaryObserver(path, "operation-1")
    assert not path.exists()
    for action in (observer.reports, lambda: observer.record(terminal())):
        with pytest.raises(SessionUsageError):
            await action()
    assert not path.exists()
    await observer.initialize()
    await observer.initialize()
    await observer.record(SessionSummaryRunReport("summary", "started"))
    assert (await observer.snapshot()).pending_summary_run_ids == ("summary",)
    await observer.record(terminal())
    reopened = SQLiteSessionSummaryObserver(path, "operation-1")
    assert await reopened.reports() == (terminal(),)
    snapshot = await reopened.snapshot(main())
    assert snapshot.known_usage == TokenUsage(30, 7, 3)
    assert snapshot.cost_totals[0].total == Decimal("0.07")
    assert snapshot.usage_complete and snapshot.cost_complete
    assert "PRIVATE_OUTPUT" not in json.dumps(snapshot.to_dict())
    assert (await reopened.snapshot(main(TokenUsage(40, 8)))).known_usage.total_tokens == 60
    assert len(await reopened.reports()) == 1
    other = SQLiteSessionSummaryObserver(path, "operation-2")
    await other.initialize()
    assert await other.reports() == ()
    await other.record(terminal())  # Same Run ID in a separate host association.
    assert len(await reopened.reports()) == 1
    with pytest.raises(FrozenInstanceError):
        observer.operation_id = "changed"


@pytest.mark.asyncio
async def test_capacity_conflicts_and_concurrent_instances(tmp_path):
    path = tmp_path / "usage.sqlite3"
    observers = [SQLiteSessionSummaryObserver(path, "operation", max_runs=1, timeout=5) for _ in range(8)]
    await asyncio.gather(*(item.initialize() for item in observers))
    await asyncio.gather(*(item.record(terminal()) for item in observers))
    assert await observers[0].reports() == (terminal(),)
    for conflict in (replace(terminal(), usage=TokenUsage(12, 2)), SessionSummaryRunReport("summary", "started")):
        with pytest.raises(SessionUsageError, match="conflict"):
            await observers[0].record(conflict)
    with pytest.raises(SessionUsageError, match="capacity"):
        await observers[0].record(terminal("other"))
    mismatch = SQLiteSessionSummaryObserver(path, "operation", max_runs=2)
    for action in (mismatch.initialize, mismatch.reports, lambda: mismatch.record(terminal("other"))):
        with pytest.raises(SessionUsageError, match="limits"):
            await action()
    assert await observers[0].reports() == (terminal(),)


@pytest.mark.asyncio
async def test_capacity_check_and_insert_are_one_transaction(tmp_path):
    path = tmp_path / "usage.sqlite3"
    first = SQLiteSessionSummaryObserver(path, "operation", max_runs=1)
    second = SQLiteSessionSummaryObserver(path, "operation", max_runs=1)
    await first.initialize()
    outcomes = await asyncio.gather(first.record(terminal("one")), second.record(terminal("two")),
                                    return_exceptions=True)
    assert sum(value is None for value in outcomes) == 1
    assert sum(isinstance(value, SessionUsageError) for value in outcomes) == 1
    assert len(await first.reports()) == 1


@pytest.mark.asyncio
async def test_finishing_at_capacity_and_unknown_usage_survive_restart(tmp_path):
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation", max_runs=1)
    await observer.initialize()
    await observer.record(SessionSummaryRunReport("summary", "started"))
    await observer.record(SessionSummaryRunReport("summary", "cancelled"))
    reopened = SQLiteSessionSummaryObserver(observer.database_path, "operation", max_runs=1)
    snapshot = await reopened.snapshot(main())
    assert snapshot.incomplete_usage_run_ids == ("summary",)
    assert not snapshot.usage_complete and not snapshot.cost_complete
    with pytest.raises(SessionUsageError, match="conflict"):
        await reopened.record(terminal())


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["version", "total", "bool", "duplicate", "identity", "oversize", "extra"])
async def test_corrupt_records_fail_closed_without_leaking_content(tmp_path, damage):
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation")
    await observer.initialize()
    await observer.record(terminal())
    with closing(sqlite3.connect(observer.database_path)) as db, db:
        payload = db.execute("SELECT payload FROM summary_reports").fetchone()[0]
        data = json.loads(payload)
        if damage == "version":
            data["schema_version"] = 2
        elif damage == "total":
            data["report"]["usage"]["total_tokens"] = 999
        elif damage == "bool":
            data["report"]["model_calls"] = True
        elif damage == "identity":
            data["report"]["run_id"] = "PRIVATE_VALUE"
        elif damage == "extra":
            data["report"]["prompt"] = "PRIVATE_VALUE"
        payload = json.dumps(data)
        if damage == "duplicate":
            payload = payload.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        elif damage == "oversize":
            payload = "PRIVATE_VALUE" * observer.max_report_bytes
        db.execute("UPDATE summary_reports SET payload = ?", (payload,))
    for action in (observer.reports, observer.snapshot, lambda: observer.record(terminal())):
        with pytest.raises(SessionUsageError) as error:
            await action()
        assert "PRIVATE_VALUE" not in str(error.value)


@pytest.mark.asyncio
async def test_foreign_database_and_version_are_not_migrated(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE private_data (value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('retained')")
    observer = SQLiteSessionSummaryObserver(path, "operation")
    with pytest.raises(SessionUsageError, match="unsupported"):
        await observer.initialize()
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT value FROM private_data").fetchall() == [("retained",)]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    own = SQLiteSessionSummaryObserver(tmp_path / "own.sqlite3", "operation")
    await own.initialize()
    with closing(sqlite3.connect(own.database_path)) as db:
        db.execute("PRAGMA user_version = 2")
    with pytest.raises(SessionUsageError, match="unsupported"):
        await own.reports()


@pytest.mark.asyncio
async def test_missing_parent_is_not_created_and_large_reports_are_rejected(tmp_path):
    observer = SQLiteSessionSummaryObserver(tmp_path / "absent" / "usage.sqlite3", "operation")
    with pytest.raises(SessionUsageError):
        await observer.initialize()
    assert not observer.database_path.parent.exists()
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation", max_report_bytes=512)
    oversized = replace(terminal(), cost=ModelCost("USD", "PRIVATE_VALUE" * 200, 1))
    with pytest.raises(SessionUsageError, match="before storage"):
        await observer.record(oversized)
    assert not observer.database_path.exists()


@pytest.mark.asyncio
async def test_cancellation_does_not_claim_started_write_was_rolled_back(tmp_path, monkeypatch):
    observer = SQLiteSessionSummaryObserver(tmp_path / "usage.sqlite3", "operation")
    await observer.initialize()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = SQLiteSessionSummaryObserver._record

    def delayed(self, report, payload):
        entered.set()
        try:
            if not release.wait(5):
                raise AssertionError("test worker was not released")
            original(self, report, payload)
        finally:
            finished.set()

    monkeypatch.setattr(SQLiteSessionSummaryObserver, "_record", delayed)
    task = asyncio.create_task(observer.record(terminal()))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    assert await observer.reports() == (terminal(),)


@pytest.mark.parametrize("kwargs", [{"max_runs": True}, {"max_runs": 0}, {"max_runs": 10001},
    {"max_report_bytes": 1}, {"timeout": True}, {"timeout": float("nan")}, {"timeout": 61}])
def test_invalid_options_fail_before_io(tmp_path, kwargs):
    path = tmp_path / "usage.sqlite3"
    with pytest.raises(ValueError):
        SQLiteSessionSummaryObserver(path, "operation", **kwargs)
    assert not path.exists()
