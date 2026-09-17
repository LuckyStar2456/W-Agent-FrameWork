"""Local developer CLI built only on public W-Agent APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from w_agent.agents import CODING_AGENT_TEMPLATE, CUSTOMER_SUPPORT_AGENT_TEMPLATE
from w_agent.compositions import (
    CompositionError,
    CompositionStore,
    encode_composition,
    inspect_composition,
    manifest_from_dict,
    manifest_to_dict,
)
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.container.bean_factory import BeanFactory
from w_agent.core.doctor import Doctor
from w_agent.models import AttemptRecord, EndpointProbe
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    assemble_local_runtime,
    load_local_runtime_config,
)
from w_agent.sessions import JsonSessionStore, SessionError, SessionManager, SessionRecord

app = typer.Typer(
    name="wagent",
    help="W-Agent Command Line Tool — local CLI for the open framework.",
    no_args_is_help=True,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)
profile_app = typer.Typer(help="Inspect built-in editable agent templates.")
composition_app = typer.Typer(help="Encode, inspect, and store compositions.")
session_app = typer.Typer(help="Manage local persistent agent sessions.")
config_app = typer.Typer(help="Compatibility configuration commands.")
bean_app = typer.Typer(help="Compatibility IOC-container commands.")
app.add_typer(profile_app, name="profile")
app.add_typer(composition_app, name="composition")
app.add_typer(session_app, name="session")
app.add_typer(config_app, name="config")
app.add_typer(bean_app, name="bean")
console = Console()
error_console = Console(stderr=True)


@app.callback()
def root(
    show_version: bool = typer.Option(
        False,
        "--version",
        "-V",
        is_eager=True,
        help="Show the installed framework version.",
    ),
) -> None:
    if show_version:
        console.print(f"W-Agent version {get_version()}")
        raise typer.Exit()


def get_version() -> str:
    from w_agent import __version__

    return __version__


@app.command("version")
def version_command() -> None:
    """Show the installed framework version."""

    console.print(f"W-Agent version {get_version()}")


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Workspace directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Create a local state layout without overwriting project files."""

    workspace = path.resolve()
    state = workspace / ".wagent"
    created: list[str] = []
    for child in (
        state,
        state / "compositions",
        state / "sessions",
        state / "runs",
        state / "workflows",
    ):
        if not child.exists():
            child.mkdir(parents=True)
            created.append(str(child))
    config = state / "config.json"
    if not config.exists():
        config.write_text("{}\n", encoding="utf-8")
        created.append(str(config))
    _emit({"workspace": str(workspace), "created": created}, json_output)


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Run local dependency and backend diagnostics."""

    results = Doctor().run_all_checks()
    payload = {
        name: {"passed": passed, "message": message}
        for name, (passed, message) in results.items()
    }
    if json_output:
        _emit(payload, True)
    else:
        table = Table(title="W-Agent doctor")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for name, item in payload.items():
            table.add_row(
                name,
                "PASS" if item["passed"] else "FAIL",
                str(item["message"]),
            )
        console.print(table)
    if not all(bool(item["passed"]) for item in payload.values()):
        raise typer.Exit(1)


@app.command("health")
def health_alias(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Compatibility alias for doctor."""

    doctor(json_output)


@app.command()
def probe(
    endpoint: str = typer.Argument(..., help="HTTP(S) endpoint to inspect."),
    timeout: float = typer.Option(3.0, min=0.1),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Run the safe L1 probe without credentials or request bodies."""

    result = asyncio.run(EndpointProbe(timeout=timeout).probe(endpoint))
    payload = {
        "target": result.target,
        "successful": result.successful,
        "latency_ms": result.latency_ms,
        "checks": [
            {
                "level": int(check.level),
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "latency_ms": check.latency_ms,
            }
            for check in result.checks
        ],
    }
    _emit(payload, json_output)
    if not result.successful:
        raise typer.Exit(2)


@app.command("run")
def run_command(
    prompt: str = typer.Argument(..., help="User text for one configured run."),
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    session_id: str | None = typer.Option(None, "--session"),
    session_title: str | None = typer.Option(None, "--title"),
    confirm_model_call: bool = typer.Option(
        False,
        "--confirm-model-call",
        help="Explicitly authorize a potentially billable network model call.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Run the configured text agent with persistent run/session state."""

    if not confirm_model_call:
        _fail("model call not authorized; pass --confirm-model-call")
    try:
        runtime = assemble_local_runtime(
            load_local_runtime_config(config),
            state_root,
        )
        run = asyncio.run(
            runtime.run(
                prompt,
                session_id=session_id,
                session_title=session_title,
            )
        )
    except (LocalRuntimeConfigError, SessionError, ValueError) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured run failed: {type(error).__name__}")
    result = run.result
    _emit(
        {
            "session_id": run.session.session_id,
            "run_id": result.run_id,
            "stop_reason": result.stop_reason.value,
            "output": result.output,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "attempts": [_attempt_payload(item) for item in result.attempts],
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cached_input_tokens": result.usage.cached_input_tokens,
                "total_tokens": result.usage.total_tokens,
                "complete": result.usage_complete,
            },
        },
        json_output,
    )


