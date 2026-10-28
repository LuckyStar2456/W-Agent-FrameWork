"""CLI preparation/execution adapters with no combined prepare-and-send command."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_build_recovery import SQLiteKnowledgePreparationStore

from w_agent.knowledge_plan_actions import (
    KnowledgeIndexHostOptions, KnowledgePlanExecuteRequest, KnowledgePlanPrepareRequest,
    execute_local_knowledge_plan, parse_knowledge_document_ids, prepare_local_knowledge_plan,
)


def _fail_action() -> None:
    typer.echo("Plan action failed; billing, saved plans or remote writes may already exist. Inspect state before retry; never blindly repeat preparation or execution.", err=True)
    raise typer.Exit(2) from None


def register_knowledge_plan_actions(app: typer.Typer) -> None:
    @app.command("knowledge-preparation-list")
    def list_preparations(
        database: Path = typer.Option(..., "--database"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Discover local pending/ready/abandoned embedding checkpoints."""
        try:
            if confirm_read is not True:
                raise ValueError("read confirmation required")
            entries = asyncio.run(SQLiteKnowledgePreparationStore(database).list_checkpoints())
            result = {"operation": "preparation-list", "checkpoints": [item.summary() for item in entries]}
        except Exception:
            _fail_action()
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-preparation-abandon")
    def abandon_preparation(
        database: Path = typer.Option(..., "--database"),
        batch_digest: str = typer.Option(..., "--batch-digest"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        evidence_ref: str = typer.Option(..., "--evidence-ref"),
        confirm_inactive: bool = typer.Option(False, "--confirm-inactive"),
        confirm_write: bool = typer.Option(False, "--confirm-write"),
    ) -> None:
        """Retire a stopped pending worker locally; never repeat embedding here."""
        try:
            item = asyncio.run(SQLiteKnowledgePreparationStore(database).abandon(
                batch_digest, attempt_id, evidence_ref=evidence_ref,
                confirm_inactive=confirm_inactive, confirm_write=confirm_write,
            ))
        except Exception:
            _fail_action()
        typer.echo(json.dumps(item.summary(), ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-plan-prepare")
    def prepare(
        host_entry: str = typer.Option(..., "--host-entry"),
        binding: str = typer.Option(..., "--binding"),
        source_database: Path = typer.Option(..., "--source-database"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        plan_database: Path = typer.Option(..., "--plan-database"),
        document_ids: str | None = typer.Option(None, "--document-ids", help="JSON array of exact string/integer document IDs; omit for a whole single-batch snapshot."),
        confirm_code: bool = typer.Option(False, "--confirm-code"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_embedding: bool = typer.Option(False, "--confirm-embedding"),
        confirm_save: bool = typer.Option(False, "--confirm-save"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
        include_target: bool = typer.Option(False, "--include-target"),
        preparation_database: Path | None = typer.Option(None, "--preparation-database"),
        preparation_attempt_id: str | None = typer.Option(None, "--preparation-attempt-id"),
    ) -> None:
        """Explicitly embed and stage one batch; never send an index write."""
        try:
            request = KnowledgePlanPrepareRequest(
                KnowledgeIndexHostOptions(host_entry, binding, confirm_code), source_database, namespace,
                version, plan_database, parse_knowledge_document_ids(document_ids),
                confirm_read, confirm_embedding, confirm_save, confirm_create, include_target,
                preparation_database, preparation_attempt_id,
            )
            result = asyncio.run(prepare_local_knowledge_plan(request))
        except Exception:
            _fail_action()
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-plan-execute")
    def execute(
        host_entry: str = typer.Option(..., "--host-entry"),
        binding: str = typer.Option(..., "--binding"),
        plan_database: Path = typer.Option(..., "--plan-database"),
        artifact_digest: str = typer.Option(..., "--artifact-digest"),
        approved_digest: str = typer.Option(..., "--approved-digest", help="Separately reviewed exact artifact digest; not automatic approval."),
        journal_database: Path = typer.Option(..., "--journal-database"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        confirm_code: bool = typer.Option(False, "--confirm-code"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_remote_write: bool = typer.Option(False, "--confirm-remote-write"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
        confirm_create_journal: bool = typer.Option(False, "--confirm-create-journal"),
    ) -> None:
        """Send the reviewed saved plan once with a journal; never re-embed."""
        try:
            request = KnowledgePlanExecuteRequest(
                KnowledgeIndexHostOptions(host_entry, binding, confirm_code), plan_database,
                artifact_digest, approved_digest, journal_database, attempt_id,
                confirm_read, confirm_remote_write, confirm_record, confirm_create_journal,
            )
            result = asyncio.run(execute_local_knowledge_plan(request))
        except Exception:
            _fail_action()
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))
