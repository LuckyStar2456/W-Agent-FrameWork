"""Local knowledge CLI adapters; no execution at import time."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.knowledge_management import LocalKnowledgeRequest, manage_local_knowledge
from w_agent.knowledge_sqlite import KnowledgeStoreError


def _execute(**options: object) -> None:
    try:
        request = LocalKnowledgeRequest(**options)
        result = asyncio.run(manage_local_knowledge(request))
    except KnowledgeStoreError as error:
        typer.echo(json.dumps({"error": error.code, "may_have_written": error.may_have_written}), err=True)
        raise typer.Exit(2) from None
    except Exception:
        # Neither parser exceptions nor paths/document bodies are echoed.
        typer.echo("Knowledge operation failed; check options and permissions. Inspect the version before retrying any write.", err=True)
        raise typer.Exit(2) from None
    typer.echo(json.dumps(result, ensure_ascii=True, sort_keys=True))


def register_knowledge_commands(app: typer.Typer) -> None:
    @app.command("knowledge-import")
    def import_text(
        database: Path = typer.Option(..., "--database"),
        root: Path = typer.Option(..., "--root"),
        paths: list[str] = typer.Option(..., "--path", help="Repeat selected POSIX-relative paths; '.' selects root."),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        recursive: bool = typer.Option(False, "--recursive"),
        chunk_bytes: int = typer.Option(4096, "--chunk-bytes"),
        document_formats: bool = typer.Option(False, "--document-formats", help="Opt into optional local PDF/DOCX/XLSX/PPTX parsers."),
        expected_preview_digest: str | None = typer.Option(None, "--expected-preview-digest", help="Save only if source, options and destination match this preview digest."),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        confirm_write: bool = typer.Option(False, "--confirm-write"),
        confirm_create: bool = typer.Option(False, "--confirm-create"),
    ) -> None:
        """Preview selected UTF-8 text; explicitly opt into append-only persistence."""
        _execute(action="import", database=database, root=root, paths=tuple(paths),
                 namespace=namespace, version=version, recursive=recursive, chunk_bytes=chunk_bytes,
                 confirm_read=confirm_read, confirm_write=confirm_write, confirm_create=confirm_create,
                 document_formats=document_formats, expected_preview_digest=expected_preview_digest)

    @app.command("knowledge-list")
    def list_versions(
        database: Path = typer.Option(..., "--database"),
        namespace: str | None = typer.Option(None, "--namespace"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
    ) -> None:
        """List stored version metadata, without verifying or exposing bodies."""
        _execute(action="list", database=database, namespace=namespace, confirm_read=confirm_read)

    @app.command("knowledge-search")
    def search_version(
        database: Path = typer.Option(..., "--database"),
        namespace: str = typer.Option(..., "--namespace"),
        version: str = typer.Option(..., "--version"),
        query: str = typer.Option(..., "--query"),
        limit: int = typer.Option(4, "--limit"),
        confirm_read: bool = typer.Option(False, "--confirm-read"),
        include_text: bool = typer.Option(False, "--include-text", help="Explicitly disclose matched bodies in output."),
    ) -> None:
        """Verify and keyword-search an exact local version; no embedding/network."""
        _execute(action="search", database=database, namespace=namespace, version=version,
                 query=query, limit=limit, confirm_read=confirm_read, include_text=include_text)
