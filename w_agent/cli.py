"""Local developer CLI built only on public W-Agent APIs."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from w_agent._cli_replay import ReplayViewError, ViewOptions, run_view, session_view
from w_agent._shared_budget_ui import budget_binding_scope, shared_budget_summary
from w_agent._service_usage_ui import ServiceUsageOptions, service_usage_binding_scope, service_usage_summary
from w_agent._knowledge_ui import KnowledgeEvaluationOptions, KnowledgeRunOptions, knowledge_binding_scope
from w_agent.knowledge_cli import register_knowledge_commands
from w_agent.knowledge_index_cli import register_knowledge_index_commands
from w_agent.knowledge_plan_action_cli import register_knowledge_plan_actions
from w_agent.knowledge_build_cli import register_knowledge_build_commands
from w_agent.knowledge_sync_cli import register_knowledge_sync_commands
from w_agent.knowledge_archive_cli import register_knowledge_archive_commands
from w_agent.service_usage_cli import register_service_usage_commands
from w_agent.application_cli import register_application_commands
from w_agent.input_manifest import load_input_manifest
from w_agent.session_history_options import BuiltinSessionHistoryOptions
from w_agent.session_message_fields import MessageFieldsSessionInputRecorder
from w_agent.session_inputs import SessionInputRecorder

from w_agent.agents import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    JsonlRunStore,
    RunCheckpointSummary,
    RunEventCursor,
    RunEventReplay,
    RunStoreError,
    RunResult,
)
from w_agent.compositions import (
    CompositionError,
    CompositionStore,
    encode_composition,
    inspect_composition,
    manifest_from_dict,
    manifest_to_dict,
)
from w_agent.composition_planning import (
    CompositionEnvironment,
    StaticCompositionDependencyResolver,
    composition_plan_to_dict,
    load_plugin_candidates,
    plan_composition,
)
from w_agent.plugin_installation import (
    InstalledPluginReference,
    PluginInstallAuthorization,
    PluginInstallResult,
    PluginInstallationError,
    PluginInstallationPlan,
    SandboxPipPackageInstaller,
    load_installed_plugin_references,
    load_plugin_install_catalog,
    load_plugin_install_result,
    plan_plugin_installations,
    plugin_installation_plan_to_dict,
    recommended_docker_install_user,
)
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.container.bean_factory import BeanFactory
from w_agent.core.doctor import Doctor
from w_agent.evaluation import (
    CaseContractScorer,
    ContainsTextScorer,
    EvaluationCase,
    EvaluationDatasetError,
    EvaluationReport,
    EvaluationScorer,
    ExactTextScorer,
    JsonEvaluationReporter,
    LocalEvaluationRunner,
    evaluation_report_to_dict,
    load_evaluation_dataset,
)
from w_agent.evaluation_suites import (
    builtin_evaluation_suite_registry,
    evaluation_suite_to_dict,
)
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    assemble_local_provider,
    load_local_runtime_config,
)
from w_agent.local_application import open_local_runtime, open_local_workflow
from w_agent.kernel import (
    PluginLoadError,
    PluginManager,
    PluginRecord,
    PluginReference,
    load_plugin_references,
    load_yaml_references,
    preview_plugin_references,
)
from w_agent.models import (
    AttemptRecord,
    EndpointProbe,
    ModelCost,
    ModelProviderProbe,
    ModelMessage,
    PricingError,
    ProbeMode,
    ProbeResult,
)
from w_agent.sessions import (
    AgentUsageSummary,
    JsonSessionStore,
    SessionError,
    SessionManager,
    SessionRecord,
)
from w_agent.sandbox import (
    DockerSandboxProvider,
    SandboxNetwork,
    SandboxSpec,
    UnsafeLocalAuthorization,
    UnsafeLocalSandboxProvider,
)
from w_agent.tools import ToolEntryLoadError, load_tool_entries
from w_agent.workflows import (
    AgentWorkflowApproval,
    AgentWorkflowAdapterError,
    JsonlWorkflowStore,
    SQLiteWorkflowPauseController,
    WorkflowPauseControlError,
    WorkflowCheckpointSummary,
    WorkflowEntryLoadError,
    WorkflowStoreError,
    load_workflow_entries,
    review_workflow_approvals,
    open_workflow_approval_entry,
    resume_workflow_approval,
    WorkflowKind,
    WorkflowApprovalLinkStatus,
    WorkflowToolApprovalError,
    open_workflow_tool_approval_entry,
    review_workflow_tool_approvals,
    resume_workflow_tool_approval,
)

app = typer.Typer(
    name="wagent",
    help="W-Agent Command Line Tool — local CLI for the open framework.",
    no_args_is_help=True,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)
profile_app = typer.Typer(help="Inspect built-in editable agent templates.")
plugin_app = typer.Typer(help="Inspect and explicitly validate local plugins.")
composition_app = typer.Typer(help="Encode, inspect, and store compositions.")
session_app = typer.Typer(help="Manage local persistent agent sessions.")
config_app = typer.Typer(help="Compatibility configuration commands.")
bean_app = typer.Typer(help="Compatibility IOC-container commands.")
checkpoint_app = typer.Typer(help="Inspect local prompt-free checkpoint summaries.")
benchmark_app = typer.Typer(help="Inspect and export built-in evaluation suites.")
app.add_typer(profile_app, name="profile")
app.add_typer(plugin_app, name="plugin")
app.add_typer(composition_app, name="composition")
app.add_typer(session_app, name="session")
app.add_typer(config_app, name="config")
app.add_typer(bean_app, name="bean")
app.add_typer(checkpoint_app, name="checkpoint")
app.add_typer(benchmark_app, name="benchmark")
console = Console()
error_console = Console(stderr=True)
register_application_commands(app)


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
    usage_entry: str | None = typer.Option(None, "--usage-entry", help="Trusted module:factory usage-ledger catalog."),
    confirm_usage_code: bool = typer.Option(False, "--confirm-usage-code"),
    confirm_usage_recording: bool = typer.Option(False, "--confirm-usage-recording"),
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    budget_entry: str | None = typer.Option(None, "--budget-entry", help="Trusted module:factory returning an async budget-catalog context manager."),
    confirm_budget_code: bool = typer.Option(False, "--confirm-budget-code", help="Authorize unsandboxed host budget setup and cleanup code."),
    mode: ProbeMode = typer.Option(ProbeMode.SAFE, "--mode", case_sensitive=False),
    confirm_active_probe: bool = typer.Option(
        False,
        "--confirm-active-probe",
        help="Authorize a potentially billable minimal generation request.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Probe the provider assembled from strict local configuration."""

    _usage_options(usage_entry, confirm_usage_code, confirm_usage_recording)
    if budget_entry is not None and not confirm_budget_code:
        _fail("budget code not authorized; pass --confirm-budget-code")
    if mode is not ProbeMode.SAFE and not confirm_active_probe:
        _fail("active probe not authorized; pass --confirm-active-probe")
    try:
        config_value = load_local_runtime_config(config)
        async def execute():
            selection = getattr(config_value, "shared_budget", None)
            usage_selection = getattr(config_value, "service_usage", None)
            async with (
                budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                     confirmed=confirm_budget_code) as bindings,
                service_usage_binding_scope(usage_entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=confirm_usage_code, confirm_record=confirm_usage_recording) as usage_bindings,
            ):
                result = await _probe_configured_provider(
                    config_value, mode=mode, allow_active=confirm_active_probe,
                    **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if usage_entry is not None else {}),
                )
                return (result, await shared_budget_summary(bindings.get(selection.binding) if selection else None),
                        await service_usage_summary(usage_bindings.get(usage_selection.binding) if usage_selection else None))

        result, budget, usage = asyncio.run(execute())
    except (LocalRuntimeConfigError, ValueError) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured provider probe failed: {type(error).__name__}")
    payload = _probe_result_payload(result)
    if budget is not None:
        payload["shared_budget"] = budget
    if usage is not None:
        payload["service_usage"] = usage
    _emit(payload, json_output)
    if not result.successful:
        raise typer.Exit(2)


