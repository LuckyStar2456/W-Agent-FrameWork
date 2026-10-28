"""Explicit read-only cross-service usage visibility; never creates stores."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.service_usage import aggregate_service_usage, _label
from w_agent.service_usage_links import ServiceUsageRunLink, SQLiteServiceUsageLinkStore
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger


def register_service_usage_commands(app: typer.Typer) -> None:
    @app.command("service-usage")
    def service_usage(
        database: Path = typer.Option(..., "--database"),
        operation: str | None = typer.Option(None, "--operation"),
        run_id: str | None = typer.Option(None, "--run"),
        links_database: Path | None = typer.Option(None, "--links-database"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        max_records: int = typer.Option(10000, "--max-records"),
        max_links: int = typer.Option(10000, "--max-links"),
    ) -> None:
        """Show observed token/cost/unit subtotals, not uninstrumented calls."""
        try:
            if confirm_read is not True:
                raise ValueError("read consent required")
            if (operation is None) == (run_id is None):
                raise ValueError("select exactly one operation or run")
            if (run_id is None) != (links_database is None):
                raise ValueError("run selection requires a links database")
            _label(operation if operation is not None else run_id)
            ledger = SQLiteServiceUsageLedger(database, max_records=max_records)

            async def read():
                selected = operation
                link = None
                if run_id is not None:
                    links = SQLiteServiceUsageLinkStore(links_database, max_links=max_links)
                    link = await links.get(run_id)
                    if link is None or link.run_id != run_id:
                        raise ValueError("run association unavailable")
                    selected = link.operation_id
                records = await ledger.records(selected)
                if any(record.operation_id != selected for record in records):
                    raise ValueError("ledger operation mismatch")
                report = aggregate_service_usage(records)
                # Even run selection resolves a whole host operation, not a slice.
                report["requested_operation_id"] = selected
                report["scope"] = "host-operation-not-this-run"
                if link is not None:
                    report["resolved_link"] = _link_payload(link)
                    report["association_only"] = True
                    report["run_state"] = "not-inferred"
                return report

            report = asyncio.run(read())
        except Exception:
            typer.echo(
                "Service usage read failed; check consent, operation and ledger configuration. "
                "No store was created and unavailable usage is not zero.", err=True,
            )
            raise typer.Exit(2) from None
        typer.echo(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))

    @app.command("service-usage-link")
    def service_usage_link(
        links_database: Path = typer.Option(..., "--links-database"),
        run_id: str | None = typer.Option(None, "--run"),
        session_id: str | None = typer.Option(None, "--session"),
        operation: str | None = typer.Option(None, "--operation"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        max_links: int = typer.Option(10000, "--max-links"),
    ) -> None:
        """Inspect persisted associations, not execution state or per-Run costs."""
        try:
            if confirm_read is not True:
                raise ValueError("read consent required")
            selected = [value for value in (run_id, session_id, operation) if value is not None]
            if len(selected) != 1:
                raise ValueError("select exactly one run, session or operation")
            _label(selected[0])
            links = SQLiteServiceUsageLinkStore(links_database, max_links=max_links)

            async def read():
                if run_id is not None:
                    result = await links.get(run_id)
                    return () if result is None else (result,)
                if session_id is not None:
                    return await links.for_session(session_id)
                return await links.for_operation(operation)

            found = asyncio.run(read())
            report = {"association_only": True, "run_state": "not-inferred",
                      "count": len(found), "links": [_link_payload(link) for link in found]}
        except Exception:
            typer.echo("Service usage links read failed; check consent, selection and store. No store was created.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False))


def _link_payload(link: ServiceUsageRunLink) -> dict[str, str]:
    return {"session_id": link.session_id, "run_id": link.run_id, "operation_id": link.operation_id}
