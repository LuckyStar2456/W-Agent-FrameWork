"""Read-only durable association selection never turns operation totals into Run totals."""

import asyncio
import json

import pytest
from typer.testing import CliRunner

from w_agent.cli import app
from w_agent.models import TokenUsage
from w_agent.service_usage import ServiceUsageRecord
from w_agent.service_usage_links import ServiceUsageRunLink, SQLiteServiceUsageLinkStore
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger


def seed(tmp_path):
    links_path, usage_path = tmp_path / "links.sqlite", tmp_path / "usage.sqlite"

    async def create():
        links = SQLiteServiceUsageLinkStore(links_path, max_links=10)
        usage = SQLiteServiceUsageLedger(usage_path, max_records=10)
        await links.initialize(confirm_create=True)
        await usage.initialize(confirm_create=True)
        for run, session, operation in (("run-a", "session-a", "shared"),
                                        ("run-b", "session-a", "shared"),
                                        ("run-c", "session-b", "other")):
            await links.bind(ServiceUsageRunLink(session, run, operation), confirm_write=True)
            await usage.record(ServiceUsageRecord(
                operation, run, "model", "offline", "fixture", status="completed",
                usage=TokenUsage(3, 2), usage_complete=True,
            ))

    asyncio.run(create())
    return links_path, usage_path


@pytest.mark.parametrize("selection,expected", [
    (["--run", "run-a"], ["run-a"]),
    (["--session", "session-a"], ["run-a", "run-b"]),
    (["--operation", "shared"], ["run-a", "run-b"]),
    (["--run", "absent"], []),
])
def test_read_links_by_each_exact_identity_without_mutation(tmp_path, selection, expected):
    links, _ = seed(tmp_path)
    before = links.read_bytes()
    result = CliRunner().invoke(app, ["service-usage-link", "--links-database", str(links),
                                     "--confirm-read", "--max-links", "10", *selection])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["association_only"] and payload["run_state"] == "not-inferred"
    assert payload["count"] == len(expected)
    assert [item["run_id"] for item in payload["links"]] == expected
    assert "known_usage" not in payload
    assert links.read_bytes() == before


def test_run_lookup_displays_whole_operation_without_double_counting(tmp_path):
    links, usage = seed(tmp_path)
    before = links.read_bytes(), usage.read_bytes()
    result = CliRunner().invoke(app, ["service-usage", "--database", str(usage),
        "--links-database", str(links), "--run", "run-a", "--confirm-read",
        "--max-links", "10", "--max-records", "10"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["requested_operation_id"] == "shared"
    assert payload["resolved_link"] == {"session_id": "session-a", "run_id": "run-a", "operation_id": "shared"}
    assert payload["scope"] == "host-operation-not-this-run" and payload["association_only"]
    assert payload["known_usage"]["total_tokens"] == 10  # Both linked Runs, once each.
    assert payload["records"] == 2
    assert (links.read_bytes(), usage.read_bytes()) == before


@pytest.mark.parametrize("selection", [[], ["--run", "a", "--operation", "b"],
                                         ["--session", "bad/path"], ["--run", ""]])
def test_link_query_preflight_never_creates_files(tmp_path, selection):
    missing = tmp_path / "missing.sqlite"
    for consent in ([], ["--confirm-read"]):
        result = CliRunner().invoke(app, ["service-usage-link", "--links-database", str(missing), *selection, *consent])
        assert result.exit_code == 2 and not missing.exists()


@pytest.mark.parametrize("extra", [[], ["--operation", "x", "--run", "a"],
                                     ["--run", "a"], ["--operation", "x", "--links-database", "unused.sqlite"]])
def test_usage_selector_preflight_never_reads_or_creates(tmp_path, monkeypatch, extra):
    entered = []

    async def unexpected(*args, **kwargs):
        entered.append(True)
        raise AssertionError("must reject before reading")

    monkeypatch.setattr(SQLiteServiceUsageLedger, "records", unexpected)
    path = tmp_path / "absent.sqlite"
    result = CliRunner().invoke(app, ["service-usage", "--database", str(path), "--confirm-read", *extra])
    assert result.exit_code == 2 and not entered and not path.exists()


def test_missing_link_refuses_usage_lookup_instead_of_zero_or_fallback(tmp_path, monkeypatch):
    links, usage = seed(tmp_path)
    entered = []

    async def unexpected(*args, **kwargs):
        entered.append(True)
        raise AssertionError("unresolved run must not select a ledger operation")

    monkeypatch.setattr(SQLiteServiceUsageLedger, "records", unexpected)
    result = CliRunner().invoke(app, ["service-usage", "--database", str(usage), "--links-database", str(links),
                                     "--run", "missing", "--confirm-read", "--max-links", "10"])
    assert result.exit_code == 2 and not entered
    assert "unavailable usage is not zero" in result.output


def test_example_factory_never_initializes_or_opens_stores(tmp_path, monkeypatch):
    import sqlite3
    from examples.service_usage_host import usage_factory

    def unexpected(*args, **kwargs):
        raise AssertionError("factory assembly must not open SQLite")

    monkeypatch.setattr(sqlite3, "connect", unexpected)
    root = tmp_path / "not-created"
    monkeypatch.setenv("WAGENT_USAGE_ROOT", str(root))
    monkeypatch.setenv("WAGENT_USAGE_OPERATION", "explicit-operation")

    async def assemble():
        async with usage_factory() as bindings:
            binding = bindings["local-usage"]
            assert binding.operation_id == "explicit-operation"
            assert binding.links.database_path == root / "service-usage-links.sqlite3"

    asyncio.run(assemble())
    assert not root.exists()
