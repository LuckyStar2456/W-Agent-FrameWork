"""Read-only service usage command, real local files and no external services."""

import asyncio
import json

from typer.testing import CliRunner

from w_agent.cli import app
from w_agent.models import TokenUsage
from w_agent.service_usage import ServiceUsageRecord
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger


def test_missing_consent_and_missing_database_do_not_create_files(tmp_path):
    database = tmp_path / "missing.sqlite"
    args = ["service-usage", "--database", str(database), "--operation", "demo"]
    for extra in ([], ["--confirm-read"]):
        result = CliRunner().invoke(app, [*args, *extra])
        assert result.exit_code == 2
        assert "unavailable usage is not zero" in result.output
        assert not database.exists()


def test_known_subtotals_unknown_cost_and_empty_operation_are_distinct(tmp_path):
    database = tmp_path / "usage.sqlite"

    async def seed():
        ledger = SQLiteServiceUsageLedger(database, max_records=10)
        await ledger.initialize(confirm_create=True)
        await ledger.record(ServiceUsageRecord(
            "demo", "one", "model", "offline", "v1", status="completed",
            usage=TokenUsage(3, 2), usage_complete=True, units_complete=True,
        ))

    asyncio.run(seed())
    before = database.read_bytes()
    args = ["service-usage", "--database", str(database), "--confirm-read", "--max-records", "10"]
    result = CliRunner().invoke(app, [*args, "--operation", "demo"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["known_usage"]["total_tokens"] == 5 and payload["usage_complete"]
    assert not payload["cost_complete"] and payload["cost_totals"] == []
    empty = CliRunner().invoke(app, [*args, "--operation", "not-recorded"])
    assert empty.exit_code == 0
    payload = json.loads(empty.output)
    assert payload["requested_operation_id"] == "not-recorded"
    assert payload["records"] == 0 and not payload["usage_complete"] and not payload["cost_complete"]
    assert database.read_bytes() == before
