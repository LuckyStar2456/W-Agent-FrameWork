"""Thin CLI for persisted incremental sync; all authorization lives in requests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions
from w_agent.knowledge_sync_management import (
    KnowledgeSyncExecuteRequest, KnowledgeSyncImportRequest, KnowledgeSyncInspectRequest,
    KnowledgeSyncPrepareRequest, KnowledgeSyncReconcileRequest, KnowledgeSyncRetryRequest,
    execute_local_knowledge_sync, import_local_knowledge_sync, inspect_local_knowledge_sync,
    prepare_local_knowledge_sync, reconcile_local_knowledge_sync, retry_local_knowledge_sync,
)


def _run(request_type, service, **options) -> None:
    try:
        if "host_entry" in options:
            options["host"] = KnowledgeIndexHostOptions(options.pop("host_entry"), options.pop("binding"), options.pop("confirm_code"))
        request = request_type(**options)
        result = asyncio.run(service(request))
    except Exception:
        typer.echo("Knowledge sync failed; billing, persisted plans or remote writes may already exist. Inspect state before retry. No automatic replay or unlock.", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))


def register_knowledge_sync_commands(app: typer.Typer) -> None:
    @app.command("knowledge-sync-import")
    def import_trace(
        trace_database: Path = typer.Option(..., "--trace-database"),
        root: Path = typer.Option(..., "--root"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        paths: list[str] | None = typer.Option(None, "--path", help="Repeat POSIX-relative UTF-8 paths. No paths is an explicit empty selection."),
        recursive: bool = typer.Option(False, "--recursive"),
        document_formats: bool = typer.Option(False, "--document-formats", help="Explicitly enable optional PDF/DOCX/XLSX/PPTX extraction in addition to UTF-8."),
        chunk_bytes: int = typer.Option(4096, "--chunk-bytes"),
        splitter: str = typer.Option("utf8", "--splitter", help="utf8 (legacy) or structure (paragraph/sentence heuristics, no model)."),
        overlap_chars: int = typer.Option(0, "--overlap-chars", help="Structure-only bounded Unicode-character overlap."),
        expected_preview_digest: str | None = typer.Option(None, "--expected-preview-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
    ) -> None:
        """Preview selected files; explicitly enable document formats and approve exact trace saving."""
        _run(KnowledgeSyncImportRequest, import_local_knowledge_sync, trace_database=trace_database,
             root=root, paths=tuple(paths or ()), namespace=namespace, version=version, recursive=recursive,
             document_formats=document_formats,
             chunk_bytes=chunk_bytes, expected_preview_digest=expected_preview_digest,
             splitter=splitter, overlap_chars=overlap_chars,
             confirm_read=confirm_read, confirm_record=confirm_record, confirm_create=confirm_create)

    @app.command("knowledge-sync-prepare")
    def prepare(
        host_entry: str = typer.Option(..., "--host-entry"),
        binding: str = typer.Option(..., "--binding"),
        trace_database: Path = typer.Option(..., "--trace-database"),
        journal_database: Path = typer.Option(..., "--journal-database"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        expected_trace_digest: str = typer.Option(..., "--expected-trace-digest"),
        previous_plan_digest: str | None = typer.Option(None, "--previous-plan-digest"),
        approved_reuse_digest: str | None = typer.Option(None, "--approved-reuse-digest"),
        confirm_code: bool = typer.Option(False, "--confirm-code"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_embedding: bool = typer.Option(False, "--confirm-embedding"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
    ) -> None:
        """Embed only missing chunks; persist and reserve exact plan. Does not upsert/delete."""
        _run(KnowledgeSyncPrepareRequest, prepare_local_knowledge_sync, **locals())

    @app.command("knowledge-sync-inspect")
    def inspect_plan(
        journal_database: Path = typer.Option(..., "--journal-database"),
        plan_digest: str = typer.Option(..., "--plan-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Read safe local summary/status and definite-not-sent retry approvals; no host import."""
        _run(KnowledgeSyncInspectRequest, inspect_local_knowledge_sync, **locals())

    @app.command("knowledge-sync-execute")
    def execute(
        host_entry: str = typer.Option(..., "--host-entry"),
        binding: str = typer.Option(..., "--binding"),
        journal_database: Path = typer.Option(..., "--journal-database"),
        plan_digest: str = typer.Option(..., "--plan-digest"),
        approved_plan_digest: str = typer.Option(..., "--approved-plan-digest"),
        approved_upsert_digest: str | None = typer.Option(None, "--approved-upsert-digest", help="Independently authorizes exact remote upserts."),
        approved_delete_digest: str | None = typer.Option(None, "--approved-delete-digest", help="Independently authorizes exact remote whole-point deletion."),
        confirm_code: bool = typer.Option(False, "--confirm-code"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
    ) -> None:
        """Execute saved vectors; never re-embed or replay uncertain batches."""
        _run(KnowledgeSyncExecuteRequest, execute_local_knowledge_sync, **locals())

    @app.command("knowledge-sync-retry-not-sent")
    def retry(
        journal_database: Path = typer.Option(..., "--journal-database"),
        plan_digest: str = typer.Option(..., "--plan-digest"),
        batch: int = typer.Option(..., "--batch"),
        generation: int = typer.Option(..., "--generation"),
        retry_id: str = typer.Option(..., "--retry-id"),
        approved_retry_digest: str = typer.Option(..., "--approved-retry-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
    ) -> None:
        """Preserve definite-not-sent attempt and authorize a new generation locally; does not send."""
        _run(KnowledgeSyncRetryRequest, retry_local_knowledge_sync, **locals())

    @app.command("knowledge-sync-reconcile")
    def reconcile(
        journal_database: Path = typer.Option(..., "--journal-database"),
        plan_digest: str = typer.Option(..., "--plan-digest"),
        approved_plan_digest: str = typer.Option(..., "--approved-plan-digest"),
        batch: int = typer.Option(..., "--batch"),
        evidence_ref: str = typer.Option(..., "--evidence-ref"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
        confirm_applied: bool = typer.Option(False, "--confirm-applied"),
        confirm_inactive: bool = typer.Option(False, "--confirm-inactive"),
    ) -> None:
        """Record host-verified completed/inactive evidence; no remote query, reset or replay."""
        _run(KnowledgeSyncReconcileRequest, reconcile_local_knowledge_sync, **locals())
