"""Explicit local build selection and read-only progress CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_build_management import (
    KnowledgeBuildExecuteRequest, create_local_knowledge_build,
    execute_local_knowledge_build_batch, review_local_knowledge_build,
    list_local_knowledge_builds,
)
from w_agent.knowledge_plan_actions import KnowledgeIndexHostOptions


def register_knowledge_build_commands(app: typer.Typer) -> None:
    @app.command("knowledge-build-list")
    def list_builds(
        database: Path = typer.Option(..., "--database"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Discover verified saved build names, versions and identities."""
        try:
            result = asyncio.run(list_local_knowledge_builds(database, confirm_read=confirm_read))
        except Exception:
            typer.echo("Build catalog read failed; unavailable state is not an empty catalog.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-build-execute")
    def execute_batch(
        host: str = typer.Option(..., "--host", help="Trusted local module:factory; executes without isolation."),
        binding: str = typer.Option(..., "--binding"),
        build_database: Path = typer.Option(..., "--build-database"),
        name: str = typer.Option(..., "--name"),
        version: str = typer.Option(..., "--version"),
        plan_database: Path = typer.Option(..., "--plan-database"),
        journal_database: Path = typer.Option(..., "--journal-database"),
        artifact_digest: str = typer.Option(..., "--artifact-digest"),
        approved_build_digest: str = typer.Option(..., "--approved-build-digest"),
        approved_artifact_digest: str = typer.Option(..., "--approved-artifact-digest"),
        confirm_code: bool = typer.Option(False, "--confirm-code"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_remote_write: bool = typer.Option(False, "--confirm-remote-write"),
        confirm_record: bool = typer.Option(False, "--confirm-record"),
        confirm_create_journal: bool = typer.Option(False, "--confirm-create-journal"),
        previous_attempt_id: str | None = typer.Option(None, "--previous-attempt-id", help="Explicit retry of this exact latest not-sent or reviewed not-applied attempt."),
    ) -> None:
        """Execute one batch, or explicitly retry its safe predecessor; never auto-retry."""
        try:
            request = KnowledgeBuildExecuteRequest(
                host=KnowledgeIndexHostOptions(host, binding, confirm_code),
                build_database=build_database, name=name, version=version,
                plan_database=plan_database, journal_database=journal_database,
                artifact_digest=artifact_digest, approved_build_digest=approved_build_digest,
                approved_artifact_digest=approved_artifact_digest, confirm_read=confirm_read,
                confirm_remote_write=confirm_remote_write, confirm_record=confirm_record,
                confirm_create_journal=confirm_create_journal,
                previous_attempt_id=previous_attempt_id,
            )
            result = asyncio.run(execute_local_knowledge_build_batch(request))
        except Exception:
            typer.echo("Build batch stopped/failed; remote write or receipt may already exist. Inspect before retry.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-build-create")
    def create(
        plan_database: Path = typer.Option(..., "--plan-database"),
        build_database: Path = typer.Option(..., "--build-database"),
        name: str = typer.Option(..., "--name"),
        version: str = typer.Option(..., "--version"),
        artifact_digests: list[str] = typer.Option(..., "--artifact-digest", help="Repeat explicit artifacts in desired order; full disjoint coverage required."),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_save: bool = typer.Option(False, "--confirm-save"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
    ) -> None:
        """Preview or explicitly save an immutable build; no embedding or remote write."""
        try:
            result = asyncio.run(create_local_knowledge_build(
                plan_database, build_database, name, version, tuple(artifact_digests),
                confirm_read=confirm_read, confirm_save=confirm_save, confirm_create=confirm_create,
            ))
        except Exception:
            typer.echo("Build creation failed; inspect saved state before retry. No remote write requested.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))

    @app.command("knowledge-build-inspect")
    def inspect_build(
        build_database: Path = typer.Option(..., "--build-database"),
        name: str = typer.Option(..., "--name"),
        version: str = typer.Option(..., "--version"),
        journal_database: Path | None = typer.Option(None, "--journal-database"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """Inspect exact build; optionally show journal-derived, non-remote progress."""
        try:
            result = asyncio.run(review_local_knowledge_build(
                build_database, name, version, confirm_read=confirm_read, journal_database=journal_database,
            ))
        except Exception:
            typer.echo("Build inspection failed; unavailable state is not an unstarted build.", err=True)
            raise typer.Exit(2) from None
        typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))
