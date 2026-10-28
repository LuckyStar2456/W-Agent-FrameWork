"""CLI transport for the shared public application execution API."""

import asyncio
import json
from pathlib import Path

import typer

from w_agent.application import execute_application_entry, load_application_call


def register_application_commands(root: typer.Typer) -> None:
    app = typer.Typer(help="Run your own application plan, without requiring ReAct or model schemas.")
    root.add_typer(app, name="application")

    @app.command("run")
    def run(
        entry: str = typer.Option(..., "--entry", help="Trusted module:project_or_factory."),
        input_file: Path = typer.Option(..., "--input-file", help="JSON with operation, args and kwargs."),
        confirm_code: bool = typer.Option(False, "--confirm-code", help="Authorize UNSANDBOXED import, startup and operation execution."),
    ) -> None:
        """Execute one explicit call; emit JSON lines for stream items and result.

        Project code may access local files, services or models. This is trusted
        developer execution, not a sandbox or an automatic tool-approval grant.
        """
        if not confirm_code:
            typer.echo("Rejected: --confirm-code is required for unsandboxed application execution.", err=True)
            raise typer.Exit(2)
        try:
            call = load_application_call(input_file)

            def item(value):
                typer.echo(json.dumps({"item": value}, ensure_ascii=False, allow_nan=False))

            result = asyncio.run(execute_application_entry(entry, call, confirmed=True, on_item=item))
            typer.echo(json.dumps({"result": result}, ensure_ascii=False, allow_nan=False))
        except Exception as error:
            # User callbacks may include secrets in error messages or reprs.
            typer.echo(f"Application failed: {type(error).__name__}; no automatic replay.", err=True)
            raise typer.Exit(1) from None