@app.command("run")
def run_command(
    usage_entry: str | None = typer.Option(None, "--usage-entry", help="Trusted module:factory usage-ledger catalog."),
    confirm_usage_code: bool = typer.Option(False, "--confirm-usage-code"),
    confirm_usage_recording: bool = typer.Option(False, "--confirm-usage-recording"),
    prompt: str | None = typer.Argument(None, help="User text; mutually exclusive with --input-file."),
    knowledge_entry: str | None = typer.Option(None, "--knowledge-entry", help="Trusted module:factory returning an async knowledge-binding catalog context manager."),
    knowledge_query: str | None = typer.Option(None, "--knowledge-query", help="Explicit knowledge query; never inferred from prompt or history."),
    confirm_knowledge_code: bool = typer.Option(False, "--confirm-knowledge-code", help="Authorize unsandboxed knowledge host setup/cleanup code."),
    confirm_knowledge_query: bool = typer.Option(False, "--confirm-knowledge-query", help="Authorize retrieval/query embedding and sending retrieved text to the model."),
    budget_entry: str | None = typer.Option(None, "--budget-entry", help="Trusted module:factory returning an async budget-catalog context manager."),
    confirm_budget_code: bool = typer.Option(False, "--confirm-budget-code", help="Authorize unsandboxed host budget setup and cleanup code."),
    input_file: Path | None = typer.Option(None, "--input-file", help="Strict user-message JSON; never follows file references."),
    input_message_fields: bool = typer.Option(False, "--input-message-fields", help="Explicitly allow input-file name/metadata to be sent to the configured model."),
    record_inputs: bool = typer.Option(False, "--record-inputs", help="Also persist current input blocks in the Session."),
    record_input_name: bool = typer.Option(False, "--record-input-name", help="Also record input names; requires --input-message-fields and confirmed --record-inputs."),
    record_input_metadata: bool = typer.Option(False, "--record-input-metadata", help="Also record input metadata; requires --input-message-fields and confirmed --record-inputs."),
    confirm_input_recording: bool = typer.Option(False, "--confirm-input-recording"),
    history: str = typer.Option("text", "--history", help="text (default), recorded, none, retrieved, or summarized."),
    confirm_history_media: bool = typer.Option(False, "--confirm-history-media", help="Authorize resending recorded history blocks to the configured model."),
    history_name: bool = typer.Option(False, "--history-name", help="Explicitly reuse recorded input names; requires recorded history and its confirmation."),
    history_metadata: bool = typer.Option(False, "--history-metadata", help="Explicitly reuse recorded input metadata; independent of display and recording."),
    confirm_history_transform: bool = typer.Option(False, "--confirm-history-transform", help="Accept lossy text-history selection or summarization; does not authorize media reuse."),
    history_query: str | None = typer.Option(None, "--history-query", help="Explicit retrieval query, never inferred from the prompt or media file."),
    history_recent_turns: int | None = typer.Option(None, "--history-recent-turns", help="Recent Run segments to preserve for retrieved/summarized modes; default 2."),
    history_retrieved_turns: int | None = typer.Option(None, "--history-retrieved-turns", help="Maximum older retrieved segments; default 4."),
    history_summary_chars: int | None = typer.Option(None, "--history-summary-chars", help="Extractive summary character limit; default 4096."),
    history_max_bytes: int | None = typer.Option(None, "--history-max-bytes", help="Transformed history UTF-8 byte limit; default 65536, not a token budget."),
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
    """Run text or structured user messages with explicit recording/history choices."""

    _usage_options(usage_entry, confirm_usage_code, confirm_usage_recording)
    try:
        knowledge_options = KnowledgeRunOptions(knowledge_entry, knowledge_query, confirm_knowledge_code,
                                                confirm_knowledge_query)
    except ValueError as error:
        _fail(str(error))
    if budget_entry is not None and not confirm_budget_code:
        _fail("budget code not authorized; pass --confirm-budget-code")
    if not confirm_model_call:
        _fail("model call not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    if record_inputs and not confirm_input_recording:
        _fail("input recording not authorized; pass --confirm-input-recording")
    if history == "recorded" and not confirm_history_media:
        _fail("recorded history not authorized; pass --confirm-history-media")
    if history in {"retrieved", "summarized"} and not confirm_history_transform:
        _fail("history transformation not authorized; pass --confirm-history-transform")
    if (prompt is None) == (input_file is None) or prompt == "":
        _fail("provide exactly one nonempty prompt or --input-file")
    if input_message_fields and input_file is None:
        _fail("--input-message-fields requires --input-file")
    if (record_input_name or record_input_metadata) and (not record_inputs or not input_message_fields):
        _fail("field recording requires --record-inputs and --input-message-fields")
    try:
        try:
            history_options = BuiltinSessionHistoryOptions(
                mode=history, query=history_query, recent_turns=history_recent_turns,
                retrieved_turns=history_retrieved_turns, summary_chars=history_summary_chars,
                max_output_bytes=history_max_bytes,
                include_name=history_name, include_metadata=history_metadata,
            )
        except ValueError as error:
            raise ValueError(f"invalid --history options: {error}") from None
        input_recorder = (MessageFieldsSessionInputRecorder(
            include_name=record_input_name, include_metadata=record_input_metadata,
        ) if record_input_name or record_input_metadata else None)
        messages = (load_input_manifest(input_file, **({"allow_message_fields": True} if input_message_fields else {}))
                    if input_file is not None else None)
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        runtime_config = load_local_runtime_config(config)

        async def execute():
            selection = getattr(runtime_config, "shared_budget", None)
            usage_selection = getattr(runtime_config, "service_usage", None)
            knowledge_selection = getattr(runtime_config, "knowledge", None)
            async with (
                budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                     confirmed=confirm_budget_code) as bindings,
                knowledge_binding_scope(knowledge_options, selected=knowledge_selection.binding if knowledge_selection else None) as knowledge_bindings,
                service_usage_binding_scope(usage_entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=confirm_usage_code, confirm_record=confirm_usage_recording) as usage_bindings,
            ):
                runtime = open_local_runtime(
                    runtime_config, state_root, tool_bindings=catalog,
                    **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if usage_entry is not None else {}),
                    **({"knowledge_bindings": knowledge_bindings} if knowledge_entry is not None else {}),
                )
                run = await _run_configured_runtime(
                    runtime, prompt, session_id=session_id, session_title=session_title,
                    permissions=frozenset(grant_permission), messages=messages,
                    record_inputs=record_inputs, history=history, history_options=history_options,
                    input_recorder=input_recorder,
                    knowledge_options=knowledge_options,
                )
                return (run, await shared_budget_summary(getattr(runtime, "shared_budget", None)),
                        await service_usage_summary(usage_bindings.get(usage_selection.binding) if usage_selection else None))

        run, budget, usage = asyncio.run(execute())
    except (
        LocalRuntimeConfigError,
        SessionError,
        ToolEntryLoadError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"configured run failed: {type(error).__name__}")
    payload = _local_run_payload(run)
    if budget is not None:
        payload["shared_budget"] = budget
    if usage is not None:
        payload["service_usage"] = usage
    _emit(payload, json_output)