@profile_app.command("list")
def profile_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List built-in templates; custom definitions remain supported."""

    templates = (CUSTOMER_SUPPORT_AGENT_TEMPLATE, CODING_AGENT_TEMPLATE)
    payload = [
        {
            "key": item.key,
            "description": item.description,
            "recommended_tools": list(item.recommended_tools),
        }
        for item in templates
    ]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Agent templates")
    table.add_column("Key")
    table.add_column("Description")
    table.add_column("Recommended tools")
    for item in payload:
        table.add_row(
            str(item["key"]),
            str(item["description"]),
            ", ".join(item["recommended_tools"]),
        )
    console.print(table)


@config_app.command("list")
def config_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List values in the legacy in-process dynamic configuration."""

    _emit(DynamicConfigManager().as_dict(), json_output)


@config_app.command("get")
def config_get(key: str) -> None:
    """Read one legacy in-process configuration value."""

    _emit({key: DynamicConfigManager().get(key)}, False)


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set one legacy in-process configuration value."""

    DynamicConfigManager().set(key, value)
    _emit({key: value}, False)


@bean_app.command("list")
def bean_list() -> None:
    """List beans from a new legacy compatibility container."""

    _emit(BeanFactory().list_beans(), False)


@bean_app.command("info")
def bean_info(name: str) -> None:
    """Resolve one bean from a new legacy compatibility container."""

    async def resolve() -> object:
        return await BeanFactory().get_bean(name)

    try:
        bean = asyncio.run(resolve())
    except Exception as error:
        _fail(f"bean {name!r} could not be resolved: {type(error).__name__}")
    _emit({"name": name, "type": type(bean).__name__}, False)


@composition_app.command("export")
def composition_export(
    manifest: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Validate a JSON manifest and print its deterministic code."""

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        typer.echo(encode_composition(manifest_from_dict(data)))
    except (CompositionError, json.JSONDecodeError, TypeError) as error:
        _fail(str(error))


