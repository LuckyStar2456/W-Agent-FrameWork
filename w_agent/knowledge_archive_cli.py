"""Thin opt-in CLI for exact-version raw archival; output never contains bytes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_archive_management import (
    KnowledgeArchiveCreateRequest, KnowledgeArchiveExportRequest,
    KnowledgeArchiveInspectRequest, KnowledgeArchivePreviewRequest,
    archive_local_knowledge_sources, export_local_knowledge_blob,
    inspect_local_knowledge_archive, preview_local_knowledge_archive,
)


def _run(request_type, service, **options) -> None:
    try:
        result = asyncio.run(service(request_type(**options)))
    except Exception:
        typer.echo("Knowledge archive operation failed. No automatic retry. Inspect storage and any export destination; a new database or partial file may remain.", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))


def register_knowledge_archive_commands(app: typer.Typer) -> None:
    archive = typer.Typer(help="Explicit plaintext raw archives; no execution, directory restore or garbage collection.")
    app.add_typer(archive, name="knowledge-archive")

    @archive.command("preview")
    def preview(
        trace_database: Path = typer.Option(..., "--trace-database"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Read exact saved trace summary/digest, not the original source files."""
        _run(KnowledgeArchivePreviewRequest, preview_local_knowledge_archive, **locals())

    @archive.command("save")
    def save(
        trace_database: Path = typer.Option(..., "--trace-database"),
        archive_database: Path = typer.Option(..., "--archive-database"),
        root: Path = typer.Option(..., "--root"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        expected_trace_digest: str = typer.Option(..., "--expected-trace-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_sources: bool = typer.Option(False, "--confirm-sources"),
        confirm_write: bool = typer.Option(False, "--confirm-write"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
    ) -> None:
        """Approve exact trace and original reads; archive only hash-matching sources."""
        _run(KnowledgeArchiveCreateRequest, archive_local_knowledge_sources, **locals())

    @archive.command("inspect")
    def inspect(
        archive_database: Path = typer.Option(..., "--archive-database"),
        trace_digest: str = typer.Option(..., "--trace-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Read-only receipt/blob-integrity check; no bytes or paths printed."""
        _run(KnowledgeArchiveInspectRequest, inspect_local_knowledge_archive, **locals())

    @archive.command("export")
    def export(
        archive_database: Path = typer.Option(..., "--archive-database"),
        trace_digest: str = typer.Option(..., "--trace-digest"),
        expected_receipt_digest: str = typer.Option(..., "--expected-receipt-digest"),
        blob_digest: str = typer.Option(..., "--blob-digest"),
        destination: Path = typer.Option(..., "--destination"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_export: bool = typer.Option(False, "--confirm-export"),
        confirm_path: bool = typer.Option(False, "--confirm-path"),
    ) -> None:
        """Write one inert raw blob to a new explicit file; never overwrite or launch."""
        _run(KnowledgeArchiveExportRequest, export_local_knowledge_blob, **locals())
