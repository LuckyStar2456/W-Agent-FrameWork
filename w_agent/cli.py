"""Local developer CLI built only on public W-Agent APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from w_agent.agents import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    JsonlRunStore,
    RunCheckpointSummary,
    RunStoreError,
)
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
from w_agent.evaluation import (
    ContainsTextScorer,
    EvaluationCase,
    EvaluationDatasetError,
    EvaluationReport,
    EvaluationScorer,
    ExactTextScorer,
    JsonEvaluationReporter,
    LocalEvaluationRunner,
    evaluation_report_to_dict,
    load_evaluation_cases,
)
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    assemble_local_provider,
    assemble_local_runtime,
    load_local_runtime_config,
)
from w_agent.models import (
    AttemptRecord,
    EndpointProbe,
    ModelCost,
    ModelProviderProbe,
    PricingError,
    ProbeMode,
    ProbeResult,
)
from w_agent.sessions import (
    JsonSessionStore,
    SessionError,
    SessionManager,
    SessionRecord,
)
from w_agent.tools import ToolEntryLoadError, load_tool_entries
from w_agent.workflows import (
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    WorkflowCheckpointSummary,
    WorkflowEntryLoadError,
    WorkflowStoreError,
    load_workflow_entries,
)

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
checkpoint_app = typer.Typer(help="Inspect local prompt-free checkpoint summaries.")
app.add_typer(profile_app, name="profile")
app.add_typer(composition_app, name="composition")
app.add_typer(session_app, name="session")
app.add_typer(config_app, name="config")
app.add_typer(bean_app, name="bean")
app.add_typer(checkpoint_app, name="checkpoint")
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
    payload = _probe_result_payload(result)
    _emit(payload, json_output)
    if not result.successful:
        raise typer.Exit(2)


@app.command("provider-probe")
def provider_probe_command(
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    mode: ProbeMode = typer.Option(ProbeMode.SAFE, "--mode", case_sensitive=False),
    confirm_active_probe: bool = typer.Option(
        False,
        "--confirm-active-probe",
        help="Authorize a potentially billable minimal generation request.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Probe the provider assembled from strict local configuration."""

    if mode is not ProbeMode.SAFE and not confirm_active_probe:
        _fail("active probe not authorized; pass --confirm-active-probe")
    try:
        config_value = load_local_runtime_config(config)
        result = asyncio.run(
            _probe_configured_provider(
                config_value,
                mode=mode,
                allow_active=confirm_active_probe,
            )
        )
    except (LocalRuntimeConfigError, ValueError) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured provider probe failed: {type(error).__name__}")
    _emit(_probe_result_payload(result), json_output)
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
    tool_entry: list[str] = typer.Option(
        [],
        "--tool-entry",
        help="Explicit module:attribute tool binding entry; may repeat.",
    ),
    confirm_tool_code: bool = typer.Option(
        False,
        "--confirm-tool-code",
        help="Authorize importing and executing the supplied Python tool entries.",
    ),
    grant_permission: list[str] = typer.Option(
        [],
        "--grant-permission",
        help="Grant one runtime tool permission; may repeat.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Run the configured text agent with persistent run/session state."""

    if not confirm_model_call:
        _fail("model call not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    try:
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        runtime = assemble_local_runtime(
            load_local_runtime_config(config),
            state_root,
            tool_bindings=catalog,
        )
        run = asyncio.run(
            _run_configured_runtime(
                runtime,
                prompt,
                session_id=session_id,
                session_title=session_title,
                permissions=frozenset(grant_permission),
            )
        )
    except (
        LocalRuntimeConfigError,
        SessionError,
        ToolEntryLoadError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured run failed: {type(error).__name__}")
    _emit(_local_run_payload(run), json_output)


@app.command("run-resume")
def run_resume_command(
    session_id: str = typer.Argument(..., help="Session owning the checkpoint."),
    run_id: str = typer.Argument(..., help="Run/checkpoint ID to resume."),
    approve_tool_call: list[str] = typer.Option(
        [],
        "--approve-tool-call",
        help="Approve one exact pending call ID; may repeat.",
    ),
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    confirm_model_call: bool = typer.Option(
        False,
        "--confirm-model-call",
        help="Authorize the model call that may follow tool execution.",
    ),
    tool_entry: list[str] = typer.Option(
        [],
        "--tool-entry",
        help="Explicit module:attribute tool binding entry; may repeat.",
    ),
    confirm_tool_code: bool = typer.Option(
        False,
        "--confirm-tool-code",
        help="Authorize importing and executing the supplied Python tool entries.",
    ),
    grant_permission: list[str] = typer.Option(
        [],
        "--grant-permission",
        help="Grant one runtime tool permission; may repeat.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Resume a persisted tool-approval checkpoint with exact call IDs."""

    if not confirm_model_call:
        _fail("model call not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    if not approve_tool_call:
        _fail("no tool call approved; pass --approve-tool-call")
    try:
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        runtime = assemble_local_runtime(
            load_local_runtime_config(config),
            state_root,
            tool_bindings=catalog,
        )
        run = asyncio.run(
            _resume_configured_runtime(
                runtime,
                session_id,
                run_id,
                permissions=frozenset(grant_permission),
                approved_call_ids=frozenset(approve_tool_call),
            )
        )
    except (
        LocalRuntimeConfigError,
        RunStoreError,
        SessionError,
        ToolEntryLoadError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured resume failed: {type(error).__name__}")
    _emit(_local_run_payload(run), json_output)


@app.command("evaluate")
def evaluate_command(
    dataset: Path = typer.Argument(..., help="Strict local JSON evaluation dataset."),
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    scorer: list[str] = typer.Option(
        ["exact-text"],
        "--scorer",
        help="exact-text, contains-text, or none; may repeat.",
    ),
    case_sensitive: bool = typer.Option(
        True,
        "--case-sensitive/--ignore-case",
    ),
    report_path: Path | None = typer.Option(None, "--report"),
    state_root: Path | None = typer.Option(
        None,
        "--state-root",
        help="Persist case sessions here; omitted uses disposable state.",
    ),
    include_outputs: bool = typer.Option(
        False,
        "--include-outputs",
        help="Include potentially sensitive model outputs in JSON/report data.",
    ),
    confirm_model_call: bool = typer.Option(
        False,
        "--confirm-model-call",
        help="Explicitly authorize potentially billable network model calls.",
    ),
    tool_entry: list[str] = typer.Option(
        [],
        "--tool-entry",
        help="Explicit module:attribute tool binding entry; may repeat.",
    ),
    confirm_tool_code: bool = typer.Option(
        False,
        "--confirm-tool-code",
        help="Authorize importing and executing the supplied Python tool entries.",
    ),
    grant_permission: list[str] = typer.Option(
        [],
        "--grant-permission",
        help="Grant one runtime tool permission; may repeat.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Evaluate the configured agent sequentially against a local dataset."""

    if not confirm_model_call:
        _fail("model calls not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    try:
        cases = load_evaluation_cases(dataset)
        scorers = _evaluation_scorers(scorer, case_sensitive=case_sensitive)
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        config_value = load_local_runtime_config(config)
        root_context = (
            TemporaryDirectory(prefix="wagent-eval-")
            if state_root is None
            else nullcontext(state_root)
        )
        with root_context as evaluation_root:
            runtime = assemble_local_runtime(
                config_value,
                evaluation_root,
                tool_bindings=catalog,
            )
            report = asyncio.run(
                _run_local_evaluation(
                    runtime,
                    cases,
                    scorers,
                    permissions=frozenset(grant_permission),
                )
            )
        if report_path is not None:
            asyncio.run(
                JsonEvaluationReporter(include_outputs=include_outputs).write(
                    report,
                    report_path,
                )
            )
    except (
        EvaluationDatasetError,
        LocalRuntimeConfigError,
        ToolEntryLoadError,
        OSError,
        ValueError,
    ) as error:
        _fail(str(error))
    payload = evaluation_report_to_dict(report, include_outputs=include_outputs)
    _emit_evaluation(payload, json_output=json_output)
    if report.passed != report.total:
        raise typer.Exit(1)


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


@checkpoint_app.command("list")
def checkpoint_list(
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    session_id: str | None = typer.Option(None, "--session"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List approval checkpoints without prompts or argument values."""

    try:
        checkpoints = asyncio.run(JsonlRunStore(state_root).list_checkpoints())
    except (RunStoreError, ValueError) as error:
        _fail(str(error))
    if session_id is not None:
        checkpoints = tuple(
            item for item in checkpoints if item.session_id == session_id
        )
    payload = [_checkpoint_payload(item) for item in checkpoints]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Agent approval checkpoints")
    table.add_column("Run")
    table.add_column("Session")
    table.add_column("Status")
    table.add_column("Tool")
    table.add_column("Call ID")
    table.add_column("Argument keys")
    for item in payload:
        table.add_row(
            str(item["run_id"]),
            str(item["session_id"] or "-"),
            str(item["status"]),
            str(item["pending_tool_name"] or "-"),
            str(item["pending_call_id"] or "-"),
            ", ".join(item["pending_argument_keys"]),
        )
    console.print(table)


@checkpoint_app.command("workflow-list")
def workflow_checkpoint_list(
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    session_id: str | None = typer.Option(None, "--session"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List workflow checkpoints without runtime input/state/output values."""

    try:
        checkpoints = asyncio.run(
            JsonlWorkflowStore(state_root).list_checkpoints()
        )
    except (OSError, WorkflowStoreError, ValueError) as error:
        _fail(str(error))
    if session_id is not None:
        checkpoints = tuple(
            item for item in checkpoints if item.session_id == session_id
        )
    payload = [_workflow_checkpoint_payload(item) for item in checkpoints]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Workflow checkpoints")
    table.add_column("Run")
    table.add_column("Session")
    table.add_column("Workflow")
    table.add_column("Kind")
    table.add_column("Status")
    table.add_column("Current node")
    table.add_column("Completed")
    table.add_column("Remaining")
    for item in payload:
        table.add_row(
            str(item["run_id"]),
            str(item["session_id"] or "-"),
            f"{item['workflow_name']}@{item['workflow_version']}",
            str(item["kind"]),
            str(item["status"]),
            str(item["current_node"] or "-"),
            ", ".join(item["completed_nodes"]) or "-",
            ", ".join(item["remaining_nodes"]) or "-",
        )
    console.print(table)


@checkpoint_app.command("workflow-resume")
def workflow_checkpoint_resume(
    run_id: str = typer.Argument(..., help="Workflow run/checkpoint ID."),
    workflow_entry: list[str] = typer.Option(
        [],
        "--workflow-entry",
        help="Explicit module:attribute workflow definition entry; may repeat.",
    ),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    confirm_workflow_code: bool = typer.Option(
        False,
        "--confirm-workflow-code",
        help="Authorize importing and executing developer Python workflow code.",
    ),
    confirm_resume: bool = typer.Option(
        False,
        "--confirm-resume",
        help="Authorize resuming the exact persisted workflow run.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Load an exact versioned workflow definition and resume its checkpoint."""

    if not confirm_resume:
        _fail("workflow resume not authorized; pass --confirm-resume")
    if not workflow_entry:
        _fail("no workflow definition supplied; pass --workflow-entry")
    if not confirm_workflow_code:
        _fail("workflow code not authorized; pass --confirm-workflow-code")
    try:
        result = asyncio.run(
            _resume_workflow_checkpoint(
                state_root,
                run_id,
                workflow_entry,
            )
        )
    except (
        OSError,
        WorkflowEntryLoadError,
        WorkflowStoreError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"workflow resume failed: {type(error).__name__}")
    _emit(_workflow_result_payload(result), json_output)


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


def _evaluation_scorers(
    names: list[str],
    *,
    case_sensitive: bool,
) -> tuple[EvaluationScorer, ...]:
    if not names:
        raise ValueError("at least one evaluation scorer is required")
    normalized = tuple(name.strip().lower() for name in names)
    if len(set(normalized)) != len(normalized):
        raise ValueError("evaluation scorers must be unique")
    if "none" in normalized:
        if normalized != ("none",):
            raise ValueError("the none scorer cannot be combined with other scorers")
        return ()
    available: dict[str, EvaluationScorer] = {
        "exact-text": ExactTextScorer(case_sensitive=case_sensitive),
        "contains-text": ContainsTextScorer(case_sensitive=case_sensitive),
    }
    unknown = [name for name in normalized if name not in available]
    if unknown:
        raise ValueError(f"unsupported evaluation scorer: {unknown[0]}")
    return tuple(available[name] for name in normalized)


async def _run_local_evaluation(
    runtime: Any,
    cases: tuple[EvaluationCase, ...],
    scorers: tuple[EvaluationScorer, ...],
    *,
    permissions: frozenset[str],
) -> EvaluationReport:
    async def target(case: EvaluationCase):
        run = await runtime.run(
            case.prompt,
            session_title=f"Evaluation: {case.name}",
            permissions=permissions,
        )
        return run.result

    async with runtime:
        return await LocalEvaluationRunner().run(cases, target, scorers=scorers)


async def _run_configured_runtime(
    runtime: Any,
    prompt: str,
    *,
    session_id: str | None,
    session_title: str | None,
    permissions: frozenset[str],
) -> Any:
    async with runtime:
        return await runtime.run(
            prompt,
            session_id=session_id,
            session_title=session_title,
            permissions=permissions,
        )


async def _resume_configured_runtime(
    runtime: Any,
    session_id: str,
    run_id: str,
    *,
    permissions: frozenset[str],
    approved_call_ids: frozenset[str],
) -> Any:
    async with runtime:
        return await runtime.resume(
            session_id,
            run_id,
            permissions=permissions,
            approved_call_ids=approved_call_ids,
        )


async def _probe_configured_provider(
    config: Any,
    *,
    mode: ProbeMode,
    allow_active: bool,
) -> ProbeResult:
    assembly = assemble_local_provider(config)
    async with assembly:
        return await ModelProviderProbe().probe(
            assembly.name,
            assembly.provider,
            mode=mode,
            allow_active=allow_active,
            model=config.provider.model,
        )


async def _resume_workflow_checkpoint(
    state_root: Path,
    run_id: str,
    workflow_entries: list[str],
):
    store = JsonlWorkflowStore(state_root)
    checkpoint = await store.load_checkpoint(run_id)
    if checkpoint is None:
        raise WorkflowStoreError(
            f"workflow run {run_id!r} has no resumable checkpoint"
        )
    catalog = load_workflow_entries(workflow_entries)
    identity = (checkpoint.workflow_name, checkpoint.workflow_version)
    definition = catalog.get(identity)
    if definition is None:
        raise WorkflowEntryLoadError(
            "loaded entries do not provide exact workflow "
            f"{checkpoint.workflow_name}@{checkpoint.workflow_version}"
        )
    if definition.kind is not checkpoint.kind:
        raise WorkflowStoreError("loaded workflow kind differs from the checkpoint")
    return await LocalWorkflowEngine(store).resume(definition, run_id)


def _emit_evaluation(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        _emit(payload, True)
        return
    usage = payload["usage"]
    console.print(
        "Evaluation: "
        f"{payload['passed']}/{payload['total']} passed; "
        f"input={usage['input_tokens']} output={usage['output_tokens']} "
        f"total={usage['total_tokens']} complete={payload['usage_complete']}",
        markup=False,
    )
    if payload["cost"] is not None:
        console.print(
            "Cost: "
            f"{payload['cost']['total']} {payload['cost']['currency']} "
            f"(table={payload['cost']['price_table_version']}, "
            f"complete={payload['cost_complete']})",
            markup=False,
        )
    table = Table(title="Evaluation cases")
    table.add_column("Case")
    table.add_column("Status")
    table.add_column("Latency ms", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Tools", justify="right")
    for case in payload["cases"]:
        case_usage = case["usage"]
        table.add_row(
            str(case["name"]),
            "PASS" if case["passed"] else "FAIL",
            f"{case['latency_ms']:.2f}",
            str(case_usage["input_tokens"]),
            str(case_usage["output_tokens"]),
            f"{case['tool_successes']}/{case['tool_failures']}",
        )
    console.print(table)


def _probe_result_payload(result: ProbeResult) -> dict[str, Any]:
    return {
        "target": result.target,
        "mode": result.mode.value,
        "successful": result.successful,
        "latency_ms": result.latency_ms,
        "routes": [
            {"provider": provider, "model": model} for provider, model in result.routes
        ],
        "checks": [
            {
                "level": int(check.level),
                "name": check.name,
                "status": check.status.value,
                "message": check.message,
                "latency_ms": check.latency_ms,
                "failure_kind": (
                    check.failure_kind.value if check.failure_kind is not None else None
                ),
                "capabilities": sorted(item.value for item in check.capabilities),
            }
            for check in result.checks
        ],
    }


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
    reported_usage_calls = sum(item.reported_usage_calls for item in session.runs)
    cost = _aggregate_costs(tuple(item.cost for item in session.runs))
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
        "cost": _cost_payload(cost),
        "cost_complete": (
            cost is not None and all(item.cost_complete for item in session.runs)
        ),
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
                "cost": _cost_payload(item.cost),
                "cost_complete": item.cost_complete,
                "priced_usage_calls": item.priced_usage_calls,
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
        "failure_code": (attempt.failure.code if attempt.failure is not None else None),
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


def _local_run_payload(run: Any) -> dict[str, Any]:
    result = run.result
    pending = result.pending_tool_call
    return {
        "session_id": run.session.session_id,
        "run_id": result.run_id,
        "checkpoint_id": result.checkpoint_id,
        "stop_reason": result.stop_reason.value,
        "output": result.output,
        "steps": result.steps,
        "tool_calls": result.tool_calls,
        "pending_tool": (
            {
                "call_id": pending.id,
                "name": pending.name,
                "argument_keys": sorted(pending.arguments),
            }
            if pending is not None
            else None
        ),
        "attempts": [_attempt_payload(item) for item in result.attempts],
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cached_input_tokens": result.usage.cached_input_tokens,
            "total_tokens": result.usage.total_tokens,
            "complete": result.usage_complete,
        },
        "cost": _cost_payload(result.cost),
        "cost_complete": result.cost_complete,
        "priced_usage_calls": result.priced_usage_calls,
    }


def _checkpoint_payload(checkpoint: RunCheckpointSummary) -> dict[str, Any]:
    return {
        "run_id": checkpoint.run_id,
        "session_id": checkpoint.session_id,
        "status": checkpoint.status.value,
        "agent_name": checkpoint.agent_name,
        "pending_call_id": checkpoint.pending_call_id,
        "pending_tool_name": checkpoint.pending_tool_name,
        "pending_argument_keys": list(checkpoint.pending_argument_keys),
        "remaining_tool_calls": checkpoint.remaining_tool_calls,
        "steps": checkpoint.steps,
        "tool_calls": checkpoint.tool_calls,
        "model_calls": checkpoint.model_calls,
        "reported_usage_calls": checkpoint.reported_usage_calls,
        "priced_usage_calls": checkpoint.priced_usage_calls,
        "usage": {
            "input_tokens": checkpoint.usage.input_tokens,
            "output_tokens": checkpoint.usage.output_tokens,
            "cached_input_tokens": checkpoint.usage.cached_input_tokens,
            "total_tokens": checkpoint.usage.total_tokens,
            "complete": checkpoint.usage_complete,
        },
        "cost": _cost_payload(checkpoint.cost),
        "cost_complete": checkpoint.cost_complete,
    }


def _workflow_checkpoint_payload(
    checkpoint: WorkflowCheckpointSummary,
) -> dict[str, Any]:
    return {
        "run_id": checkpoint.run_id,
        "session_id": checkpoint.session_id,
        "workflow_name": checkpoint.workflow_name,
        "workflow_version": checkpoint.workflow_version,
        "kind": checkpoint.kind.value,
        "status": checkpoint.status.value,
        "current_node": checkpoint.current_node,
        "completed_nodes": list(checkpoint.completed_nodes),
        "remaining_nodes": list(checkpoint.remaining_nodes),
        "graph_steps": checkpoint.graph_steps,
        "resume_count": checkpoint.resume_count,
    }


def _workflow_result_payload(result: Any) -> dict[str, Any]:
    safe_fields = {
        "workflow",
        "version",
        "kind",
        "status",
        "node",
        "paused",
        "reason",
        "code",
    }
    return {
        "run_id": result.run_id,
        "stop_reason": result.stop_reason.value,
        "completed_nodes": list(result.completed_nodes),
        "checkpoint_id": result.checkpoint_id,
        "failure": result.failure,
        "events": [
            {
                "sequence": event.sequence,
                "type": event.type.value,
                "data": {
                    key: value
                    for key, value in event.data.items()
                    if key in safe_fields
                },
            }
            for event in result.events
        ],
    }


def _cost_payload(cost: ModelCost | None) -> dict[str, str] | None:
    if cost is None:
        return None
    return {
        "currency": cost.currency,
        "price_table_version": cost.price_table_version,
        "input_cost": str(cost.input_cost),
        "output_cost": str(cost.output_cost),
        "cached_input_cost": str(cost.cached_input_cost),
        "total": str(cost.total),
    }


def _aggregate_costs(costs: tuple[ModelCost | None, ...]) -> ModelCost | None:
    if not costs or any(cost is None for cost in costs):
        return None
    total = costs[0]
    assert total is not None
    try:
        for cost in costs[1:]:
            assert cost is not None
            total = total.add(cost)
    except PricingError:
        return None
    return total


def _fail(message: str) -> None:
    error_console.print(f"Error: {message}", markup=False)
    raise typer.Exit(2)


def main() -> None:
    app(prog_name="wagent")


if __name__ == "__main__":
    main()