@composition_app.command("inspect")
def composition_inspect(
    code: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Preview a code without network, imports, or execution."""

    try:
        preview = inspect_composition(code)
    except CompositionError as error:
        _fail(str(error))
    payload = {
        "digest": preview.digest,
        "manifest": manifest_to_dict(preview.manifest),
        "plugin_dependencies": list(preview.plugin_dependencies),
        "risks": list(preview.risks),
    }
    _emit(payload, json_output)


@composition_app.command("save")
def composition_save(
    code: str = typer.Argument(...),
    root: Path = typer.Option(Path(".wagent/compositions"), "--root"),
    alias: str | None = typer.Option(None, "--alias"),
) -> None:
    """Save a validated code; never install or load its plugins."""

    try:
        preview = inspect_composition(code)
        digest = CompositionStore(root).save(preview.manifest, alias=alias)
    except CompositionError as error:
        _fail(str(error))
    _emit(
        {
            "name": preview.manifest.name,
            "version": preview.manifest.version,
            "digest": digest,
            "alias": alias,
        },
        False,
    )


@composition_app.command("list")
def composition_list(
    root: Path = typer.Option(Path(".wagent/compositions"), "--root"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List locally stored composition versions."""

    entries = [
        {"name": name, "version": version}
        for name, version in CompositionStore(root).entries()
    ]
    _emit(entries, json_output)


@session_app.command("create")
def session_create(
    title: str = typer.Argument(..., help="Human-readable local session title."),
    session_id: str | None = typer.Option(None, "--id", help="Optional stable ID."),
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Create a local session without starting a model run."""

    manager = SessionManager(JsonSessionStore(root))
    try:
        session = asyncio.run(manager.create(title, session_id=session_id))
    except (SessionError, ValueError) as error:
        _fail(str(error))
    _emit(_session_payload(session, include_details=False), json_output)


@session_app.command("list")
def session_list(
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    include_archived: bool = typer.Option(False, "--include-archived"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List local sessions, newest first."""

    manager = SessionManager(JsonSessionStore(root))
    sessions = asyncio.run(manager.list(include_archived=include_archived))
    payload = [_session_payload(item, include_details=False) for item in sessions]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Local sessions")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Runs", justify="right")
    table.add_column("Tokens", justify="right")
    for item in payload:
        table.add_row(
            str(item["session_id"]),
            str(item["title"]),
            str(item["status"]),
            str(item["run_count"]),
            str(item["total_tokens"]),
        )
    console.print(table)


@session_app.command("show")
def session_show(
    session_id: str = typer.Argument(...),
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show messages, run summaries, and visible token usage."""

    manager = SessionManager(JsonSessionStore(root))
    try:
        session = asyncio.run(manager.get(session_id))
    except (SessionError, ValueError) as error:
        _fail(str(error))
    _emit(_session_payload(session, include_details=True), json_output)


@session_app.command("archive")
def session_archive(
    session_id: str = typer.Argument(...),
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Archive a session, making it read-only for agent runs."""

    _set_session_archived(session_id, root, archived=True, json_output=json_output)


@session_app.command("unarchive")
def session_unarchive(
    session_id: str = typer.Argument(...),
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Return an archived session to active use."""

    _set_session_archived(session_id, root, archived=False, json_output=json_output)


@app.command()
def tui() -> None:
    """Launch the optional local Textual interface."""

    try:
        from w_agent.tui import run_tui
    except ImportError:
        _fail('TUI dependencies are missing; install "wagent-framework[tui]"')
    run_tui()


def _emit(value: Any, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            console.print(f"{key}: {item}", markup=False)
    elif isinstance(value, list):
        for item in value:
            console.print(item, markup=False)
    else:
        console.print(value, markup=False)


def _set_session_archived(
    session_id: str,
    root: Path,
    *,
    archived: bool,
    json_output: bool,
) -> None:
    manager = SessionManager(JsonSessionStore(root))
    try:
        session = asyncio.run(manager.archive(session_id, archived=archived))
    except (SessionError, ValueError) as error:
        _fail(str(error))
    _emit(_session_payload(session, include_details=False), json_output)


def _session_payload(
    session: SessionRecord,
    *,
    include_details: bool,
) -> dict[str, Any]:
    input_tokens = sum(item.usage.input_tokens for item in session.runs)
    output_tokens = sum(item.usage.output_tokens for item in session.runs)
    model_calls = sum(item.model_calls for item in session.runs)
    reported_usage_calls = sum(
        item.reported_usage_calls for item in session.runs
    )
    payload: dict[str, Any] = {
        "session_id": session.session_id,
        "title": session.title,
        "status": session.status.value,
        "run_count": len(session.runs),
        "message_count": len(session.messages),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model_calls": model_calls,
        "reported_usage_calls": reported_usage_calls,
        "usage_complete": all(item.usage_complete for item in session.runs),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }
    if include_details:
        payload["messages"] = [
            {
                "role": item.role.value,
                "text": item.text,
                "run_id": item.run_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in session.messages
        ]
        payload["runs"] = [
            {
                "run_id": item.run_id,
                "agent_name": item.agent_name,
                "stop_reason": item.stop_reason,
                "output": item.output,
                "usage": {
                    "input_tokens": item.usage.input_tokens,
                    "output_tokens": item.usage.output_tokens,
                    "cached_input_tokens": item.usage.cached_input_tokens,
                },
                "usage_complete": item.usage_complete,
                "steps": item.steps,
                "tool_calls": item.tool_calls,
                "model_calls": item.model_calls,
                "reported_usage_calls": item.reported_usage_calls,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in session.runs
        ]
    return payload


def _attempt_payload(attempt: AttemptRecord) -> dict[str, Any]:
    return {
        "ordinal": attempt.ordinal,
        "route_index": attempt.route_index,
        "route_attempt": attempt.route_attempt,
        "provider": attempt.provider,
        "model": attempt.model,
        "outcome": attempt.outcome.value,
        "duration_ms": attempt.duration_ms,
        "failure_code": (
            attempt.failure.code if attempt.failure is not None else None
        ),
        "usage": (
            {
                "input_tokens": attempt.usage.input_tokens,
                "output_tokens": attempt.usage.output_tokens,
                "cached_input_tokens": attempt.usage.cached_input_tokens,
                "total_tokens": attempt.usage.total_tokens,
            }
            if attempt.usage is not None
            else None
        ),
        "usage_reported": attempt.usage_reported,
    }


def _fail(message: str) -> None:
    error_console.print(f"Error: {message}", markup=False)
    raise typer.Exit(2)


def main() -> None:
    app(prog_name="wagent")


if __name__ == "__main__":
    main()
