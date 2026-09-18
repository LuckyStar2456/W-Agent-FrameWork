"""Optional in-process Textual UI over public W-Agent APIs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.app import App, ComposeResult
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from w_agent import __version__
from w_agent.agents import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    JsonlRunStore,
    RunEvent,
    RunStoreError,
)
from w_agent.compositions import (
    CompositionError,
    CompositionStore,
    inspect_composition,
    manifest_to_dict,
)
from w_agent.evaluation import (
    EvaluationCase,
    EvaluationDatasetError,
    ExactTextScorer,
    JsonEvaluationReporter,
    LocalEvaluationRunner,
    load_evaluation_cases,
)
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    LocalRuntimeRun,
    assemble_local_provider,
    assemble_local_runtime,
    load_local_runtime_config,
)
from w_agent.kernel import (
    PluginLoadError,
    PluginManager,
    PluginUnloadError,
    load_plugin_references,
    load_yaml_references,
    preview_plugin_references,
)
from w_agent.models import (
    EndpointProbe,
    ModelCost,
    ModelProviderProbe,
    PricingError,
    ProbeMode,
)
from w_agent.sandbox import DockerSandboxProvider
from w_agent.sessions import JsonSessionStore, SessionError, SessionManager
from w_agent.tools import ToolEntryLoadError, load_tool_entries
from w_agent.workflows import (
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    WorkflowEntryLoadError,
    WorkflowEvent,
    WorkflowStoreError,
    load_workflow_entries,
)


class WAgentTui(App[None]):
    """Local UI shell; it owns no capability unavailable through public APIs."""

    TITLE = "W-Agent"
    SUB_TITLE = "local agent development"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    Screen { background: $surface; }
    TabPane { padding: 1 2; overflow-y: auto; }
    .panel { border: round $primary; padding: 1 2; margin-bottom: 1; }
    Input { margin-bottom: 1; }
    Button { margin-bottom: 1; }
    #composition-result, #probe-result, #provider-probe-result, #plugin-preview-result, #plugin-result, #session-result, #run-result, #run-events, #checkpoint-result, #checkpoint-resume-result, #checkpoint-events, #workflow-checkpoint-result, #workflow-checkpoint-resume-result, #workflow-checkpoint-events, #evaluation-result { min-height: 8; }
    """

    def __init__(self, workspace: str | Path = ".") -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.sessions = SessionManager(
            JsonSessionStore(self.workspace / ".wagent" / "sessions")
        )
        self.runs = JsonlRunStore(self.workspace / ".wagent")
        self.plugin_manager = PluginManager()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="home"):
            with TabPane("Home", id="home"):
                yield Static(id="home-summary", classes="panel")
            with TabPane("Models", id="models"):
                yield Label("Safe endpoint probe (no credentials or body)")
                yield Input(
                    placeholder="https://api.example.test",
                    id="probe-endpoint",
                )
                yield Button("Run safe probe", id="probe-button", variant="primary")
                yield Static("No probe run.", id="probe-result", classes="panel")
                yield Label("Configured provider probe")
                yield Input(value=".wagent/config.json", id="provider-probe-config")
                yield Input(
                    placeholder="Type ACTIVE to authorize minimal generation",
                    id="provider-probe-confirm",
                )
                yield Button("Check provider catalog", id="provider-probe-safe")
                yield Button(
                    "Run active generation probe",
                    id="provider-probe-active",
                    variant="warning",
                )
                yield Static(
                    "No configured provider probe run.",
                    id="provider-probe-result",
                    classes="panel",
                )
            with TabPane("Profiles", id="profiles"):
                yield Static(self._profile_text(), classes="panel")
            with TabPane("Plugins", id="plugins"):
                yield Label("Review local plugin references without importing code")
                yield Input(value=".wagent/plugins.yml", id="plugin-config")
                yield Button("Preview references", id="plugin-preview")
                yield Static(
                    "No plugin configuration previewed.",
                    id="plugin-preview-result",
                    classes="panel",
                )
                yield Label(
                    "Loading executes developer-owned Python code. Installation "
                    "and updates are never automatic."
                )
                yield Input(
                    placeholder="Type LOAD PLUGINS to authorize imports and setup",
                    id="plugin-load-confirm",
                )
                yield Button(
                    "Load enabled plugins",
                    id="plugin-load",
                    variant="warning",
                )
                yield Button("Refresh lifecycle state", id="plugin-refresh")
                yield Static(
                    "No plugin lifecycle records.",
                    id="plugin-result",
                    classes="panel",
                )
                yield Label(
                    "Unloading a provider also unloads active dependent plugins."
                )
                yield Input(placeholder="Exact plugin name", id="plugin-unload-name")
                yield Input(
                    placeholder="Type UNLOAD <plugin-name>",
                    id="plugin-unload-confirm",
                )
                yield Button(
                    "Unload plugin and dependents",
                    id="plugin-unload",
                    variant="warning",
                )
            with TabPane("Composition", id="composition"):
                yield Label("Paste a wagent-compose:v1 code for offline preview")
                yield Input(placeholder="wagent-compose:v1:...", id="composition-code")
                yield Button(
                    "Inspect without loading",
                    id="composition-button",
                    variant="primary",
                )
                yield Static(
                    "No composition inspected.",
                    id="composition-result",
                    classes="panel",
                )
            with TabPane("Sessions", id="sessions"):
                yield Label("Local persistent session lifecycle")
                yield Input(placeholder="Session title", id="session-title")
                yield Input(
                    placeholder="Session ID for archive/unarchive",
                    id="session-id",
                )
                yield Button("Create", id="session-create", variant="primary")
                yield Button("Refresh", id="session-refresh")
                yield Button("Archive", id="session-archive", variant="warning")
                yield Button("Unarchive", id="session-unarchive")
                yield Static("Loading sessions…", id="session-result", classes="panel")
            with TabPane("Run", id="run"):
                yield Label("Configured text agent run")
                yield Input(value=".wagent/config.json", id="run-config")
                yield Input(placeholder="Prompt", id="run-prompt")
                yield Input(
                    placeholder="Existing session ID (optional)",
                    id="run-session",
                )
                yield Input(
                    placeholder="Tool entries, comma-separated module:attribute",
                    id="run-tool-entries",
                )
                yield Input(
                    placeholder="Runtime permissions, comma-separated",
                    id="run-permissions",
                )
                yield Input(
                    placeholder="Type LOAD TOOLS to authorize Python imports",
                    id="run-tool-confirm",
                )
                yield Input(
                    placeholder="Type RUN to authorize the model call",
                    id="run-confirm",
                )
                yield Button("Start configured run", id="run-button", variant="primary")
                yield Static("No live events.", id="run-events", classes="panel")
                yield Static(
                    "No configured run started.", id="run-result", classes="panel"
                )
            with TabPane("Checkpoints", id="checkpoints"):
                yield Button("Refresh agent checkpoints", id="checkpoint-refresh")
                yield Static(
                    "Loading agent checkpoints…",
                    id="checkpoint-result",
                    classes="panel",
                )
                yield Label("Approve and resume one exact tool call")
                yield Input(value=".wagent/config.json", id="checkpoint-config")
                yield Input(placeholder="Session ID", id="checkpoint-session")
                yield Input(placeholder="Run ID", id="checkpoint-run")
                yield Input(placeholder="Exact tool call ID", id="checkpoint-call")
                yield Input(
                    placeholder="Tool entries, comma-separated module:attribute",
                    id="checkpoint-tool-entries",
                )
                yield Input(
                    placeholder="Runtime permissions, comma-separated",
                    id="checkpoint-permissions",
                )
                yield Input(
                    placeholder="Type LOAD TOOLS to authorize Python imports",
                    id="checkpoint-tool-confirm",
                )
                yield Input(
                    placeholder="Type RESUME to authorize execution and model calls",
                    id="checkpoint-confirm",
                )
                yield Button(
                    "Approve exact call and resume",
                    id="checkpoint-resume",
                    variant="warning",
                )
                yield Static(
                    "No resumed events.", id="checkpoint-events", classes="panel"
                )
                yield Static(
                    "No checkpoint resumed.",
                    id="checkpoint-resume-result",
                    classes="panel",
                )
                yield Label("Workflow checkpoints (runtime values are hidden)")
                yield Input(value=".wagent", id="workflow-checkpoint-state-root")
                yield Button(
                    "Refresh workflow checkpoints",
                    id="workflow-checkpoint-refresh",
                )
                yield Static(
                    "Loading workflow checkpoints…",
                    id="workflow-checkpoint-result",
                    classes="panel",
                )
                yield Label("Load the exact workflow definition and resume")
                yield Input(
                    placeholder="Workflow run ID",
                    id="workflow-checkpoint-run",
                )
                yield Input(
                    placeholder=(
                        "Workflow entries, comma-separated module:attribute"
                    ),
                    id="workflow-checkpoint-entries",
                )
                yield Input(
                    placeholder="Type LOAD WORKFLOW to authorize Python imports",
                    id="workflow-checkpoint-load-confirm",
                )
                yield Input(
                    placeholder="Type RESUME WORKFLOW to authorize execution",
                    id="workflow-checkpoint-resume-confirm",
                )
                yield Button(
                    "Load exact definition and resume",
                    id="workflow-checkpoint-resume",
                    variant="warning",
                )
                yield Static(
                    "No resumed workflow events.",
                    id="workflow-checkpoint-events",
                    classes="panel",
                )
                yield Static(
                    "No workflow checkpoint resumed.",
                    id="workflow-checkpoint-resume-result",
                    classes="panel",
                )
            with TabPane("Sandbox", id="sandbox"):
                yield Static(
                    "Checking Docker/OCI…", id="sandbox-summary", classes="panel"
                )
            with TabPane("Evaluation", id="evaluation"):
                yield Label("Sequential local evaluation with disposable run state")
                yield Input(
                    placeholder="Evaluation dataset JSON",
                    id="evaluation-dataset",
                )
                yield Input(value=".wagent/config.json", id="evaluation-config")
                yield Input(
                    placeholder="Optional privacy-safe report JSON path",
                    id="evaluation-report",
                )
                yield Input(
                    placeholder="Type EVALUATE to authorize model calls",
                    id="evaluation-confirm",
                )
                yield Button(
                    "Run evaluation",
                    id="evaluation-button",
                    variant="primary",
                )
                yield Static(
                    "No evaluation run.", id="evaluation-result", classes="panel"
                )
        yield Footer()

    async def on_mount(self) -> None:
        store = CompositionStore(self.workspace / ".wagent" / "compositions")
        entries = store.entries()
        sessions = await self.sessions.list(include_archived=True)
        summary = (
            f"Workspace: {self.workspace}\n"
            f"Python framework version: {__version__}\n"
            f"Stored compositions: {len(entries)}\n"
            f"Stored sessions: {len(sessions)}\n"
            "No hosted service or background daemon is required."
        )
        self.query_one("#home-summary", Static).update(summary)
        await self._refresh_sessions()
        self._refresh_plugins()
        await self._refresh_checkpoints()
        await self._refresh_workflow_checkpoints()
        available = await DockerSandboxProvider().available()
        self.query_one("#sandbox-summary", Static).update(
            f"Docker/OCI available: {available}\n"
            "Unsafe local execution is never enabled by this UI. It requires an "
            "explicit runtime authorization object from the host application."
        )

    async def on_unmount(self) -> None:
        await self.plugin_manager.close()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composition-button":
            self._inspect_composition()
        elif event.button.id == "plugin-preview":
            self._preview_plugins()
        elif event.button.id == "plugin-load":
            await self._load_plugins()
        elif event.button.id == "plugin-refresh":
            self._refresh_plugins()
        elif event.button.id == "plugin-unload":
            await self._unload_plugin()
        elif event.button.id == "probe-button":
            await self._probe_endpoint()
        elif event.button.id == "provider-probe-safe":
            await self._probe_configured_provider(active=False)
        elif event.button.id == "provider-probe-active":
            await self._probe_configured_provider(active=True)
        elif event.button.id == "session-create":
            await self._create_session()
        elif event.button.id == "session-refresh":
            await self._refresh_sessions()
        elif event.button.id == "session-archive":
            await self._set_session_archived(True)
        elif event.button.id == "session-unarchive":
            await self._set_session_archived(False)
        elif event.button.id == "run-button":
            await self._run_configured_agent()
        elif event.button.id == "checkpoint-refresh":
            await self._refresh_checkpoints()
        elif event.button.id == "checkpoint-resume":
            await self._resume_configured_agent()
        elif event.button.id == "workflow-checkpoint-refresh":
            await self._refresh_workflow_checkpoints()
        elif event.button.id == "workflow-checkpoint-resume":
            await self._resume_workflow()
        elif event.button.id == "evaluation-button":
            await self._run_evaluation()

    def _inspect_composition(self) -> None:
        code = self.query_one("#composition-code", Input).value.strip()
        target = self.query_one("#composition-result", Static)
        try:
            preview = inspect_composition(code)
        except CompositionError as error:
            target.update(f"Rejected: {error}")
            return
        target.update(
            json.dumps(
                {
                    "digest": preview.digest,
                    "manifest": manifest_to_dict(preview.manifest),
                    "risks": preview.risks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    def _preview_plugins(self) -> None:
        target = self.query_one("#plugin-preview-result", Static)
        try:
            references = load_yaml_references(self._plugin_config_path())
            summaries = preview_plugin_references(references)
        except (OSError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        lines = [
            (
                f"{item.entry} | enabled={item.enabled} | "
                f"config keys={','.join(item.config_keys) or '-'}"
            )
            for item in summaries
        ]
        target.update(
            "\n".join(lines)
            if lines
            else "No plugin references. No code was imported."
        )

    async def _load_plugins(self) -> None:
        target = self.query_one("#plugin-result", Static)
        confirmation = self.query_one("#plugin-load-confirm", Input)
        if confirmation.value.strip() != "LOAD PLUGINS":
            target.update(
                "Rejected: type LOAD PLUGINS to authorize developer Python code"
            )
            return
        confirmation.value = ""
        target.update("Loading explicitly authorized plugins…")
        try:
            references = load_yaml_references(self._plugin_config_path())
            await load_plugin_references(self.plugin_manager, references)
        except (OSError, PluginLoadError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Plugin load failed: {type(error).__name__}")
            return
        self._refresh_plugins(prefix="Plugin batch loaded.\n")

    def _refresh_plugins(self, *, prefix: str = "") -> None:
        target = self.query_one("#plugin-result", Static)
        records = sorted(
            self.plugin_manager.records(),
            key=lambda record: record.spec.name,
        )
        lines = [
            (
                f"{record.spec.name}@{record.spec.version} | "
                f"api={record.spec.api_version} | state={record.state.value} | "
                "provides="
                f"{','.join(item.capability for item in record.spec.provides) or '-'} | "
                "requires="
                f"{','.join(item.capability for item in record.spec.requires) or '-'}"
            )
            for record in records
        ]
        body = "\n".join(lines) if lines else "No plugin lifecycle records."
        target.update(prefix + body)

    async def _unload_plugin(self) -> None:
        target = self.query_one("#plugin-result", Static)
        name = self.query_one("#plugin-unload-name", Input).value.strip()
        confirmation = self.query_one("#plugin-unload-confirm", Input)
        if not name:
            target.update("Rejected: exact plugin name is required")
            return
        if confirmation.value.strip() != f"UNLOAD {name}":
            target.update(
                f"Rejected: type UNLOAD {name} to unload it and active dependents"
            )
            return
        confirmation.value = ""
        try:
            await self.plugin_manager.unload(name)
        except (KeyError, PluginUnloadError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Plugin unload failed: {type(error).__name__}")
            return
        self._refresh_plugins(prefix=f"Unloaded {name} and active dependents.\n")

    async def _probe_endpoint(self) -> None:
        endpoint = self.query_one("#probe-endpoint", Input).value.strip()
        target = self.query_one("#probe-result", Static)
        if not endpoint:
            target.update("Rejected: endpoint is required")
            return
        target.update("Probing safely…")
        result = await EndpointProbe().probe(endpoint)
        lines = [
            f"Target: {result.target}",
            f"Successful: {result.successful}",
        ]
        lines.extend(
            f"L{int(check.level)} {check.name}: {check.status.value} — {check.message}"
            for check in result.checks
        )
        target.update("\n".join(lines))

    async def _probe_configured_provider(self, *, active: bool) -> None:
        target = self.query_one("#provider-probe-result", Static)
        confirmation = self.query_one("#provider-probe-confirm", Input)
        if active and confirmation.value.strip() != "ACTIVE":
            target.update("Rejected: type ACTIVE to authorize minimal generation")
            return
        confirmation.value = ""
        source = Path(self.query_one("#provider-probe-config", Input).value)
        if not source.is_absolute():
            source = self.workspace / source
        target.update("Probing configured provider…")
        try:
            config = load_local_runtime_config(source)
            assembly = assemble_local_provider(config)
            async with assembly:
                result = await ModelProviderProbe().probe(
                    assembly.name,
                    assembly.provider,
                    mode=ProbeMode.ACTIVE if active else ProbeMode.SAFE,
                    allow_active=active,
                    model=config.provider.model,
                )
        except (LocalRuntimeConfigError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Probe failed: {type(error).__name__}")
            return
        lines = [
            f"Provider: {result.target}",
            f"Mode: {result.mode.value}",
            f"Successful: {result.successful}",
        ]
        lines.extend(
            f"L{int(check.level)} {check.name}: {check.status.value} — {check.message}"
            for check in result.checks
        )
        target.update("\n".join(lines))

    async def _create_session(self) -> None:
        title = self.query_one("#session-title", Input).value.strip()
        target = self.query_one("#session-result", Static)
        if not title:
            target.update("Rejected: session title is required")
            return
        try:
            created = await self.sessions.create(title)
        except (SessionError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        self.query_one("#session-title", Input).value = ""
        self.query_one("#session-id", Input).value = created.session_id
        await self._refresh_sessions(prefix=f"Created {created.session_id}\n")

    async def _set_session_archived(self, archived: bool) -> None:
        session_id = self.query_one("#session-id", Input).value.strip()
        target = self.query_one("#session-result", Static)
        if not session_id:
            target.update("Rejected: session ID is required")
            return
        try:
            updated = await self.sessions.archive(session_id, archived=archived)
        except (SessionError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        action = "Archived" if archived else "Unarchived"
        await self._refresh_sessions(prefix=f"{action} {updated.session_id}\n")

    async def _refresh_sessions(self, *, prefix: str = "") -> None:
        sessions = await self.sessions.list(include_archived=True)
        lines = [
            (
                f"{item.session_id} | {item.status.value} | {item.title} | "
                f"runs={len(item.runs)} | "
                f"attempts={sum(run.model_calls for run in item.runs)} | "
                f"tokens={sum(run.usage.total_tokens for run in item.runs)} | "
                f"cost={_session_cost_text(item.runs)}"
            )
            for item in sessions
        ]
        body = "\n".join(lines) if lines else "No local sessions."
        self.query_one("#session-result", Static).update(prefix + body)

    async def _refresh_checkpoints(self) -> None:
        target = self.query_one("#checkpoint-result", Static)
        try:
            checkpoints = await self.runs.list_checkpoints()
        except (RunStoreError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        lines = [
            (
                f"{item.run_id} | session={item.session_id or '-'} | "
                f"{item.status.value} | tool={item.pending_tool_name or '-'} | "
                f"call={item.pending_call_id or '-'} | "
                f"keys={','.join(item.pending_argument_keys)} | "
                f"tokens={item.usage.total_tokens} | "
                f"cost={_cost_text(item.cost, complete=item.cost_complete)}"
            )
            for item in checkpoints
        ]
        target.update("\n".join(lines) if lines else "No agent checkpoints.")

    async def _refresh_workflow_checkpoints(self) -> None:
        target = self.query_one("#workflow-checkpoint-result", Static)
        try:
            store = self._workflow_store()
            checkpoints = await store.list_checkpoints()
        except (OSError, WorkflowStoreError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        lines = [
            (
                f"{item.run_id} | session={item.session_id or '-'} | "
                f"workflow={item.workflow_name}@{item.workflow_version} | "
                f"kind={item.kind.value} | status={item.status.value} | "
                f"current={item.current_node or '-'} | "
                f"completed={','.join(item.completed_nodes) or '-'} | "
                f"remaining={','.join(item.remaining_nodes) or '-'} | "
                f"steps={item.graph_steps} | resumes={item.resume_count}"
            )
            for item in checkpoints
        ]
        target.update("\n".join(lines) if lines else "No workflow checkpoints.")

    async def _run_configured_agent(self) -> None:
        target = self.query_one("#run-result", Static)
        confirmation = self.query_one("#run-confirm", Input)
        if confirmation.value.strip() != "RUN":
            target.update("Rejected: type RUN to authorize the model call")
            return
        confirmation.value = ""
        try:
            tool_entries = _split_values(
                self.query_one("#run-tool-entries", Input).value
            )
            permissions = frozenset(
                _split_values(self.query_one("#run-permissions", Input).value)
            )
        except ValueError as error:
            target.update(f"Rejected: {error}")
            return
        tool_confirmation = self.query_one("#run-tool-confirm", Input)
        if tool_entries and tool_confirmation.value.strip() != "LOAD TOOLS":
            target.update(
                "Rejected: type LOAD TOOLS to authorize developer Python imports"
            )
            return
        tool_confirmation.value = ""
        prompt = self.query_one("#run-prompt", Input).value
        if not prompt:
            target.update("Rejected: prompt is required")
            return
        source = Path(self.query_one("#run-config", Input).value)
        if not source.is_absolute():
            source = self.workspace / source
        session_id = self.query_one("#run-session", Input).value.strip() or None
        event_target = self.query_one("#run-events", Static)
        event_lines: list[str] = []

        async def show_event(event: RunEvent) -> None:
            event_lines.append(_event_text(event))
            event_target.update("\n".join(event_lines))

        target.update("Running configured agent…")
        event_target.update("Waiting for the first event…")
        try:
            catalog = load_tool_entries(tool_entries) if tool_entries else {}
            runtime = assemble_local_runtime(
                load_local_runtime_config(source),
                self.workspace / ".wagent",
                tool_bindings=catalog,
            )
            async with runtime:
                run = await runtime.run(
                    prompt,
                    session_id=session_id,
                    permissions=permissions,
                    event_callback=show_event,
                )
        except (
            LocalRuntimeConfigError,
            SessionError,
            ToolEntryLoadError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Run failed: {type(error).__name__}")
            return
        self._show_run_result(target, run)
        self.query_one("#run-session", Input).value = run.session.session_id
        self._select_pending_checkpoint(run)
        await self._refresh_sessions()
        await self._refresh_checkpoints()

    async def _resume_configured_agent(self) -> None:
        target = self.query_one("#checkpoint-resume-result", Static)
        confirmation = self.query_one("#checkpoint-confirm", Input)
        if confirmation.value.strip() != "RESUME":
            target.update(
                "Rejected: type RESUME to authorize tool execution and model calls"
            )
            return
        confirmation.value = ""
        session_id = self.query_one("#checkpoint-session", Input).value.strip()
        run_id = self.query_one("#checkpoint-run", Input).value.strip()
        call_id = self.query_one("#checkpoint-call", Input).value.strip()
        if not session_id or not run_id or not call_id:
            target.update("Rejected: session, run, and exact call ID are required")
            return
        try:
            tool_entries = _split_values(
                self.query_one("#checkpoint-tool-entries", Input).value
            )
            permissions = frozenset(
                _split_values(
                    self.query_one("#checkpoint-permissions", Input).value
                )
            )
        except ValueError as error:
            target.update(f"Rejected: {error}")
            return
        tool_confirmation = self.query_one("#checkpoint-tool-confirm", Input)
        if tool_entries and tool_confirmation.value.strip() != "LOAD TOOLS":
            target.update(
                "Rejected: type LOAD TOOLS to authorize developer Python imports"
            )
            return
        tool_confirmation.value = ""
        source = self._workspace_path(
            self.query_one("#checkpoint-config", Input).value
        )
        event_target = self.query_one("#checkpoint-events", Static)
        event_lines: list[str] = []

        async def show_event(event: RunEvent) -> None:
            event_lines.append(_event_text(event))
            event_target.update("\n".join(event_lines))

        target.update("Resuming approved tool call…")
        event_target.update("Waiting for the first resumed event…")
        try:
            catalog = load_tool_entries(tool_entries) if tool_entries else {}
            runtime = assemble_local_runtime(
                load_local_runtime_config(source),
                self.workspace / ".wagent",
                tool_bindings=catalog,
            )
            async with runtime:
                run = await runtime.resume(
                    session_id,
                    run_id,
                    permissions=permissions,
                    approved_call_ids=frozenset({call_id}),
                    event_callback=show_event,
                )
        except (
            LocalRuntimeConfigError,
            RunStoreError,
            SessionError,
            ToolEntryLoadError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Resume failed: {type(error).__name__}")
            return
        self._show_run_result(target, run)
        self._select_pending_checkpoint(run)
        await self._refresh_sessions()
        await self._refresh_checkpoints()

    async def _resume_workflow(self) -> None:
        target = self.query_one("#workflow-checkpoint-resume-result", Static)
        resume_confirmation = self.query_one(
            "#workflow-checkpoint-resume-confirm",
            Input,
        )
        if resume_confirmation.value.strip() != "RESUME WORKFLOW":
            target.update(
                "Rejected: type RESUME WORKFLOW to authorize workflow execution"
            )
            return
        run_id = self.query_one("#workflow-checkpoint-run", Input).value.strip()
        if not run_id:
            target.update("Rejected: workflow run ID is required")
            return
        try:
            entries = _split_values(
                self.query_one("#workflow-checkpoint-entries", Input).value
            )
        except ValueError as error:
            target.update(f"Rejected: {error}")
            return
        if not entries:
            target.update("Rejected: at least one workflow entry is required")
            return
        load_confirmation = self.query_one(
            "#workflow-checkpoint-load-confirm",
            Input,
        )
        if load_confirmation.value.strip() != "LOAD WORKFLOW":
            target.update(
                "Rejected: type LOAD WORKFLOW to authorize developer Python imports"
            )
            return

        event_target = self.query_one("#workflow-checkpoint-events", Static)
        target.update("Loading exact workflow definition and resuming…")
        event_target.update("Waiting for resumed workflow events…")
        resume_confirmation.value = ""
        load_confirmation.value = ""
        try:
            store = self._workflow_store()
            checkpoint = await store.load_checkpoint(run_id)
            if checkpoint is None:
                raise WorkflowStoreError(
                    f"workflow run {run_id!r} has no resumable checkpoint"
                )
            catalog = load_workflow_entries(entries)
            identity = (checkpoint.workflow_name, checkpoint.workflow_version)
            definition = catalog.get(identity)
            if definition is None:
                raise WorkflowEntryLoadError(
                    "loaded entries do not provide exact workflow "
                    f"{checkpoint.workflow_name}@{checkpoint.workflow_version}"
                )
            if definition.kind is not checkpoint.kind:
                raise WorkflowStoreError(
                    "loaded workflow kind differs from the checkpoint"
                )
            result = await LocalWorkflowEngine(store).resume(definition, run_id)
        except (
            OSError,
            WorkflowEntryLoadError,
            WorkflowStoreError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Workflow resume failed: {type(error).__name__}")
            return

        event_target.update(
            "\n".join(_workflow_event_text(event) for event in result.events)
            or "No workflow events."
        )
        target.update(
            f"Run: {result.run_id}\n"
            f"Stop: {result.stop_reason.value}\n"
            f"Completed nodes: {','.join(result.completed_nodes) or '-'}\n"
            f"Checkpoint retained: {result.checkpoint_id or '-'}\n"
            f"Events: {len(result.events)}\n"
            "Runtime input, state, output, and metadata are hidden."
        )
        await self._refresh_workflow_checkpoints()

    def _show_run_result(self, target: Static, run: LocalRuntimeRun) -> None:
        result = run.result
        cost_text = (
            f"\nCost: {result.cost.total} {result.cost.currency}, "
            f"table={result.cost.price_table_version}, "
            f"complete={result.cost_complete}"
            if result.cost is not None
            else "\nCost: unavailable"
        )
        target.update(
            f"Session: {run.session.session_id}\n"
            f"Run: {result.run_id}\n"
            f"Stop: {result.stop_reason.value}\n"
            f"Attempts: {len(result.attempts)}\n"
            f"Tokens: in={result.usage.input_tokens}, "
            f"out={result.usage.output_tokens}, "
            f"total={result.usage.total_tokens}, "
            f"complete={result.usage_complete}"
            f"{cost_text}\n\n"
            f"{result.output}"
        )

    def _select_pending_checkpoint(self, run: LocalRuntimeRun) -> None:
        result = run.result
        pending = result.pending_tool_call
        if pending is None:
            return
        self.query_one("#checkpoint-session", Input).value = run.session.session_id
        self.query_one("#checkpoint-run", Input).value = result.run_id
        self.query_one("#checkpoint-call", Input).value = pending.id

    async def _run_evaluation(self) -> None:
        target = self.query_one("#evaluation-result", Static)
        confirmation = self.query_one("#evaluation-confirm", Input)
        if confirmation.value.strip() != "EVALUATE":
            target.update("Rejected: type EVALUATE to authorize model calls")
            return
        confirmation.value = ""
        dataset = self._workspace_path(
            self.query_one("#evaluation-dataset", Input).value
        )
        config_path = self._workspace_path(
            self.query_one("#evaluation-config", Input).value
        )
        report_value = self.query_one("#evaluation-report", Input).value.strip()
        report_path = self._workspace_path(report_value) if report_value else None
        target.update("Running evaluation…")
        try:
            cases = load_evaluation_cases(dataset)
            with TemporaryDirectory(prefix="wagent-tui-eval-") as state_root:
                runtime = assemble_local_runtime(
                    load_local_runtime_config(config_path),
                    state_root,
                )

                async def run_case(case: EvaluationCase):
                    run = await runtime.run(
                        case.prompt,
                        session_title=f"Evaluation: {case.name}",
                    )
                    return run.result

                async with runtime:
                    report = await LocalEvaluationRunner().run(
                        cases,
                        run_case,
                        scorers=(ExactTextScorer(),),
                    )
            if report_path is not None:
                await JsonEvaluationReporter().write(report, report_path)
        except (
            EvaluationDatasetError,
            LocalRuntimeConfigError,
            OSError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Evaluation failed: {type(error).__name__}")
            return
        usage = report.usage
        lines = [
            f"Passed: {report.passed}/{report.total} ({report.pass_rate:.1%})",
            f"Tokens: in={usage.input_tokens}, out={usage.output_tokens}, "
            f"total={usage.total_tokens}, complete={report.usage_complete}",
            f"Latency: total={report.latency_ms:.2f} ms, "
            f"average={report.average_latency_ms:.2f} ms",
            f"Tools: success={report.tool_successes}, failed={report.tool_failures}",
        ]
        if report.cost is not None:
            lines.append(
                f"Cost: {report.cost.total} {report.cost.currency}, "
                f"table={report.cost.price_table_version}, "
                f"complete={report.cost_complete}"
            )
        else:
            lines.append("Cost: unavailable")
        lines.extend(
            f"{case.name}: {'PASS' if case.passed else 'FAIL'} | "
            f"stop={case.stop_reason or '-'} | tokens={case.usage.total_tokens}"
            for case in report.cases
        )
        target.update("\n".join(lines))

    def _workspace_path(self, value: str) -> Path:
        path = Path(value.strip())
        return path if path.is_absolute() else self.workspace / path

    def _plugin_config_path(self) -> Path:
        value = self.query_one("#plugin-config", Input).value.strip()
        if not value:
            raise ValueError("plugin config path is required")
        return self._workspace_path(value)

    def _workflow_store(self) -> JsonlWorkflowStore:
        value = self.query_one("#workflow-checkpoint-state-root", Input).value.strip()
        if not value:
            raise ValueError("workflow state root is required")
        return JsonlWorkflowStore(self._workspace_path(value))

    @staticmethod
    def _profile_text() -> str:
        templates = (CUSTOMER_SUPPORT_AGENT_TEMPLATE, CODING_AGENT_TEMPLATE)
        return "\n\n".join(
            f"{item.key}\n{item.description}\n"
            f"Suggested tools: {', '.join(item.recommended_tools)}"
            for item in templates
        )


def run_tui(workspace: str | Path = ".") -> None:
    WAgentTui(workspace).run()


def _split_values(value: str) -> tuple[str, ...]:
    """Parse a compact UI list without allowing blank or duplicate entries."""

    values = tuple(item.strip() for item in value.split(",") if item.strip())
    if len(values) != len(set(values)):
        raise ValueError("list entries must be unique")
    return values


def _event_text(event: RunEvent) -> str:
    """Render a prompt/argument/output-free event projection for the TUI."""

    fields = (
        "step",
        "provider",
        "model",
        "finish_reason",
        "call_id",
        "name",
        "outcome",
        "failure_code",
        "reason",
        "stop_reason",
        "checkpoint_status",
        "pending_call_id",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "usage_complete",
        "max_cost",
        "cost_complete",
    )
    details = [
        f"{name}={event.data[name]}"
        for name in fields
        if event.data.get(name) is not None
    ]
    cost = event.data.get("cost")
    if isinstance(cost, Mapping):
        total = cost.get("total")
        currency = cost.get("currency")
        if total is not None and currency is not None:
            details.append(f"cost={total} {currency}")
    prefix = f"{event.sequence:03d} {event.type.value}"
    return prefix if not details else f"{prefix} | {' | '.join(details)}"


def _workflow_event_text(event: WorkflowEvent) -> str:
    """Render workflow control metadata without runtime values."""

    fields = (
        "workflow",
        "version",
        "kind",
        "status",
        "node",
        "paused",
        "reason",
        "code",
    )
    details = [
        f"{name}={event.data[name]}"
        for name in fields
        if event.data.get(name) is not None
    ]
    prefix = f"{event.sequence:03d} {event.type.value}"
    return prefix if not details else f"{prefix} | {' | '.join(details)}"


def _cost_text(cost: ModelCost | None, *, complete: bool) -> str:
    if cost is None:
        return "unavailable"
    suffix = "" if complete else " (incomplete)"
    return f"{cost.total} {cost.currency}@{cost.price_table_version}{suffix}"


def _session_cost_text(runs) -> str:
    if not runs or any(run.cost is None for run in runs):
        return "unavailable"
    total = runs[0].cost
    assert total is not None
    try:
        for run in runs[1:]:
            assert run.cost is not None
            total = total.add(run.cost)
    except PricingError:
        return "mixed"
    return _cost_text(total, complete=all(run.cost_complete for run in runs))
