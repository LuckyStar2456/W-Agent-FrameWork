"""Persistent-in-process terminal session for explicitly trusted local plugins."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from w_agent.kernel.loading import load_plugin_references, load_yaml_references
from w_agent.kernel.plugins import PluginManager
from w_agent.plugin_replacement_session import PluginReplacementSession


async def run_plugin_session(config: Path) -> None:
    """Keep the local manager alive until exit; never target another process."""
    manager = PluginManager()
    review = PluginReplacementSession(manager)
    typer.echo(
        "Local plugin session: current process only; no project files or other processes "
        "are updated. Trusted Python code is NOT sandboxed. Exit unloads this session."
    )
    try:
        await load_plugin_references(manager, load_yaml_references(config))
        typer.echo("Commands: status | inspect <replacement.yml> | prepare | replace | cancel | exit")
        while True:
            try:
                command = (await asyncio.to_thread(typer.prompt, "plugin-session")).strip()
            except (EOFError, typer.Abort):
                return
            if command in {"exit", "quit"}:
                return
            try:
                if command == "status":
                    payload = {
                        "scope": "current_process_only",
                        "plugins": [{"name": item.spec.name, "version": item.spec.version,
                                     "state": item.state.value} for item in manager.records()],
                    }
                elif command.startswith("inspect "):
                    payload = review.inspect(command[len("inspect "):].strip())
                elif command == "prepare":
                    confirmation = await asyncio.to_thread(typer.prompt, "Exact IMPORT REPLACEMENT confirmation")
                    payload = await review.prepare(import_confirmation=confirmation)
                elif command == "replace":
                    typer.echo("Stop all users of this manager and release old snapshots first. No automatic draining.")
                    confirmation = await asyncio.to_thread(typer.prompt, "Exact REPLACE confirmation")
                    quiescent = await asyncio.to_thread(typer.prompt, "Exact QUIESCENT confirmation")
                    payload = await review.execute(
                        replace_confirmation=confirmation, quiescent_confirmation=quiescent,
                    )
                elif command == "cancel":
                    review.cancel()
                    payload = {"review_cancelled": True, "import_side_effects_undone": False}
                else:
                    typer.echo("Unknown command. Use status, inspect <path>, prepare, replace, cancel, exit.")
                    continue
                typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            except (EOFError, typer.Abort):
                return
            except Exception as error:
                # Config, imports and arbitrary plugins can include credentials in exceptions.
                typer.echo(f"Operation failed: {type(error).__name__}. Inspect lifecycle status; review again before retry.")
                review.cancel()
    finally:
        review.cancel()
        await manager.close()