@app.command("run-resume")
def run_resume_command(
    usage_entry: str | None = typer.Option(None, "--usage-entry", help="Trusted module:factory usage-ledger catalog."),
    confirm_usage_code: bool = typer.Option(False, "--confirm-usage-code"),
    confirm_usage_recording: bool = typer.Option(False, "--confirm-usage-recording"),
    session_id: str = typer.Argument(..., help="Session owning the checkpoint."),
    run_id: str = typer.Argument(..., help="Run/checkpoint ID to resume."),
    budget_entry: str | None = typer.Option(None, "--budget-entry", help="Trusted module:factory returning an async budget-catalog context manager."),
    confirm_budget_code: bool = typer.Option(False, "--confirm-budget-code", help="Authorize unsandboxed host budget setup and cleanup code."),
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

    _usage_options(usage_entry, confirm_usage_code, confirm_usage_recording)
    if budget_entry is not None and not confirm_budget_code:
        _fail("budget code not authorized; pass --confirm-budget-code")
    if not confirm_model_call:
        _fail("model call not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    if not approve_tool_call:
        _fail("no tool call approved; pass --approve-tool-call")
    try:
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        runtime_config = load_local_runtime_config(config)

        async def execute():
            selection = getattr(runtime_config, "shared_budget", None)
            usage_selection = getattr(runtime_config, "service_usage", None)
            async with (
                budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                     confirmed=confirm_budget_code) as bindings,
                service_usage_binding_scope(usage_entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=confirm_usage_code, confirm_record=confirm_usage_recording) as usage_bindings,
            ):
                runtime = open_local_runtime(
                    runtime_config, state_root, tool_bindings=catalog,
                    **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if usage_entry is not None else {}),
                )
                run = await _resume_configured_runtime(
                    runtime, session_id, run_id, permissions=frozenset(grant_permission),
                    approved_call_ids=frozenset(approve_tool_call),
                )
                return (run, await shared_budget_summary(getattr(runtime, "shared_budget", None)),
                        await service_usage_summary(usage_bindings.get(usage_selection.binding) if usage_selection else None))

        run, budget, usage = asyncio.run(execute())
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
    payload = _local_run_payload(run)
    if budget is not None:
        payload["shared_budget"] = budget
    if usage is not None:
        payload["service_usage"] = usage
    _emit(payload, json_output)


