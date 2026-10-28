"""CLI adapters for local index review, with no hidden remote execution."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_index_journal import KnowledgeIndexReconciliation
from w_agent.knowledge_index_management import KnowledgeIndexReviewRequest, review_local_knowledge_index, list_local_knowledge_journals
from w_agent.knowledge_plan_sqlite import inspect_stored_knowledge_plan
from w_agent.knowledge_plan_catalog import review_knowledge_plan_catalog
from w_agent.knowledge_batches import review_missing_knowledge_batches


def _execute(options: dict, decision_options: dict | None = None) -> None:
    try:
        decision = KnowledgeIndexReconciliation(**decision_options) if decision_options is not None else None
        request = KnowledgeIndexReviewRequest(**options, decision=decision)
        result = asyncio.run(review_local_knowledge_index(request))
    except Exception:
        typer.echo("Index review failed; check options/consent. A decision may already be saved: inspect before retrying. No remote write was requested.", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))


def register_knowledge_index_commands(app: typer.Typer) -> None:
    @app.command("knowledge-index-list")
    def list_journals(
        database: Path = typer.Option(..., "--database"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_details: bool = typer.Option(False, "--include-details"),
    ) -> None:
        """Discover validated local receipt manifests and unresolved attempts."""
        try:
            result = asyncio.run(list_local_knowledge_journals(
                database, confirm_read=confirm_read, include_details=include_details,
            ))
        except Exception:
            typer.echo("Journal catalog read failed; unavailable state is not an empty catalog.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-plan-batches")
    def missing_batches(
        plan_database: Path = typer.Option(..., "--plan-database"),
        source_database: Path = typer.Option(..., "--source-database"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        manifest_digest: str = typer.Option(..., "--manifest-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_ids: bool = typer.Option(False, "--include-ids"),
        max_documents: int = typer.Option(128, "--max-documents"),
        max_input_bytes: int = typer.Option(1024 * 1024, "--max-input-bytes"),
        max_vector_values: int = typer.Option(1024 * 1024, "--max-vector-values"),
    ) -> None:
        """Suggest missing preparation batches; no embedding, save, approval or write."""
        try:
            result = asyncio.run(review_missing_knowledge_batches(
                plan_database, source_database, namespace, version, manifest_digest,
                confirm_read=confirm_read, include_ids=include_ids,
                max_documents=max_documents, max_input_bytes=max_input_bytes,
                max_vector_values=max_vector_values,
            ))
        except Exception:
            typer.echo("Batch review failed; check consent, exact snapshot and plan-store integrity. No preparation or write requested.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-plan-list")
    def list_plans(
        database: Path = typer.Option(..., "--database"),
        manifest_digest: str | None = typer.Option(None, "--manifest-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_target: bool = typer.Option(False, "--include-target"),
    ) -> None:
        """List verified staged plans and local preparation coverage; never execute."""
        try:
            result = asyncio.run(review_knowledge_plan_catalog(
                database, manifest_digest=manifest_digest, confirm_read=confirm_read, include_target=include_target,
            ))
        except Exception:
            typer.echo("Plan catalog read failed; check consent and store integrity. No remote write requested.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-plan-inspect")
    def inspect_plan(
        database: Path = typer.Option(..., "--database"),
        artifact_digest: str = typer.Option(..., "--artifact-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_target: bool = typer.Option(False, "--include-target"),
    ) -> None:
        """Inspect a saved exact plan without disclosing vectors or sending it."""
        try:
            result = asyncio.run(inspect_stored_knowledge_plan(
                database, artifact_digest, confirm_read=confirm_read, include_target=include_target,
            ))
        except Exception:
            typer.echo("Plan inspection failed; check identity, read consent and database. No remote write requested.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-index-inspect")
    def inspect(
        database: Path = typer.Option(..., "--database"),
        manifest_digest: str = typer.Option(..., "--manifest-digest"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_details: bool = typer.Option(False, "--include-details"),
    ) -> None:
        """View local observations, not proof of current remote index state."""
        _execute(dict(database=database, manifest_digest=manifest_digest,
                      confirm_read=confirm_read, include_details=include_details))

    @app.command("knowledge-index-reconcile")
    def reconcile(
        database: Path = typer.Option(..., "--database"),
        manifest_digest: str = typer.Option(..., "--manifest-digest"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        plan_digest: str = typer.Option(..., "--plan-digest"),
        expected_outcome: str = typer.Option(..., "--expected-outcome"),
        outcome: str = typer.Option(..., "--outcome", help="Host-evidenced completed or not-applied."),
        reconciliation_id: str = typer.Option(..., "--reconciliation-id"),
        evidence_ref: str = typer.Option(..., "--evidence-ref"),
        actor_ref: str = typer.Option(..., "--actor-ref"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_write: bool = typer.Option(False, "--confirm-write"),
        confirm_inactive: bool = typer.Option(False, "--confirm-inactive", help="Assert exact attempt cannot have late local/remote effects."),
        include_details: bool = typer.Option(False, "--include-details"),
    ) -> None:
        """Record independently reviewed evidence locally; never resend an upsert."""
        _execute(
            dict(database=database, manifest_digest=manifest_digest, confirm_read=confirm_read,
                 confirm_write=confirm_write, confirm_inactive=confirm_inactive, include_details=include_details),
            dict(reconciliation_id=reconciliation_id, manifest_digest=manifest_digest,
                 attempt_id=attempt_id, plan_digest=plan_digest, expected_outcome=expected_outcome,
                 outcome=outcome, evidence_ref=evidence_ref, actor_ref=actor_ref),
        )