@app.command("evaluate")
def evaluate_command(
    usage_entry: str | None = typer.Option(None, "--usage-entry", help="Trusted usage catalog for the entire evaluation."),
    confirm_usage_code: bool = typer.Option(False, "--confirm-usage-code"),
    confirm_usage_recording: bool = typer.Option(False, "--confirm-usage-recording"),
    dataset: Path = typer.Argument(
        ...,
        help="Strict local JSON dataset or builtin:<name>[@version].",
    ),
    config: Path = typer.Option(Path(".wagent/config.json"), "--config"),
    budget_entry: str | None = typer.Option(None, "--budget-entry", help="One trusted module:factory budget context for the entire evaluation."),
    confirm_budget_code: bool = typer.Option(False, "--confirm-budget-code", help="Authorize unsandboxed host budget setup and cleanup code."),
    knowledge_entry: str | None = typer.Option(None, "--knowledge-entry", help="One trusted module:factory knowledge catalog for all cases."),
    confirm_knowledge_code: bool = typer.Option(False, "--confirm-knowledge-code"),
    confirm_knowledge_queries: bool = typer.Option(False, "--confirm-knowledge-queries", help="Authorize retrieval and sending evidence for every dataset prompt."),
    scorer: list[str] = typer.Option(
        [],
        "--scorer",
        help=(
            "exact-text, contains-text, case-contract, or none; may repeat. "
            "Omitted uses dataset recommendations."
        ),
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

    _usage_options(usage_entry, confirm_usage_code, confirm_usage_recording)
    if budget_entry is not None and not confirm_budget_code:
        _fail("budget code not authorized; pass --confirm-budget-code")
    if not confirm_model_call:
        _fail("model calls not authorized; pass --confirm-model-call")
    if tool_entry and not confirm_tool_code:
        _fail("tool code not authorized; pass --confirm-tool-code")
    try:
        knowledge_options = KnowledgeEvaluationOptions(knowledge_entry, confirm_knowledge_code, confirm_knowledge_queries)
        evaluation_dataset = load_evaluation_dataset(dataset)
        cases = evaluation_dataset.cases
        knowledge_options.validate_queries(tuple(case.prompt for case in cases))
        scorer_names = scorer or list(evaluation_dataset.scorers)
        scorers = _evaluation_scorers(scorer_names, case_sensitive=case_sensitive)
        catalog = load_tool_entries(tool_entry) if tool_entry else {}
        config_value = load_local_runtime_config(config)
        root_context = (
            TemporaryDirectory(prefix="wagent-eval-")
            if state_root is None
            else nullcontext(state_root)
        )
        with root_context as evaluation_root:
            async def execute():
                selection = getattr(config_value, "shared_budget", None)
                usage_selection = getattr(config_value, "service_usage", None)
                knowledge_selection = getattr(config_value, "knowledge", None)
                async with (
                    budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                         confirmed=confirm_budget_code) as bindings,
                    knowledge_binding_scope(knowledge_options, selected=knowledge_selection.binding if knowledge_selection else None) as knowledge_bindings,
                    service_usage_binding_scope(usage_entry, selected=usage_selection.binding if usage_selection else None,
                                                confirmed=confirm_usage_code, confirm_record=confirm_usage_recording) as usage_bindings,
                ):
                    runtime = open_local_runtime(
                        config_value, evaluation_root, tool_bindings=catalog,
                        **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                        **({"service_usage_bindings": usage_bindings} if usage_entry is not None else {}),
                        **({"knowledge_bindings": knowledge_bindings} if knowledge_entry is not None else {}),
                    )
                    report = await _run_local_evaluation(
                        runtime, cases, scorers, permissions=frozenset(grant_permission),
                        knowledge_options=knowledge_options,
                    )
                    return (report, await shared_budget_summary(getattr(runtime, "shared_budget", None)),
                            await service_usage_summary(usage_bindings.get(usage_selection.binding) if usage_selection else None))

            report, budget, usage = asyncio.run(execute())
        if report_path is not None:
            asyncio.run(
                JsonEvaluationReporter(
                    include_outputs=include_outputs,
                    **({"accounting_scope": "model-runs-only; retrieval-not-included"} if knowledge_entry is not None else {}),
                ).write(
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
    if knowledge_entry is not None:
        payload["knowledge"] = {"query_source": "each-case-prompt", "accounting_scope": "model-runs-only; retrieval-not-included"}
        payload["accounting_scope"] = "model-runs-only; retrieval-not-included"
    if budget is not None:
        payload["shared_budget"] = budget
    if usage is not None:
        payload["service_usage"] = usage
    _emit_evaluation(payload, json_output=json_output)
    if report.passed != report.total:
        raise typer.Exit(1)


@benchmark_app.command("list")
def benchmark_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List versioned built-in suites without running models or tools."""

    payload = [
        {
            "key": suite.key,
            "version": suite.version,
            "reference": suite.reference,
            "description": suite.description,
            "agent_template": suite.agent_template,
            "cases": len(suite.cases),
            "scorers": list(suite.scorers),
        }
        for suite in builtin_evaluation_suite_registry().list()
    ]
    _emit(payload, json_output)


@benchmark_app.command("export")
def benchmark_export(
    reference: str = typer.Argument(..., help="Suite name or name@version."),
    destination: Path = typer.Argument(..., help="Destination JSON file."),
    force: bool = typer.Option(False, "--force", help="Replace an existing file."),
) -> None:
    """Export a built-in suite to the ordinary strict JSON dataset format."""

    try:
        suite = builtin_evaluation_suite_registry().resolve_reference(reference)
        target = destination.resolve()
        if target.exists() and not force:
            raise ValueError("destination exists; pass --force to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                evaluation_suite_to_dict(suite),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        _fail(str(error))
    console.print(str(target), markup=False)


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


@plugin_app.command("inspect")
def plugin_inspect(
    config: Path = typer.Option(Path(".wagent/plugins.yml"), "--config"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Preview plugin references and config keys without importing code."""

    try:
        summaries = preview_plugin_references(load_yaml_references(config))
    except (OSError, ValueError) as error:
        _fail(str(error))
    payload = [
        {
            "entry": item.entry,
            "enabled": item.enabled,
            "config_keys": list(item.config_keys),
        }
        for item in summaries
    ]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Plugin reference preview (no imports)")
    table.add_column("Entry")
    table.add_column("Enabled")
    table.add_column("Config keys")
    for item in payload:
        table.add_row(
            str(item["entry"]),
            str(item["enabled"]),
            ", ".join(item["config_keys"]) or "-",
        )
    console.print(table)


@plugin_app.command("validate-load")
def plugin_validate_load(
    config: Path = typer.Option(Path(".wagent/plugins.yml"), "--config"),
    confirm_plugin_code: bool = typer.Option(
        False,
        "--confirm-plugin-code",
        help="Authorize importing and executing developer-owned plugin code.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Load a plugin batch transactionally, report it, then unload on exit."""

    if not confirm_plugin_code:
        _fail("plugin code not authorized; pass --confirm-plugin-code")
    try:
        references = load_yaml_references(config)
        payload = asyncio.run(_validate_plugin_batch(references))
    except (OSError, PluginLoadError, ValueError) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"plugin validation failed: {type(error).__name__}")
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Validated plugins (unloaded after validation)")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("API")
    table.add_column("State during validation")
    table.add_column("Capabilities")
    for item in payload:
        table.add_row(
            str(item["name"]),
            str(item["version"]),
            str(item["api_version"]),
            str(item["state"]),
            ", ".join(
                capability["capability"] for capability in item["provides"]
            )
            or "-",
        )
    console.print(table)


@plugin_app.command("session")
def plugin_session(
    config: Path = typer.Option(Path(".wagent/plugins.yml"), "--config"),
    confirm_plugin_code: bool = typer.Option(
        False, "--confirm-plugin-code",
        help="Authorize initial trusted Python imports/setup in this process (not sandboxed).",
    ),
) -> None:
    """Open a local plugin session; review/replace here, unload on exit."""
    if not confirm_plugin_code:
        _fail("plugin code not authorized; pass --confirm-plugin-code")
    from w_agent.plugin_session_cli import run_plugin_session

    try:
        asyncio.run(run_plugin_session(config))
    except Exception as error:
        _fail(f"plugin session failed: {type(error).__name__}")


@plugin_app.command("validate-installed")
def plugin_validate_installed(
    install_path: Path = typer.Argument(..., exists=True, file_okay=False),
    confirm_plugin_code: bool = typer.Option(
        False,
        "--confirm-plugin-code",
        help="Authorize importing and executing the verified installed plugin.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Verify, load, report, and unload one installed plugin site."""

    if not confirm_plugin_code:
        _fail("plugin code not authorized; pass --confirm-plugin-code")
    try:
        installation = load_plugin_install_result(install_path)
        payload = asyncio.run(_validate_installed_plugin(installation))
    except (
        CompositionError,
        OSError,
        PluginInstallationError,
        PluginLoadError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"installed plugin validation failed: {type(error).__name__}")
    _emit(payload, json_output)


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


@app.command("run-events")
def run_events(
    run_id: str = typer.Argument(..., help="Exact local run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    after_sequence: int = typer.Option(0, "--after-sequence"),
    limit: int = typer.Option(100, "--limit"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Read a privacy-safe page of persisted events without executing a run."""

    try:
        if limit > 500:
            raise ValueError("run event CLI limit must not exceed 500")
        if not (state_root / "runs").is_dir():
            raise RunStoreError("local run event store does not exist")
        page = asyncio.run(
            RunEventReplay(JsonlRunStore(state_root)).projected_page(
                run_id,
                cursor=RunEventCursor(run_id, after_sequence),
                limit=limit,
            )
        )
    except (OSError, RunStoreError, ValueError) as error:
        _fail(str(error))
    payload = {
        "run_id": page.cursor.run_id,
        "after_sequence": page.cursor.sequence,
        "next_sequence": page.next_cursor.sequence,
        "has_more": page.has_more,
        "events": list(page.events),
    }
    if json_output:
        _emit(payload, True)
        return
    console.print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        markup=False,
    )


@app.command("run-view")
def run_view_command(
    run_id: str = typer.Argument(..., help="Exact local Run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    snapshot: Path | None = typer.Option(None, "--snapshot", help="Complete previous view JSON; trusted cache only."),
    limit: int = typer.Option(100, "--limit", help="Events in this page, 1 to 500."),
    include_text: bool = typer.Option(False, "--include-text"),
    include_tools: bool = typer.Option(False, "--include-tools", help="Expose tool identities and arguments."),
    include_tool_results: bool = typer.Option(False, "--include-tool-results"),
    media: str = typer.Option("metadata", "--media", help="metadata, references, or content; never fetched."),
    confirm_sensitive: bool = typer.Option(False, "--confirm-sensitive-content"),
    trust_snapshot: bool = typer.Option(False, "--trust-snapshot"),
) -> None:
    """Print one accumulated read-only Run view as JSON; never execute or write a cache."""
    options = ViewOptions(include_text=include_text, include_tools=include_tools,
                          include_tool_results=include_tool_results, media=media,
                          confirm_sensitive=confirm_sensitive, trust_snapshot=trust_snapshot)
    try:
        output = asyncio.run(run_view(run_id, state_root, options=options, snapshot=snapshot, limit=limit))
    except ReplayViewError as error:
        _fail(str(error))
    typer.echo(output)


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
    enable_pause_control: bool = typer.Option(
        False,
        "--enable-pause-control",
        help="Observe local SQLite pause requests at committed node boundaries.",
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
                enable_pause_control=enable_pause_control,
            )
        )
    except (
        OSError,
        WorkflowEntryLoadError,
        WorkflowStoreError,
        WorkflowPauseControlError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"workflow resume failed: {type(error).__name__}")
    _emit(_workflow_result_payload(result), json_output)


@checkpoint_app.command("workflow-pause")
def workflow_pause_request(
    run_id: str = typer.Argument(..., help="Exact workflow run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    confirm_pause: bool = typer.Option(False, "--confirm-pause"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Request a boundary pause; this does not prove a worker is running."""

    if not confirm_pause:
        _fail("workflow pause not authorized; pass --confirm-pause")
    try:
        checkpoint = asyncio.run(JsonlWorkflowStore(state_root).load_checkpoint(run_id))
        if checkpoint is None:
            _fail("workflow run has no checkpoint; pause request was not written")
        SQLiteWorkflowPauseController(state_root).request_pause(run_id)
    except (OSError, ValueError, WorkflowStoreError, WorkflowPauseControlError) as error:
        _fail(str(error))
    _emit(
        {"run_id": run_id, "request_recorded": True, "execution_acknowledged": False},
        json_output,
    )


@checkpoint_app.command("workflow-pause-status")
def workflow_pause_status(
    run_id: str = typer.Argument(..., help="Exact workflow run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read request/checkpoint snapshots, not process liveness or an ACK."""

    try:
        requested = SQLiteWorkflowPauseController(state_root).is_pause_requested(run_id)
        checkpoint = asyncio.run(JsonlWorkflowStore(state_root).load_checkpoint(run_id))
    except (OSError, ValueError, WorkflowStoreError, WorkflowPauseControlError) as error:
        _fail(str(error))
    _emit(
        {
            "run_id": run_id,
            "pause_requested": requested,
            "checkpoint_status": checkpoint.status.value if checkpoint else None,
        },
        json_output,
    )


@checkpoint_app.command("workflow-pause-clear")
def workflow_pause_clear(
    run_id: str = typer.Argument(..., help="Exact workflow run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    confirm_clear: bool = typer.Option(False, "--confirm-clear"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Clear one request without resuming a workflow or changing checkpoints."""

    if not confirm_clear:
        _fail("workflow pause clear not authorized; pass --confirm-clear")
    try:
        SQLiteWorkflowPauseController(state_root).clear(run_id)
    except (OSError, ValueError, WorkflowPauseControlError) as error:
        _fail(str(error))
    _emit({"run_id": run_id, "request_cleared": True, "resumed": False}, json_output)


@checkpoint_app.command("workflow-approvals")
def workflow_approval_review(
    run_id: str = typer.Argument(..., help="Exact parent workflow run ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    agent_state_root: Path | None = typer.Option(None, "--agent-state-root"),
    state_key: list[str] = typer.Option(
        [], "--state-key", help="Explicit custom approval state key; may repeat.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Review linked approval identities/status only; never grant or execute."""

    try:
        selected_agent_root = agent_state_root if agent_state_root is not None else state_root
        # Store constructors create directories; refuse absent roots first so
        # a read-only query does not initialize a workspace by accident.
        if not (state_root / "workflows").is_dir():
            _fail("workflow state directory does not exist")
        if not (selected_agent_root / "runs").is_dir():
            _fail("Agent state directory does not exist; select --agent-state-root")
        reviews = asyncio.run(review_workflow_approvals(
            JsonlWorkflowStore(state_root), JsonlRunStore(selected_agent_root), run_id,
            state_keys=tuple(state_key) if state_key else None,
        ))
    except (OSError, ValueError, WorkflowStoreError, RunStoreError, AgentWorkflowAdapterError) as error:
        _fail(f"workflow approval review failed: {type(error).__name__}")
    _emit([item.to_dict() for item in reviews], json_output)


@checkpoint_app.command("workflow-approve-resume")
def workflow_approval_resume(
    run_id: str = typer.Argument(..., help="Exact parent workflow run ID."),
    workflow_factory: str = typer.Option(..., "--workflow-factory"),
    node: str = typer.Option(..., "--node"),
    agent_run: str = typer.Option(..., "--agent-run"),
    agent_name: str = typer.Option(..., "--agent-name"),
    approve_tool_call: str = typer.Option(..., "--approve-tool-call"),
    tool_name: str = typer.Option(..., "--tool-name"),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    agent_state_root: Path | None = typer.Option(None, "--agent-state-root"),
    state_key: list[str] = typer.Option([], "--state-key"),
    grant_permission: list[str] = typer.Option([], "--grant-permission"),
    confirm_workflow_code: bool = typer.Option(False, "--confirm-workflow-code"),
    confirm_approval: bool = typer.Option(False, "--confirm-approval"),
    confirm_resume: bool = typer.Option(False, "--confirm-resume"),
    enable_pause_control: bool = typer.Option(False, "--enable-pause-control"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Approve one reviewed linked call and resume the parent via a trusted factory.

    Recovery may run subsequent workflow nodes and billable model calls. The
    factory must return an async context manager and use the supplied stores and
    grants. Inspect the actual tool action before confirming its identifiers.
    """

    if not confirm_workflow_code:
        _fail("workflow code not authorized; pass --confirm-workflow-code")
    if not confirm_approval:
        _fail("exact call approval not authorized; pass --confirm-approval")
    if not confirm_resume:
        _fail("parent execution not authorized; pass --confirm-resume")
    selected_agent_root = agent_state_root if agent_state_root is not None else state_root
    if not (state_root / "workflows").is_dir():
        _fail("workflow state directory does not exist")
    if not (selected_agent_root / "runs").is_dir():
        _fail("Agent state directory does not exist; select --agent-state-root")
    try:
        reference = AgentWorkflowApproval(
            run_id, node, agent_run, agent_name, approve_tool_call, tool_name,
        )
        result = asyncio.run(resume_workflow_approval(
            JsonlWorkflowStore(state_root), JsonlRunStore(selected_agent_root), reference,
            lambda context: open_workflow_approval_entry(workflow_factory, context),
            permissions=frozenset(grant_permission),
            state_keys=tuple(state_key) if state_key else None,
            pause_source=SQLiteWorkflowPauseController(state_root) if enable_pause_control else None,
        ))
    except Exception as error:
        # Imported developer code and custom stores can put private data in errors.
        _fail(f"workflow approval resume failed: {type(error).__name__}")
    _emit(_workflow_result_payload(result), json_output)


def _workflow_tool_stores(
    state_root: Path, workflow_state_root: Path | None, child_state_root: Path | None,
) -> tuple[JsonlRunStore, JsonlWorkflowStore, JsonlRunStore]:
    workflow_root = workflow_state_root if workflow_state_root is not None else state_root
    child_root = child_state_root if child_state_root is not None else state_root
    # Validate all roots before any constructor can initialize a directory.
    for directory, label in (
        (state_root / "runs", "parent Agent"),
        (workflow_root / "workflows", "Workflow"),
        (child_root / "runs", "child Agent"),
    ):
        if not directory.is_dir():
            _fail(f"{label} state directory does not exist")
    try:
        return JsonlRunStore(state_root), JsonlWorkflowStore(workflow_root), JsonlRunStore(child_root)
    except (OSError, ValueError) as error:
        _fail(f"approval state stores unavailable: {type(error).__name__}")


@checkpoint_app.command("workflow-tool-approvals")
def workflow_tool_approval_review(
    run_id: str = typer.Argument(..., help="Exact outer Agent run ID, not the middle Workflow ID."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    workflow_state_root: Path | None = typer.Option(None, "--workflow-state-root"),
    child_state_root: Path | None = typer.Option(None, "--child-state-root"),
    state_key: list[str] = typer.Option([], "--state-key"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect Agent -> Workflow -> Agent approval links without loading code."""
    stores = _workflow_tool_stores(state_root, workflow_state_root, child_state_root)
    try:
        reviews = asyncio.run(review_workflow_tool_approvals(
            *stores, run_id, state_keys=tuple(state_key) if state_key else None,
        ))
    except Exception as error:
        _fail(f"workflow tool approval review failed: {type(error).__name__}")
    _emit([item.to_dict() for item in reviews], json_output)


@checkpoint_app.command("workflow-tool-approve-resume")
def workflow_tool_approval_resume(
    run_id: str = typer.Argument(..., help="Exact outer Agent run ID."),
    agent_factory: str = typer.Option(..., "--agent-factory", help="Trusted module:attribute async parent-loop factory."),
    parent_call: str = typer.Option(..., "--parent-call"),
    parent_tool: str = typer.Option(..., "--parent-tool"),
    workflow_run: str = typer.Option(..., "--workflow-run"),
    workflow_name: str = typer.Option(..., "--workflow-name"),
    workflow_version: str = typer.Option(..., "--workflow-version"),
    workflow_kind: WorkflowKind = typer.Option(..., "--workflow-kind"),
    sequence: int = typer.Option(..., "--sequence", min=1, help="Workflow event sequence from the reviewed boundary."),
    node: str = typer.Option(..., "--node"),
    child_run: str = typer.Option(..., "--child-run"),
    child_agent: str = typer.Option(..., "--child-agent"),
    child_call: str = typer.Option(..., "--child-call"),
    child_tool: str = typer.Option(..., "--child-tool"),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    workflow_state_root: Path | None = typer.Option(None, "--workflow-state-root"),
    child_state_root: Path | None = typer.Option(None, "--child-state-root"),
    state_key: list[str] = typer.Option([], "--state-key"),
    parent_permission: list[str] = typer.Option([], "--parent-permission"),
    child_permission: list[str] = typer.Option([], "--child-permission"),
    confirm_agent_code: bool = typer.Option(False, "--confirm-agent-code"),
    confirm_parent_approval: bool = typer.Option(False, "--confirm-parent-approval"),
    confirm_child_approval: bool = typer.Option(False, "--confirm-child-approval"),
    confirm_resume: bool = typer.Option(False, "--confirm-resume"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Approve two exact calls and resume the outer Agent via its owned chain.

    All identities and the event boundary must match a fresh review. Continuing
    may execute later nodes/tools and billable model calls. The factory owns
    clients and explicitly configures execution/pause policies; this is not a
    sandbox or a shortcut to independently resuming the middle Workflow.
    """
    for confirmed, option in (
        (confirm_agent_code, "--confirm-agent-code"),
        (confirm_parent_approval, "--confirm-parent-approval"),
        (confirm_child_approval, "--confirm-child-approval"),
        (confirm_resume, "--confirm-resume"),
    ):
        if not confirmed:
            _fail(f"two-layer recovery not authorized; pass {option}")
    stores = _workflow_tool_stores(state_root, workflow_state_root, child_state_root)
    keys = tuple(state_key) if state_key else None

    async def recover() -> RunResult:
        reviews = await review_workflow_tool_approvals(*stores, run_id, state_keys=keys)
        inner = AgentWorkflowApproval(workflow_run, node, child_run, child_agent, child_call, child_tool)
        selected = [item for item in reviews if (
            item.parent.agent_run_id == run_id
            and item.parent.call_id == parent_call and item.parent.tool_name == parent_tool
            and item.parent.workflow_run_id == workflow_run
            and item.parent.workflow_name == workflow_name
            and item.parent.workflow_version == workflow_version
            and item.parent.workflow_kind == workflow_kind
            and item.sequence == sequence and item.child.reference == inner
            and item.child.link_status is WorkflowApprovalLinkStatus.MATCHED
        )]
        if len(selected) != 1:
            raise WorkflowToolApprovalError("selected chain is absent, stale, or not pending")
        return await resume_workflow_tool_approval(
            *stores, selected[0],
            lambda context: open_workflow_tool_approval_entry(agent_factory, context),
            parent_permissions=frozenset(parent_permission),
            child_permissions=frozenset(child_permission), state_keys=keys,
        )

    try:
        result = asyncio.run(recover())
    except Exception as error:
        _fail(f"workflow tool approval resume failed: {type(error).__name__}")
    _emit(_approval_run_result_payload(result), json_output)


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


@composition_app.command("plan")
def composition_plan(
    code: str = typer.Argument(...),
    inventory: Path | None = typer.Option(
        None,
        "--inventory",
        help="Optional explicit plugin-candidate JSON inventory.",
    ),
    python_version: str | None = typer.Option(None, "--python-version"),
    wagent_version: str | None = typer.Option(None, "--wagent-version"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Build an offline dependency plan without imports or installation."""

    try:
        preview = inspect_composition(code)
        candidates = load_plugin_candidates(inventory) if inventory else ()
        plan = plan_composition(
            preview.manifest,
            CompositionEnvironment(
                python_version or platform.python_version(),
                wagent_version or get_version(),
            ),
            StaticCompositionDependencyResolver(candidates),
        )
    except (CompositionError, OSError, ValueError) as error:
        _fail(str(error))
    payload = composition_plan_to_dict(plan)
    if json_output:
        _emit(payload, True)
        return
    console.print(
        f"Composition: {plan.name}@{plan.version}\n"
        f"Digest: {plan.digest}\n"
        f"Python {plan.environment.python_version}: {plan.python_compatible}\n"
        f"W-Agent {plan.environment.wagent_version}: {plan.wagent_compatible}\n"
        f"Ready: {plan.ready}\n"
        f"Plugin load confirmation required: {plan.load_confirmation_required}",
        markup=False,
    )
    table = Table(title="Offline plugin dependency plan")
    table.add_column("Plugin")
    table.add_column("Constraint")
    table.add_column("Source")
    table.add_column("Action")
    table.add_column("Selected")
    for item in plan.plugins:
        table.add_row(
            item.requirement.name,
            item.requirement.version or "*",
            item.requirement.source or "-",
            item.action.value,
            (
                f"{item.candidate.version} ({item.candidate.entry or '-'})"
                if item.candidate is not None
                else "-"
            ),
        )
    console.print(table)


@composition_app.command("install-plan")
def composition_install_plan(
    code: str = typer.Argument(...),
    catalog: Path = typer.Option(
        ...,
        "--catalog",
        exists=True,
        dir_okay=False,
        help="Explicit locked plugin-package catalog.",
    ),
    inventory: Path | None = typer.Option(
        None,
        "--inventory",
        exists=True,
        dir_okay=False,
        help="Optional installed-plugin inventory.",
    ),
    python_version: str | None = typer.Option(None, "--python-version"),
    wagent_version: str | None = typer.Option(None, "--wagent-version"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Create a locked package-install plan without network or imports."""

    try:
        install_plan = _build_plugin_install_plan(
            code,
            catalog,
            inventory,
            python_version=python_version,
            wagent_version=wagent_version,
        )
    except (CompositionError, OSError, ValueError) as error:
        _fail(str(error))
    payload = plugin_installation_plan_to_dict(install_plan)
    if json_output:
        _emit(payload, True)
        return
    console.print(
        f"Composition digest: {install_plan.composition_digest}\n"
        f"Installable: {install_plan.installable}\n"
        "No network was accessed and no package or plugin code was executed.",
        markup=False,
    )
    table = Table(title="Locked plugin package requests")
    table.add_column("Plugin")
    table.add_column("Version")
    table.add_column("Source")
    table.add_column("Index origin")
    table.add_column("Request digest")
    table.add_column("Packages")
    for request in install_plan.requests:
        table.add_row(
            request.lock.name,
            request.lock.version,
            request.lock.source,
            request.index.origin,
            request.digest,
            ", ".join(
                f"{item.name}=={item.version}" for item in request.lock.packages
            ),
        )
    console.print(table)
    if install_plan.blockers:
        blocker_table = Table(title="Installation blockers")
        blocker_table.add_column("Plugin")
        blocker_table.add_column("Reason")
        for blocker in install_plan.blockers:
            blocker_table.add_row(blocker.plugin_name or "environment", blocker.reason)
        console.print(blocker_table)


@composition_app.command("install")
def composition_install(
    code: str = typer.Argument(...),
    request_digest: str = typer.Argument(
        ...,
        help="Exact request digest shown by composition install-plan.",
    ),
    catalog: Path = typer.Option(
        ...,
        "--catalog",
        exists=True,
        dir_okay=False,
    ),
    inventory: Path | None = typer.Option(
        None,
        "--inventory",
        exists=True,
        dir_okay=False,
    ),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root"),
    backend: str = typer.Option("docker", "--backend", help="docker or unsafe-local"),
    docker_image: str = typer.Option("python:3.11-slim", "--docker-image"),
    confirm_network: bool = typer.Option(False, "--confirm-network"),
    confirm_package_code: bool = typer.Option(False, "--confirm-package-code"),
    confirm_unsafe_local: bool = typer.Option(False, "--confirm-unsafe-local"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Install one exact locked request through an explicitly selected sandbox."""

    try:
        install_plan = _build_plugin_install_plan(code, catalog, inventory)
        if install_plan.blockers:
            reasons = ", ".join(item.reason for item in install_plan.blockers)
            raise PluginInstallationError(f"installation plan is blocked: {reasons}")
        matches = [
            item for item in install_plan.requests if item.digest == request_digest
        ]
        if len(matches) != 1:
            raise PluginInstallationError(
                "request digest is absent or ambiguous; run install-plan again"
            )
        request = matches[0]
        authorization = PluginInstallAuthorization.grant(
            request.digest,
            "cli",
            acknowledge_network_access=confirm_network,
            acknowledge_package_code=confirm_package_code,
        )
        normalized_backend = backend.strip().lower()
        if normalized_backend not in {"docker", "unsafe-local"}:
            raise ValueError("plugin install backend must be docker or unsafe-local")
        if normalized_backend == "unsafe-local" and not confirm_unsafe_local:
            raise PermissionError(
                "unsafe local install not authorized; pass --confirm-unsafe-local"
            )
        workspace = state_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if normalized_backend == "docker":
            provider = DockerSandboxProvider()
            sandbox = SandboxSpec(
                workspace,
                image=docker_image,
                network=SandboxNetwork.BRIDGE,
                user=recommended_docker_install_user(),
            )
            python_executable = "python"
        elif normalized_backend == "unsafe-local":
            local_authorization = UnsafeLocalAuthorization.grant(
                "plugin-install-cli",
                acknowledge_host_access=True,
            )
            provider = UnsafeLocalSandboxProvider(local_authorization)
            sandbox = SandboxSpec(
                workspace,
                network=SandboxNetwork.BRIDGE,
                inherit_host_environment=True,
            )
            python_executable = sys.executable
        result = asyncio.run(
            SandboxPipPackageInstaller(
                provider,
                sandbox,
                python_executable=python_executable,
            ).install(request, authorization)
        )
    except (
        CompositionError,
        OSError,
        PermissionError,
        PluginInstallationError,
        ValueError,
    ) as error:
        _fail(str(error))
    except Exception as error:
        _fail(f"plugin package installation failed: {type(error).__name__}")
    _emit(
        {
            "request_digest": result.request_digest,
            "composition_digest": result.composition_digest,
            "plugin": result.plugin_name,
            "version": result.plugin_version,
            "source": result.source,
            "entry": result.entry,
            "target": str(result.target),
            "tree_digest": result.tree_digest,
            "plugin_load_authorized": False,
        },
        json_output,
    )


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


@session_app.command("view")
def session_view_command(
    session_id: str = typer.Argument(..., help="Exact local Session ID."),
    root: Path = typer.Option(Path(".wagent/sessions"), "--root", help="Existing Session store."),
    state_root: Path = typer.Option(Path(".wagent"), "--state-root", help="Existing Run state root."),
    snapshot: Path | None = typer.Option(None, "--snapshot", help="Complete previous view JSON; trusted cache only."),
    run_offset: int = typer.Option(0, "--run-offset"),
    run_limit: int = typer.Option(10, "--run-limit", help="Registered Runs to read, 1 to 32."),
    event_limit: int = typer.Option(100, "--event-limit", help="Events per selected Run, 1 to 500."),
    include_text: bool = typer.Option(False, "--include-text", help="Expose recorded model text."),
    include_session_text: bool = typer.Option(False, "--include-session-text"),
    input_media: str | None = typer.Option(None, "--input-media", help="Session input blocks: metadata, references, or content; off by default."),
    include_input_name: bool = typer.Option(False, "--include-input-name", help="Expose explicitly recorded input message names; requires sensitive-content consent."),
    include_input_metadata: bool = typer.Option(False, "--include-input-metadata", help="Expose explicitly recorded input message metadata; independent from media and Session text."),
    include_tools: bool = typer.Option(False, "--include-tools", help="Expose tool identities and arguments."),
    include_tool_results: bool = typer.Option(False, "--include-tool-results"),
    media: str = typer.Option("metadata", "--media", help="metadata, references, or content; never fetched."),
    allow_unscoped_events: bool = typer.Option(False, "--allow-unscoped-events", help="Allow legacy events with no Session ID, never a different Session."),
    confirm_sensitive: bool = typer.Option(False, "--confirm-sensitive-content"),
    trust_snapshot: bool = typer.Option(False, "--trust-snapshot"),
) -> None:
    """Print one bounded Session view as JSON; membership offsets do not imply completion."""
    options = ViewOptions(include_text=include_text, include_tools=include_tools,
                          include_tool_results=include_tool_results, media=media,
                          include_session_text=include_session_text,
                          input_media=input_media,
                          include_input_name=include_input_name, include_input_metadata=include_input_metadata,
                          confirm_sensitive=confirm_sensitive, trust_snapshot=trust_snapshot)
    try:
        output = asyncio.run(session_view(
            session_id, state_root, root, options=options, snapshot=snapshot,
            run_offset=run_offset, run_limit=run_limit, event_limit=event_limit,
            allow_unscoped_events=allow_unscoped_events,
        ))
    except ReplayViewError as error:
        _fail(str(error))
    typer.echo(output)


@session_app.command("usage")
def session_usage(
    root: Path = typer.Option(Path(".wagent/sessions"), "--root"),
    agent_name: str | None = typer.Option(
        None,
        "--agent",
        help="Optional exact agent name filter.",
    ),
    include_archived: bool = typer.Option(False, "--include-archived"),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Summarize known usage and cost across local sessions by agent."""

    manager = SessionManager(JsonSessionStore(root))
    try:
        summaries = asyncio.run(
            manager.agent_usage(
                agent_name,
                include_archived=include_archived,
            )
        )
    except ValueError as error:
        _fail(str(error))
    payload = [_agent_usage_payload(item) for item in summaries]
    if json_output:
        _emit(payload, True)
        return
    table = Table(title="Agent usage across local sessions")
    table.add_column("Agent")
    table.add_column("Sessions", justify="right")
    table.add_column("Runs", justify="right")
    table.add_column("Model calls", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Usage complete")
    table.add_column("Cost")
    for item, summary in zip(payload, summaries, strict=True):
        usage = item["usage"]
        assert isinstance(usage, dict)
        table.add_row(
            str(item["agent_name"]),
            str(item["session_count"]),
            str(item["run_count"]),
            str(item["model_calls"]),
            str(usage["total_tokens"]),
            str(item["usage_complete"]),
            _cost_text(summary.cost, complete=summary.cost_complete),
        )
    console.print(table)


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
        "case-contract": CaseContractScorer(case_sensitive=case_sensitive),
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
    knowledge_options: KnowledgeEvaluationOptions | None = None,
) -> EvaluationReport:
    async def target(case: EvaluationCase):
        run = await runtime.run(
            case.prompt,
            session_title=f"Evaluation: {case.name}",
            permissions=permissions,
            **(knowledge_options.runtime_options(case.prompt) if knowledge_options is not None else {}),
        )
        return run.result

    async with runtime:
        return await LocalEvaluationRunner().run(cases, target, scorers=scorers)


async def _run_configured_runtime(
    runtime: Any,
    prompt: str | None,
    *,
    session_id: str | None,
    session_title: str | None,
    permissions: frozenset[str],
    messages: tuple[ModelMessage, ...] | None = None,
    record_inputs: bool = False,
    history: str = "text",
    history_options: BuiltinSessionHistoryOptions | None = None,
    input_recorder: SessionInputRecorder | None = None,
    knowledge_options: KnowledgeRunOptions | None = None,
) -> Any:
    async with runtime:
        options: dict[str, Any] = {"session_id": session_id, "session_title": session_title, "permissions": permissions}
        if record_inputs:
            options["record_inputs"] = True
        if input_recorder is not None:
            options["input_recorder"] = input_recorder
        selection = history_options if history_options is not None else BuiltinSessionHistoryOptions(mode=history)
        options.update(selection.runtime_options())
        if knowledge_options is not None:
            options.update(knowledge_options.runtime_options())
        if messages is not None:
            return await runtime.run_messages(messages, **options)
        return await runtime.run(prompt, **options)


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
    shared_budget_bindings: Mapping[str, Any] | None = None,
    service_usage_bindings: Mapping[str, Any] | None = None,
) -> ProbeResult:
    assembly = assemble_local_provider(
        config, **({"shared_budget_bindings": shared_budget_bindings} if shared_budget_bindings is not None else {}),
        **({"service_usage_bindings": service_usage_bindings} if service_usage_bindings is not None else {}),
    )
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
    *,
    enable_pause_control: bool = False,
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
    pause_source = (
        SQLiteWorkflowPauseController(state_root) if enable_pause_control else None
    )
    async with open_local_workflow(state_root, pause_source=pause_source) as host:
        return await host.invoke("resume", definition, run_id)


def _build_plugin_install_plan(
    code: str,
    catalog_path: Path,
    inventory: Path | None,
    *,
    python_version: str | None = None,
    wagent_version: str | None = None,
) -> PluginInstallationPlan:
    preview = inspect_composition(code)
    candidates = load_plugin_candidates(inventory) if inventory else ()
    dependency_plan = plan_composition(
        preview.manifest,
        CompositionEnvironment(
            python_version or platform.python_version(),
            wagent_version or get_version(),
        ),
        StaticCompositionDependencyResolver(candidates),
    )
    return plan_plugin_installations(
        dependency_plan,
        load_plugin_install_catalog(catalog_path),
    )


async def _validate_installed_plugin(
    installation: PluginInstallResult,
) -> tuple[dict[str, Any], ...]:
    manager = PluginManager()
    batch = None
    try:
        batch = await load_installed_plugin_references(
            manager,
            (InstalledPluginReference(installation),),
        )
        return tuple(
            _plugin_record_payload(record)
            for record in manager.records()
            if record.state.value == "active"
        )
    finally:
        if batch is not None:
            await batch.unload()
        else:
            await manager.close()


async def _validate_plugin_batch(
    references: tuple[PluginReference, ...],
) -> tuple[dict[str, Any], ...]:
    manager = PluginManager()
    try:
        await load_plugin_references(manager, references)
        return tuple(
            _plugin_record_payload(record)
            for record in manager.records()
            if record.state.value == "active"
        )
    finally:
        await manager.close()


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
    if "shared_budget" in payload:
        console.print("Shared pool (not evaluation-only usage): " + json.dumps(payload["shared_budget"], ensure_ascii=False),
                      markup=False)
    if "service_usage" in payload:
        console.print("Service usage (host operation, not evaluation-only usage): " + json.dumps(payload["service_usage"], ensure_ascii=False),
                      markup=False)


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


def _agent_usage_payload(summary: AgentUsageSummary) -> dict[str, Any]:
    return {
        "agent_name": summary.agent_name,
        "session_count": summary.session_count,
        "session_ids": list(summary.session_ids),
        "run_count": summary.run_count,
        "usage": {
            "input_tokens": summary.usage.input_tokens,
            "output_tokens": summary.usage.output_tokens,
            "cached_input_tokens": summary.usage.cached_input_tokens,
            "total_tokens": summary.usage.total_tokens,
        },
        "model_calls": summary.model_calls,
        "reported_usage_calls": summary.reported_usage_calls,
        "usage_complete": summary.usage_complete,
        "cost": _cost_payload(summary.cost),
        "priced_usage_calls": summary.priced_usage_calls,
        "cost_complete": summary.cost_complete,
    }


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


def _approval_run_result_payload(result: RunResult) -> dict[str, Any]:
    """Status/accounting only; no model output, arguments, or event bodies."""
    pending = result.pending_tool_call
    return {
        "run_id": result.run_id, "checkpoint_id": result.checkpoint_id,
        "stop_reason": result.stop_reason.value, "steps": result.steps,
        "tool_calls": result.tool_calls,
        "pending_call_id": pending.id if pending is not None else None,
        "pending_tool_name": pending.name if pending is not None else None,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cached_input_tokens": result.usage.cached_input_tokens,
            "total_tokens": result.usage.total_tokens,
            "complete": result.usage_complete,
        },
        "cost": _cost_payload(result.cost), "cost_complete": result.cost_complete,
        "selected_child_execution_confirmed": False,
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


def _plugin_record_payload(record: PluginRecord) -> dict[str, Any]:
    spec = record.spec
    return {
        "name": spec.name,
        "version": spec.version,
        "api_version": spec.api_version,
        "state": record.state.value,
        "scope": [
            {"kind": segment.kind, "value": segment.value}
            for segment in spec.scope
        ],
        "provides": [
            {
                "capability": item.capability,
                "name": item.name,
                "version": item.version,
                "exclusive": item.exclusive,
            }
            for item in spec.provides
        ],
        "requires": [
            {
                "capability": item.capability,
                "name": item.name,
                "version": item.version,
            }
            for item in spec.requires
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


def _cost_text(cost: ModelCost | None, *, complete: bool) -> str:
    if cost is None:
        return "unavailable"
    suffix = "" if complete else " (incomplete)"
    return f"{cost.total} {cost.currency}@{cost.price_table_version}{suffix}"


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


def _usage_options(entry: str | None, code: bool, recording: bool) -> None:
    """Validate recording separately, before input files or any host code."""
    try:
        ServiceUsageOptions(entry, code, recording)
    except ValueError as error:
        _fail(str(error))


register_knowledge_commands(app)
register_knowledge_index_commands(app)
register_knowledge_plan_actions(app)
register_knowledge_build_commands(app)
register_knowledge_sync_commands(app)
register_knowledge_archive_commands(app)
register_service_usage_commands(app)


def main() -> None:
    app(prog_name="wagent")


if __name__ == "__main__":
    main()
