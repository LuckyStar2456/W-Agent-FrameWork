"""Optional in-process Textual UI over public W-Agent APIs."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.text import Text
from textual.app import App, ComposeResult
from textual.events import Resize
from textual.worker import Worker, WorkerCancelled, WorkerFailed
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

from w_agent import __version__
from w_agent.tui_application import ApplicationPanel
from w_agent.local_application import open_local_runtime, open_local_workflow
from w_agent._shared_budget_ui import BudgetEntryError, budget_binding_scope, shared_budget_summary
from w_agent._service_usage_ui import ServiceUsageOptions, service_usage_binding_scope, service_usage_summary
from w_agent._knowledge_ui import KnowledgeEvaluationOptions, KnowledgeRunOptions, knowledge_binding_scope
from w_agent.agents import (
    CODING_AGENT_TEMPLATE,
    CUSTOMER_SUPPORT_AGENT_TEMPLATE,
    JsonlRunStore,
    RunEvent,
    RunEventCursor,
    RunEventReplay,
    RunStoreError,
    safe_run_event_to_dict,
)
from w_agent.compositions import (
    CompositionError,
    CompositionStore,
    inspect_composition,
    manifest_to_dict,
)
from w_agent.composition_planning import (
    CompositionEnvironment,
    PluginCandidate,
    StaticCompositionDependencyResolver,
    load_plugin_candidates,
    plan_composition,
)
from w_agent.plugin_installation import (
    InstalledPluginBatch,
    InstalledPluginReference,
    PluginInstallAuthorization,
    PluginInstallationError,
    SandboxPipPackageInstaller,
    load_installed_plugin_references,
    load_plugin_install_catalog,
    load_plugin_install_result,
    plan_plugin_installations,
    plugin_installation_plan_to_dict,
    recommended_docker_install_user,
)
from w_agent.plugin_replacement_session import PluginReplacementSession
from w_agent.evaluation import (
    CaseContractScorer,
    ContainsTextScorer,
    EvaluationCase,
    EvaluationDatasetError,
    EvaluationScorer,
    ExactTextScorer,
    JsonEvaluationReporter,
    LocalEvaluationRunner,
    load_evaluation_dataset,
)
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    LocalRuntimeRun,
    assemble_local_provider,
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
from w_agent.sandbox import (
    DockerSandboxProvider,
    SandboxNetwork,
    SandboxSpec,
    UnsafeLocalAuthorization,
    UnsafeLocalSandboxProvider,
)
from w_agent.sessions import JsonSessionStore, SessionError, SessionManager
from w_agent.tools import ToolEntryLoadError, load_tool_entries
from w_agent.tui_branding import welcome_banner
from w_agent.tui_replay import ReplayPanel
from w_agent.tui_knowledge import KnowledgePanel
from w_agent.tui_knowledge_index import KnowledgeIndexPanel
from w_agent.tui_knowledge_plans import KnowledgePlansPanel
from w_agent.tui_knowledge_builds import KnowledgeBuildsPanel
from w_agent.tui_knowledge_sync import KnowledgeSyncPanel
from w_agent.input_manifest import InputManifestError, load_input_manifest
from w_agent.session_history_options import BuiltinSessionHistoryOptions
from w_agent.session_message_fields import MessageFieldsSessionInputRecorder
from w_agent.workflows import (
    AgentWorkflowApproval,
    AgentWorkflowAdapterError,
    AnyWorkflowPauseSource,
    JsonlWorkflowStore,
    SQLiteWorkflowPauseController,
    ThreadedWorkflowNodeInvoker,
    WorkflowEntryLoadError,
    WorkflowEvent,
    WorkflowPauseController,
    WorkflowPauseControlError,
    WorkflowStoreError,
    load_workflow_entries,
    review_workflow_approvals,
    open_workflow_approval_entry,
    resume_workflow_approval,
    WorkflowApprovalLinkStatus,
    WorkflowToolApprovalReview,
    open_workflow_tool_approval_entry,
    review_workflow_tool_approvals,
    resume_workflow_tool_approval,
)


@dataclass(frozen=True, slots=True)
class _AgentRunRequest:
    config: Path
    prompt: str
    input_file: Path | None
    session_id: str | None
    tool_entries: tuple[str, ...]
    permissions: frozenset[str]
    record_inputs: bool
    history: BuiltinSessionHistoryOptions
    allow_message_fields: bool
    input_recorder: MessageFieldsSessionInputRecorder | None
    budget_entry: str | None = None
    knowledge: KnowledgeRunOptions = field(default_factory=KnowledgeRunOptions)
    service_usage: ServiceUsageOptions = field(default_factory=ServiceUsageOptions)


_RUN_CONFIRMATIONS = ("confirm", "tool-confirm", "budget-confirm", "record-confirm", "history-confirm", "history-transform-confirm",
                      "knowledge-code-confirm", "knowledge-query-confirm")
_RUN_FIELDS = ("config", "prompt", "input-file", "session", "tool-entries", "budget-entry", "permissions",
               "usage-entry", "usage-code", "usage-record",
               "record-inputs", "history", "history-query", "history-recent-turns",
               "history-retrieved-turns", "history-summary-chars", "history-max-bytes",
               "input-message-fields", "record-input-name", "record-input-metadata", "history-name", "history-metadata",
               "knowledge-entry", "knowledge-query",
               *_RUN_CONFIRMATIONS)


@dataclass(frozen=True, slots=True)
class _ActiveWorkflowResume:
    state_root: Path
    run_id: str
    control: WorkflowPauseController
    observe_external_pause: bool = False


@dataclass(frozen=True, slots=True)
class _WorkflowApprovalRequest:
    state_root: Path
    agent_root: Path
    reference: AgentWorkflowApproval
    factory: str
    state_keys: tuple[str, ...]
    permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class _ChainQuery:
    parent_root: Path
    workflow_root: Path
    child_root: Path
    run_id: str
    state_keys: tuple[str, ...]


_CHAIN_FIELDS = (
    "parent-root", "workflow-root", "child-root", "run", "state-keys", "row",
    "factory", "parent-permissions", "child-permissions", "code-confirm",
    "parent-confirm", "child-confirm", "resume-confirm",
)
_CHAIN_CONFIRMATIONS = ("code-confirm", "parent-confirm", "child-confirm", "resume-confirm")


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
    #home-banner { height: auto; padding: 1 0; margin-bottom: 1; text-align: center; }
    #composition-result, #probe-result, #provider-probe-result, #plugin-preview-result, #plugin-result, #session-result, #run-result, #run-events, #checkpoint-result, #checkpoint-replay-result, #checkpoint-resume-result, #checkpoint-events, #workflow-checkpoint-result, #workflow-checkpoint-resume-result, #workflow-checkpoint-events, #evaluation-result { min-height: 8; }
    """

    def __init__(self, workspace: str | Path = ".") -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.sessions = SessionManager(
            JsonSessionStore(self.workspace / ".wagent" / "sessions")
        )
        self.runs = JsonlRunStore(self.workspace / ".wagent")
        self.plugin_manager = PluginManager()
        self._plugin_replacement = PluginReplacementSession(self.plugin_manager)
        self._plugin_replacement_source: str | None = None
        self._plugin_replacement_busy = False
        self.installed_plugin_batches: list[InstalledPluginBatch] = []
        self._workflow_worker: Worker[None] | None = None
        self._agent_worker: Worker[None] | None = None
        self._agent_busy = False
        self._agent_started = False
        self._agent_cancel_requested = False
        self._agent_ui_closing = False
        self._active_workflow: _ActiveWorkflowResume | None = None
        self._workflow_ui_closing = False
        self._chain_busy = False
        self._chain_review: tuple[_ChainQuery, tuple[WorkflowToolApprovalReview, ...]] | None = None
        self._chain_selection: tuple[int, WorkflowToolApprovalReview] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="home"):
            with TabPane("Application", id="application"):
                yield ApplicationPanel(self.workspace)
            with TabPane("Knowledge", id="knowledge"):
                yield KnowledgePanel(self.workspace)
            with TabPane("Index journal", id="knowledge-index"):
                yield KnowledgeIndexPanel(self.workspace)
            with TabPane("Index plans", id="knowledge-plans"):
                yield KnowledgePlansPanel(self.workspace)
            with TabPane("Knowledge builds", id="knowledge-builds"):
                yield KnowledgeBuildsPanel(self.workspace)
            with TabPane("Knowledge sync", id="knowledge-sync"):
                yield KnowledgeSyncPanel(self.workspace)
            with TabPane("Home", id="home"):
                yield Static(
                    welcome_banner(max(0, self.size.width - 8), __version__),
                    id="home-banner",
                )
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
                yield Input(placeholder="Budget host / 预算宿主 module:factory (optional)", id="provider-probe-budget-entry")
                yield Input(placeholder="Type LOAD BUDGET to authorize unsandboxed host code", id="provider-probe-budget-confirm")
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
                yield Static("Shared budget not read.", id="provider-probe-budget-result", classes="panel")
                yield from _service_usage_widgets("provider-probe")
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
                yield Label("Load a verified plugin installation (separate approval)")
                yield Input(
                    placeholder="Installed plugin directory",
                    id="plugin-installed-path",
                )
                yield Input(
                    placeholder="Type LOAD INSTALLED to authorize imports and setup",
                    id="plugin-installed-confirm",
                )
                yield Button(
                    "Load verified installed plugin",
                    id="plugin-installed-load",
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
                yield Label(
                    "Replace a local plugin in this TUI process only. Trusted Python "
                    "imports are NOT sandboxed; installed-package updates need a fresh process."
                )
                yield Input(placeholder="One-plugin replacement YAML", id="plugin-replace-config")
                yield Button("Inspect replacement (no imports)", id="plugin-replace-inspect")
                yield Input(placeholder="IMPORT REPLACEMENT <source_digest>", id="plugin-replace-import-confirm")
                yield Button("Authorize import and prepare plan", id="plugin-replace-prepare", variant="warning")
                yield Static("No replacement reviewed.", id="plugin-replace-result", classes="panel", markup=False)
                yield Label("Stop all users and release old snapshots; consumers remain stopped after replacement.")
                yield Input(placeholder="REPLACE <plan_id>", id="plugin-replace-confirm")
                yield Input(placeholder="QUIESCENT <plan_id>", id="plugin-replace-quiescent")
                yield Button("Execute reviewed replacement", id="plugin-replace-execute", variant="warning")
                yield Button("Cancel replacement review", id="plugin-replace-cancel")
            with TabPane("Composition", id="composition"):
                yield Label("Paste a wagent-compose:v1 code for offline preview")
                yield Input(placeholder="wagent-compose:v1:...", id="composition-code")
                yield Button(
                    "Inspect without loading",
                    id="composition-button",
                    variant="primary",
                )
                yield Input(
                    placeholder=(
                        "Optional explicit plugin-candidate inventory JSON"
                    ),
                    id="composition-inventory",
                )
                yield Button(
                    "Build offline dependency plan",
                    id="composition-plan",
                )
                yield Label(
                    "Locked package installation: plan first; package installation "
                    "and plugin loading require separate approvals."
                )
                yield Input(
                    placeholder="Explicit locked plugin install catalog JSON",
                    id="composition-install-catalog",
                )
                yield Button(
                    "Build locked install plan (offline)",
                    id="composition-install-plan",
                )
                yield Input(
                    placeholder="Exact request digest from install plan",
                    id="composition-install-request",
                )
                yield Input(
                    value="docker",
                    placeholder="docker or unsafe-local",
                    id="composition-install-backend",
                )
                yield Input(
                    value="python:3.11-slim",
                    placeholder="Fixed Docker image",
                    id="composition-install-image",
                )
                yield Input(
                    placeholder=(
                        "Type INSTALL <digest>, or INSTALL LOCAL <digest> for host access"
                    ),
                    id="composition-install-confirm",
                )
                yield Button(
                    "Install exact locked request",
                    id="composition-install",
                    variant="warning",
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
                yield Label("Configured text/media run — Prompt or input file, not both")
                yield Input(value=".wagent/config.json", id="run-config")
                yield Input(placeholder="Prompt", id="run-prompt")
                yield Input(placeholder="User-message JSON file (relative to workspace or absolute)", id="run-input-file")
                yield Checkbox("Send input-file name/metadata / 允许发送输入文件的消息字段", id="run-input-message-fields")
                yield Checkbox("Record current input blocks in Session / 记录当前输入块", id="run-record-inputs")
                yield Checkbox("Also record input names / 另存输入名称", id="run-record-input-name")
                yield Checkbox("Also record input metadata / 另存输入元数据", id="run-record-input-metadata")
                yield Input(placeholder="Type RECORD INPUTS to authorize additional persistence", id="run-record-confirm")
                yield Label("History / 历史: text (default), recorded, none, retrieved, summarized")
                yield Input(value="text", id="run-history")
                yield Input(placeholder="Type SEND HISTORY to authorize recorded media reuse", id="run-history-confirm")
                yield Checkbox("Reuse recorded names / 复用历史名称 (recorded mode)", id="run-history-name")
                yield Checkbox("Reuse recorded metadata / 复用历史元数据 (recorded mode)", id="run-history-metadata")
                yield Label("Text templates / 文本模板: lossy; leave unused settings blank")
                yield Input(placeholder="Explicit retrieval query / 检索词 (retrieved only)", id="run-history-query")
                yield Input(placeholder="Recent Run segments / 近期段数 (templates; default 2)", id="run-history-recent-turns")
                yield Input(placeholder="Older retrieved segments / 检索段数 (retrieved; default 4)", id="run-history-retrieved-turns")
                yield Input(placeholder="Summary characters / 摘要字符 (summarized; default 4096)", id="run-history-summary-chars")
                yield Input(placeholder="Output UTF-8 bytes / 输出字节 (templates; default 65536)", id="run-history-max-bytes")
                yield Input(placeholder="Type TRANSFORM HISTORY to accept lossy text context", id="run-history-transform-confirm")
                yield Label("Knowledge / 知识上下文: named host binding; explicit query, separate from history selection")
                yield Input(placeholder="Knowledge host / 知识宿主 module:factory", id="run-knowledge-entry")
                yield Input(placeholder="Explicit knowledge query / 独立知识检索词", id="run-knowledge-query")
                yield Input(placeholder="Type LOAD KNOWLEDGE to authorize unsandboxed host code", id="run-knowledge-code-confirm")
                yield Input(placeholder="Type QUERY KNOWLEDGE to authorize retrieval and context disclosure", id="run-knowledge-query-confirm")
                yield Input(
                    placeholder="Existing session ID (optional)",
                    id="run-session",
                )
                yield Input(
                    placeholder="Tool entries, comma-separated module:attribute",
                    id="run-tool-entries",
                )
                yield Input(placeholder="Budget host / 预算宿主 module:factory (optional)", id="run-budget-entry")
                yield Input(placeholder="Type LOAD BUDGET to authorize unsandboxed host code", id="run-budget-confirm")
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
                yield Button("Request cancellation / 请求取消", id="run-cancel", variant="warning", disabled=True)
                yield Static("No live events.", id="run-events", classes="panel")
                yield Static(
                    "No configured run started.", id="run-result", classes="panel"
                )
                yield Static("Shared budget not read.", id="run-budget-result", classes="panel")
                yield from _service_usage_widgets("run")
            with TabPane("Replay", id="replay"):
                yield ReplayPanel(self.workspace)
            with TabPane("Checkpoints", id="checkpoints"):
                yield Button("Refresh agent checkpoints", id="checkpoint-refresh")
                yield Static(
                    "Loading agent checkpoints…",
                    id="checkpoint-result",
                    classes="panel",
                )
                yield Label("Read persisted RunEvents (safe metadata only)")
                yield Input(placeholder="Exact run ID", id="checkpoint-replay-run")
                yield Input(value="0", id="checkpoint-replay-after")
                yield Button("Read next event page", id="checkpoint-replay")
                yield Static(
                    "No persisted events read.",
                    id="checkpoint-replay-result",
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
                yield Input(placeholder="Budget host / 预算宿主 module:factory (optional)", id="checkpoint-budget-entry")
                yield Input(placeholder="Type LOAD BUDGET to authorize unsandboxed host code", id="checkpoint-budget-confirm")
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
                yield Static("Shared budget not read.", id="checkpoint-budget-result", classes="panel")
                yield from _service_usage_widgets("checkpoint")
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
                    placeholder="Agent state root (blank = selected workflow state root)",
                    id="workflow-approval-agent-root",
                )
                yield Input(
                    placeholder="Custom approval state keys, comma-separated (optional)",
                    id="workflow-approval-state-keys",
                )
                yield Button(
                    "Review linked Agent approvals (read only)", id="workflow-approval-review"
                )
                yield Static(
                    "No linked approvals reviewed. Review never authorizes execution.",
                    id="workflow-approval-result", classes="panel",
                )
                yield Label(
                    "Approve one linked call and resume its parent (optional). "
                    "Review the actual tool action/arguments separately; matching IDs are not approval."
                )
                for suffix, placeholder in (
                    ("factory", "Approval factory module:attribute (async context manager)"),
                    ("node", "Exact workflow node from the reviewed reference"),
                    ("agent-run", "Exact child Agent run ID"),
                    ("agent-name", "Exact Agent name"),
                    ("call", "Exact pending Call ID"),
                    ("tool", "Exact pending tool name"),
                    ("permissions", "Permissions for this recovery, comma-separated (optional)"),
                    ("confirm", "Type APPROVE <Call ID> for this one call"),
                ):
                    yield Input(placeholder=placeholder, id=f"workflow-approval-{suffix}")
                yield Label(
                    "Both recovery buttons also require LOAD WORKFLOW and RESUME WORKFLOW below. "
                    "Recovery may execute subsequent nodes and billable model calls. "
                    "Factory imports run trusted local Python, not sandboxed code."
                )
                yield Button(
                    "Approve exact call and resume parent", id="workflow-approval-resume",
                    variant="warning",
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
                yield Checkbox(
                    "Run synchronous workflow nodes in threads (optional)",
                    id="workflow-checkpoint-threaded",
                )
                yield Checkbox(
                    "Observe cross-process SQLite pause requests (optional)",
                    id="workflow-checkpoint-external-pause",
                )
                yield Label(
                    "The pause button only controls this recovery. SQLite requests "
                    "persist until explicitly cleared with workflow-pause-clear."
                )
                yield Button(
                    "Pause active workflow at next boundary",
                    id="workflow-checkpoint-pause",
                    disabled=True,
                )
                yield Static(
                    "No active workflow recovery.",
                    id="workflow-control-status",
                    classes="panel",
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
            with TabPane("Approval chains", id="approval-chains"):
                yield Label("Agent → Workflow → Agent: review references, then separately approve both calls")
                yield Label("Review actual actions separately. Matching references are not permission.")
                for suffix, placeholder in (
                    ("parent-root", "Outer Agent state root"),
                    ("workflow-root", "Workflow root (blank = outer Agent root)"),
                    ("child-root", "Inner Agent root (blank = outer Agent root)"),
                    ("run", "Exact outer Agent Run ID"),
                    ("state-keys", "Custom inner approval state keys, comma-separated (optional)"),
                ):
                    yield Input(value=".wagent" if suffix == "parent-root" else "",
                                placeholder=placeholder, id=f"chain-{suffix}")
                yield Button("Review chain (no imports or grants)", id="chain-review")
                yield Static("No chain reviewed.", id="chain-review-result", classes="panel")
                yield Input(placeholder="Explicit review row number, starting at 1", id="chain-row")
                yield Button("Select reviewed row", id="chain-select")
                yield Static("No row selected.", id="chain-selected", classes="panel")
                for suffix, placeholder in (
                    ("factory", "Parent-loop async factory module:attribute"),
                    ("parent-permissions", "Parent permissions, comma-separated"),
                    ("child-permissions", "Child permissions, comma-separated"),
                    ("code-confirm", "Type LOAD AGENT to authorize trusted Python assembly"),
                    ("parent-confirm", "Type APPROVE PARENT <outer Call ID>"),
                    ("child-confirm", "Type APPROVE CHILD <inner Call ID>"),
                    ("resume-confirm", "Type RESUME AGENT <outer Run ID>"),
                ):
                    yield Input(placeholder=placeholder, id=f"chain-{suffix}")
                yield Label("Recovery may run later nodes/tools and billable model calls. Factory owns pause/thread policies.")
                yield Button("Approve both calls and resume outer Agent", id="chain-resume", variant="warning")
                yield Static("No chain recovery started.", id="chain-result", classes="panel")
            with TabPane("Sandbox", id="sandbox"):
                yield Static(
                    "Checking Docker/OCI…", id="sandbox-summary", classes="panel"
                )
            with TabPane("Evaluation", id="evaluation"):
                yield Label("Sequential local evaluation with disposable run state")
                yield Input(
                    placeholder="Evaluation JSON or builtin:<name>[@version]",
                    id="evaluation-dataset",
                )
                yield Input(value=".wagent/config.json", id="evaluation-config")
                yield Input(placeholder="Budget host / 预算宿主 module:factory (optional)", id="evaluation-budget-entry")
                yield Input(placeholder="Type LOAD BUDGET to authorize unsandboxed host code", id="evaluation-budget-confirm")
                yield Input(placeholder="Knowledge host / 知识宿主 module:factory (optional)", id="evaluation-knowledge-entry")
                yield Input(placeholder="Type LOAD KNOWLEDGE to authorize host code", id="evaluation-knowledge-code")
                yield Input(placeholder="Type QUERY ALL CASES to authorize retrieval and evidence for every case", id="evaluation-knowledge-queries")
                yield Input(
                    placeholder="Tool entries, comma-separated module:attribute",
                    id="evaluation-tool-entries",
                )
                yield Input(
                    placeholder="Permissions for this evaluation only, comma-separated",
                    id="evaluation-permissions",
                )
                yield Input(
                    placeholder="Type LOAD EVAL TOOLS to authorize Python imports",
                    id="evaluation-tool-confirm",
                )
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
                yield Static("Shared budget not read.", id="evaluation-budget-result", classes="panel")
                yield from _service_usage_widgets("evaluation")
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

    def on_resize(self, event: Resize) -> None:
        for banner in self.query("#home-banner"):
            banner.update(welcome_banner(max(0, event.size.width - 8), __version__))

    async def on_unmount(self) -> None:
        self._plugin_replacement.cancel()
        self._agent_ui_closing = True
        already_cancelled = self._agent_cancel_requested
        self._agent_cancel_requested = True
        if self._agent_worker is not None:
            if not already_cancelled or not self._agent_started:
                self._agent_worker.cancel()
            try:
                await self._agent_worker.wait()
            except (WorkerCancelled, WorkerFailed):
                pass
        self._agent_busy = False
        self._workflow_ui_closing = True
        if self._workflow_worker is not None:
            self._workflow_worker.cancel()
            try:
                await self._workflow_worker.wait()
            except (WorkerCancelled, WorkerFailed):
                pass
        for batch in reversed(self.installed_plugin_batches):
            await batch.unload()
        self.installed_plugin_batches.clear()
        await self.plugin_manager.close()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composition-button":
            self._inspect_composition()
        elif event.button.id == "composition-plan":
            self._plan_composition()
        elif event.button.id == "composition-install-plan":
            self._plan_plugin_installation()
        elif event.button.id == "composition-install":
            await self._install_plugin_package()
        elif event.button.id == "plugin-preview":
            self._preview_plugins()
        elif event.button.id == "plugin-load":
            await self._load_plugins()
        elif event.button.id == "plugin-installed-load":
            await self._load_installed_plugin()
        elif event.button.id == "plugin-refresh":
            self._refresh_plugins()
        elif event.button.id == "plugin-unload":
            await self._unload_plugin()
        elif event.button.id == "plugin-replace-inspect":
            self._inspect_plugin_replacement()
        elif event.button.id == "plugin-replace-prepare":
            await self._prepare_plugin_replacement()
        elif event.button.id == "plugin-replace-execute":
            await self._execute_plugin_replacement()
        elif event.button.id == "plugin-replace-cancel":
            self._cancel_plugin_replacement()
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
            self._start_configured_agent()
        elif event.button.id == "run-cancel":
            self._cancel_configured_agent()
        elif event.button.id == "checkpoint-refresh":
            await self._refresh_checkpoints()
        elif event.button.id == "checkpoint-replay":
            await self._replay_run_events()
        elif event.button.id == "checkpoint-resume":
            await self._resume_configured_agent()
        elif event.button.id == "workflow-checkpoint-refresh":
            await self._refresh_workflow_checkpoints()
        elif event.button.id == "workflow-approval-review":
            await self._review_workflow_approvals()
        elif event.button.id == "workflow-checkpoint-resume":
            self._start_workflow_resume()
        elif event.button.id == "workflow-approval-resume":
            self._start_workflow_resume(approve=True)
        elif event.button.id == "workflow-checkpoint-pause":
            self._request_workflow_pause()
        elif event.button.id == "evaluation-button":
            await self._run_evaluation()
        elif event.button.id == "chain-review":
            self._start_chain_operation(review=True)
        elif event.button.id == "chain-select":
            self._select_chain_row()
        elif event.button.id == "chain-resume":
            self._start_chain_operation(review=False)

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

    def _plan_composition(self) -> None:
        code = self.query_one("#composition-code", Input).value.strip()
        target = self.query_one("#composition-result", Static)
        inventory_value = self.query_one(
            "#composition-inventory",
            Input,
        ).value.strip()
        try:
            preview = inspect_composition(code)
            if inventory_value:
                candidates = load_plugin_candidates(
                    self._workspace_path(inventory_value)
                )
            else:
                candidates = tuple(
                    PluginCandidate(record.spec.name, record.spec.version)
                    for record in self.plugin_manager.records()
                    if record.state.value == "active"
                )
            plan = plan_composition(
                preview.manifest,
                CompositionEnvironment(platform.python_version(), __version__),
                StaticCompositionDependencyResolver(candidates),
            )
        except (CompositionError, OSError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        lines = [
            f"Composition: {plan.name}@{plan.version}",
            f"Digest: {plan.digest}",
            (
                f"Python {plan.environment.python_version}: "
                f"compatible={plan.python_compatible}"
            ),
            (
                f"W-Agent {plan.environment.wagent_version}: "
                f"compatible={plan.wagent_compatible}"
            ),
            f"Ready: {plan.ready}",
            f"Plugin load confirmation required: {plan.load_confirmation_required}",
        ]
        lines.extend(
            (
                f"{item.requirement.name}{item.requirement.version} | "
                f"source={item.requirement.source or '-'} | "
                f"action={item.action.value} | "
                "selected="
                f"{item.candidate.version if item.candidate is not None else '-'}"
            )
            for item in plan.plugins
        )
        lines.append("No package was installed and no plugin code was imported.")
        target.update("\n".join(lines))

    def _plan_plugin_installation(self) -> None:
        target = self.query_one("#composition-result", Static)
        try:
            install_plan = self._current_plugin_install_plan()
        except (CompositionError, OSError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        target.update(
            json.dumps(
                plugin_installation_plan_to_dict(install_plan),
                ensure_ascii=False,
                indent=2,
            )
            + "\nNo network was accessed and no package or plugin code was executed."
        )

    async def _install_plugin_package(self) -> None:
        target = self.query_one("#composition-result", Static)
        request_digest = self.query_one(
            "#composition-install-request",
            Input,
        ).value.strip()
        backend = self.query_one(
            "#composition-install-backend",
            Input,
        ).value.strip().lower()
        confirmation = self.query_one("#composition-install-confirm", Input)
        expected = (
            f"INSTALL LOCAL {request_digest}"
            if backend == "unsafe-local"
            else f"INSTALL {request_digest}"
        )
        if not request_digest or confirmation.value.strip() != expected:
            target.update(f"Rejected: type {expected} to authorize this exact request")
            return
        confirmation.value = ""
        try:
            install_plan = self._current_plugin_install_plan()
            if install_plan.blockers:
                reasons = ", ".join(item.reason for item in install_plan.blockers)
                raise PluginInstallationError(
                    f"installation plan is blocked: {reasons}"
                )
            matches = [
                item for item in install_plan.requests if item.digest == request_digest
            ]
            if len(matches) != 1:
                raise PluginInstallationError(
                    "request digest is absent or ambiguous; rebuild the plan"
                )
            request = matches[0]
            authorization = PluginInstallAuthorization.grant(
                request.digest,
                "tui",
                acknowledge_network_access=True,
                acknowledge_package_code=True,
            )
            if backend not in {"docker", "unsafe-local"}:
                raise ValueError("plugin install backend must be docker or unsafe-local")
            state_root = (self.workspace / ".wagent").resolve()
            state_root.mkdir(parents=True, exist_ok=True)
            if backend == "docker":
                image = self.query_one(
                    "#composition-install-image",
                    Input,
                ).value.strip()
                provider = DockerSandboxProvider()
                sandbox = SandboxSpec(
                    state_root,
                    image=image,
                    network=SandboxNetwork.BRIDGE,
                    user=recommended_docker_install_user(),
                )
                executable = "python"
            elif backend == "unsafe-local":
                local_authorization = UnsafeLocalAuthorization.grant(
                    "plugin-install-tui",
                    acknowledge_host_access=True,
                )
                provider = UnsafeLocalSandboxProvider(local_authorization)
                sandbox = SandboxSpec(
                    state_root,
                    network=SandboxNetwork.BRIDGE,
                    inherit_host_environment=True,
                )
                executable = sys.executable
            target.update("Installing exact locked request in the selected sandbox…")
            result = await SandboxPipPackageInstaller(
                provider,
                sandbox,
                python_executable=executable,
            ).install(request, authorization)
        except (
            CompositionError,
            OSError,
            PermissionError,
            PluginInstallationError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Package installation failed: {type(error).__name__}")
            return
        target.update(
            "Installed locked plugin package. Plugin code was not loaded.\n"
            f"Plugin: {result.plugin_name}@{result.plugin_version}\n"
            f"Request: {result.request_digest}\n"
            f"Tree: {result.tree_digest}\n"
            f"Path: {result.target}\n"
            "Use Plugins > Load verified installed plugin for separate code approval."
        )
        self.query_one("#plugin-installed-path", Input).value = str(result.target)

    def _current_plugin_install_plan(self):
        code = self.query_one("#composition-code", Input).value.strip()
        catalog_value = self.query_one(
            "#composition-install-catalog",
            Input,
        ).value.strip()
        if not catalog_value:
            raise ValueError("an explicit plugin install catalog is required")
        inventory_value = self.query_one(
            "#composition-inventory",
            Input,
        ).value.strip()
        preview = inspect_composition(code)
        if inventory_value:
            candidates = load_plugin_candidates(self._workspace_path(inventory_value))
        else:
            candidates = tuple(
                PluginCandidate(record.spec.name, record.spec.version)
                for record in self.plugin_manager.records()
                if record.state.value == "active"
            )
        dependency_plan = plan_composition(
            preview.manifest,
            CompositionEnvironment(platform.python_version(), __version__),
            StaticCompositionDependencyResolver(candidates),
        )
        return plan_plugin_installations(
            dependency_plan,
            load_plugin_install_catalog(self._workspace_path(catalog_value)),
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

    async def _load_installed_plugin(self) -> None:
        target = self.query_one("#plugin-result", Static)
        confirmation = self.query_one("#plugin-installed-confirm", Input)
        if confirmation.value.strip() != "LOAD INSTALLED":
            target.update(
                "Rejected: type LOAD INSTALLED to authorize installed plugin code"
            )
            return
        confirmation.value = ""
        path_value = self.query_one("#plugin-installed-path", Input).value.strip()
        if not path_value:
            target.update("Rejected: installed plugin directory is required")
            return
        try:
            installation = load_plugin_install_result(
                self._workspace_path(path_value)
            )
            batch = await load_installed_plugin_references(
                self.plugin_manager,
                (InstalledPluginReference(installation),),
            )
        except (
            OSError,
            PluginInstallationError,
            PluginLoadError,
            ValueError,
        ) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Installed plugin load failed: {type(error).__name__}")
            return
        self.installed_plugin_batches.append(batch)
        self._refresh_plugins(prefix="Verified installed plugin loaded.\n")

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
            await self._release_disposed_installed_batches()
        except (KeyError, PluginUnloadError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Plugin unload failed: {type(error).__name__}")
            return
        self._refresh_plugins(prefix=f"Unloaded {name} and active dependents.\n")

    def _cancel_plugin_replacement(self) -> None:
        self._plugin_replacement.cancel()
        self._plugin_replacement_source = None
        for selector in ("#plugin-replace-import-confirm", "#plugin-replace-confirm", "#plugin-replace-quiescent"):
            self.query_one(selector, Input).value = ""
        self.query_one("#plugin-replace-result", Static).update(
            "Replacement review cancelled. Imported Python code/side effects cannot be undone."
        )

    def _inspect_plugin_replacement(self) -> None:
        self._cancel_plugin_replacement()
        source = self.query_one("#plugin-replace-config", Input).value.strip()
        try:
            if not source:
                raise ValueError("replacement config required")
            payload = self._plugin_replacement.inspect(self._workspace_path(source))
            self._plugin_replacement_source = source
        except Exception as error:
            self.query_one("#plugin-replace-result", Static).update(f"Inspection failed: {type(error).__name__}")
            return
        self.query_one("#plugin-replace-result", Static).update(json.dumps(payload, ensure_ascii=False, indent=2))

    def _check_plugin_replacement_input(self) -> None:
        if self.query_one("#plugin-replace-config", Input).value.strip() != self._plugin_replacement_source:
            self._cancel_plugin_replacement()
            raise ValueError("replacement path changed; inspect again")

    async def _prepare_plugin_replacement(self) -> None:
        confirmation = self.query_one("#plugin-replace-import-confirm", Input)
        phrase = confirmation.value.strip()
        confirmation.value = ""
        try:
            self._check_plugin_replacement_input()
            payload = await self._plugin_replacement.prepare(import_confirmation=phrase)
        except Exception as error:
            self._plugin_replacement.cancel()
            self.query_one("#plugin-replace-result", Static).update(f"Plan failed: {type(error).__name__}. Inspect again.")
            return
        self.query_one("#plugin-replace-result", Static).update(json.dumps(payload, ensure_ascii=False, indent=2))

    async def _execute_plugin_replacement(self) -> None:
        confirmation = self.query_one("#plugin-replace-confirm", Input)
        quiescent = self.query_one("#plugin-replace-quiescent", Input)
        replace_phrase, quiescent_phrase = confirmation.value.strip(), quiescent.value.strip()
        confirmation.value = quiescent.value = ""
        busy = (
            self._plugin_replacement_busy or self._agent_busy or self._chain_busy
            or self._active_workflow is not None or getattr(self, "_evaluation_busy", False)
            or any(worker is not None and not worker.is_finished
                   for worker in (self._agent_worker, self._workflow_worker))
        )
        blocked_names = frozenset(handle.name for batch in self.installed_plugin_batches for handle in batch.handles)
        self._plugin_replacement_busy = True
        try:
            self._check_plugin_replacement_input()
            payload = await self._plugin_replacement.execute(
                replace_confirmation=replace_phrase, quiescent_confirmation=quiescent_phrase,
                host_busy=busy, blocked_names=blocked_names,
            )
            self._refresh_plugins(prefix="Replaced in this TUI process only; consumers remain stopped.\n")
        except Exception as error:
            self._plugin_replacement.cancel()
            self._refresh_plugins(prefix="Replacement did not complete; inspect lifecycle states.\n")
            self.query_one("#plugin-replace-result", Static).update(
                f"Replacement failed: {type(error).__name__}. No automatic rollback; inspect again."
            )
            return
        finally:
            self._plugin_replacement_busy = False
            self._plugin_replacement_source = None
        self.query_one("#plugin-replace-result", Static).update(json.dumps(payload, ensure_ascii=False, indent=2))

    async def _release_disposed_installed_batches(self) -> None:
        active_batches: list[InstalledPluginBatch] = []
        for batch in self.installed_plugin_batches:
            if all(
                self.plugin_manager.record(handle.name).state.value
                in {"disposed", "failed"}
                for handle in batch.handles
            ):
                await batch.unload()
            else:
                active_batches.append(batch)
        self.installed_plugin_batches = active_batches

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
        try:
            usage_options = self._capture_service_usage("provider-probe")
        except ValueError as error:
            target.update(Text(f"Rejected: {error}"))
            return
        self.query_one("#provider-probe-budget-result", Static).update(Text("Shared budget not read for this attempt."))
        budget_entry = self.query_one("#provider-probe-budget-entry", Input).value.strip() or None
        budget_confirmation = self.query_one("#provider-probe-budget-confirm", Input)
        budget_authorized = budget_confirmation.value.strip() == "LOAD BUDGET"
        budget_confirmation.value = ""
        if budget_entry is not None and not budget_authorized:
            target.update(Text("Rejected: type LOAD BUDGET to authorize unsandboxed budget host code"))
            return
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
            selection = getattr(config, "shared_budget", None)
            usage_selection = getattr(config, "service_usage", None)
            async with (
                budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                     confirmed=budget_authorized) as bindings,
                service_usage_binding_scope(usage_options.entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=usage_options.confirm_code, confirm_record=usage_options.confirm_record) as usage_bindings,
            ):
                assembly = assemble_local_provider(
                    config, **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if usage_options.entry is not None else {}),
                )
                async with assembly:
                    result = await ModelProviderProbe().probe(
                        assembly.name, assembly.provider,
                        mode=ProbeMode.ACTIVE if active else ProbeMode.SAFE,
                        allow_active=active, model=config.provider.model,
                    )
                budget = await shared_budget_summary(getattr(assembly, "shared_budget", None))
                service_summary = await service_usage_summary(getattr(assembly, "service_usage", None))
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
        self._show_shared_budget("provider-probe", budget)
        self._show_service_usage("provider-probe", service_summary)

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
        summaries = await self.sessions.agent_usage(include_archived=True)
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
        if summaries:
            usage_lines = [
                (
                    f"{summary.agent_name} | sessions={summary.session_count} | "
                    f"runs={summary.run_count} | attempts={summary.model_calls} | "
                    f"tokens={summary.usage.total_tokens} | "
                    f"usage_complete={str(summary.usage_complete).lower()} | "
                    f"cost={_cost_text(summary.cost, complete=summary.cost_complete)}"
                )
                for summary in summaries
            ]
            body += "\n\nAgent usage:\n" + "\n".join(usage_lines)
        targets = list(self.query("#session-result"))
        if targets:
            target = targets[0]
            if isinstance(target, Static):
                target.update(prefix + body)

    async def _replay_run_events(self) -> None:
        """Read one persisted page without exposing model or tool content."""

        target = self.query_one("#checkpoint-replay-result", Static)
        run_id = self.query_one("#checkpoint-replay-run", Input).value.strip()
        after_input = self.query_one("#checkpoint-replay-after", Input)
        try:
            cursor = RunEventCursor(run_id, int(after_input.value.strip()))
            page = await RunEventReplay(self.runs).projected_page(
                run_id,
                cursor=cursor,
                limit=100,
            )
        except (OSError, RunStoreError, ValueError) as error:
            target.update(Text(f"Rejected: {error}"))
            return
        lines = [
            f"Run: {run_id} | next={page.next_cursor.sequence} | "
            f"has_more={str(page.has_more).lower()}"
        ]
        lines.extend(
            json.dumps(event, ensure_ascii=False)
            for event in page.events
        )
        if not page.events:
            lines.append("No new persisted events at this cursor.")
        after_input.value = str(page.next_cursor.sequence)
        target.update(Text("\n".join(lines)))

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

    async def _review_workflow_approvals(self) -> None:
        target = self.query_one("#workflow-approval-result", Static)
        run_id = self.query_one("#workflow-checkpoint-run", Input).value.strip()
        root_value = self.query_one("#workflow-checkpoint-state-root", Input).value.strip()
        agent_value = self.query_one("#workflow-approval-agent-root", Input).value.strip()
        if not run_id or not root_value:
            target.update("Review rejected: workflow run ID and state root are required.")
            return
        try:
            keys = _split_values(self.query_one("#workflow-approval-state-keys", Input).value)
            root = self._workspace_path(root_value)
            agent_root = self._workspace_path(agent_value) if agent_value else root
            if not (root / "workflows").is_dir() or not (agent_root / "runs").is_dir():
                target.update("Review rejected: select existing Workflow and Agent state roots.")
                return
            reviews = await review_workflow_approvals(
                JsonlWorkflowStore(root), JsonlRunStore(agent_root), run_id,
                state_keys=keys or None,
            )
        except (OSError, ValueError, WorkflowStoreError, RunStoreError, AgentWorkflowAdapterError) as error:
            target.update(f"Approval review failed: {type(error).__name__}")
            return
        target.update(Text(
            f"Reviewed parent: {run_id}\nWorkflow root: {root}\nAgent root: {agent_root}\n"
            "Read-only snapshots, not permission or proof of an active process.\n"
            + json.dumps([item.to_dict() for item in reviews], ensure_ascii=False, indent=2)
        ))

    def _capture_agent_run(self) -> _AgentRunRequest | None:
        target = self.query_one("#run-result", Static)
        self.query_one("#run-budget-result", Static).update(Text("Shared budget not read for this attempt."))
        confirmations = {name: self.query_one(f"#run-{name}", Input).value.strip() for name in _RUN_CONFIRMATIONS}
        for name in _RUN_CONFIRMATIONS:
            self.query_one(f"#run-{name}", Input).value = ""
        try:
            service_usage = self._capture_service_usage("run")
            if confirmations["confirm"] != "RUN":
                raise ValueError("type RUN to authorize the model call")
            entries = _split_values(self.query_one("#run-tool-entries", Input).value)
            budget_entry = self.query_one("#run-budget-entry", Input).value.strip() or None
            if budget_entry is not None and confirmations["budget-confirm"] != "LOAD BUDGET":
                raise ValueError("type LOAD BUDGET to authorize unsandboxed budget host code")
            permissions = frozenset(_split_values(self.query_one("#run-permissions", Input).value))
            if entries and confirmations["tool-confirm"] != "LOAD TOOLS":
                raise ValueError("type LOAD TOOLS to authorize developer Python imports")
            record = self.query_one("#run-record-inputs", Checkbox).value
            if record and confirmations["record-confirm"] != "RECORD INPUTS":
                raise ValueError("type RECORD INPUTS to authorize additional Session recording")
            history = self.query_one("#run-history", Input).value.strip()
            if history == "recorded" and confirmations["history-confirm"] != "SEND HISTORY":
                raise ValueError("type SEND HISTORY to authorize recorded media reuse")
            if history in {"retrieved", "summarized"} and confirmations["history-transform-confirm"] != "TRANSFORM HISTORY":
                raise ValueError("type TRANSFORM HISTORY to accept lossy text context")
            history_options = BuiltinSessionHistoryOptions(
                mode=history,
                query=self.query_one("#run-history-query", Input).value.strip() or None,
                recent_turns=self._history_integer("recent-turns"),
                retrieved_turns=self._history_integer("retrieved-turns"),
                summary_chars=self._history_integer("summary-chars"),
                max_output_bytes=self._history_integer("max-bytes"),
                include_name=self.query_one("#run-history-name", Checkbox).value,
                include_metadata=self.query_one("#run-history-metadata", Checkbox).value,
            )
            knowledge = KnowledgeRunOptions(
                self.query_one("#run-knowledge-entry", Input).value.strip() or None,
                self.query_one("#run-knowledge-query", Input).value or None,
                confirm_code=confirmations["knowledge-code-confirm"] == "LOAD KNOWLEDGE",
                confirm_query=confirmations["knowledge-query-confirm"] == "QUERY KNOWLEDGE",
            )
            prompt = self.query_one("#run-prompt", Input).value
            input_file = self.query_one("#run-input-file", Input).value.strip()
            if bool(prompt) == bool(input_file):
                raise ValueError("provide exactly one Prompt or input file")
            allow_fields = self.query_one("#run-input-message-fields", Checkbox).value
            record_name = self.query_one("#run-record-input-name", Checkbox).value
            record_metadata = self.query_one("#run-record-input-metadata", Checkbox).value
            if allow_fields and not input_file:
                raise ValueError("input message fields require an input file")
            if (record_name or record_metadata) and (not record or not allow_fields):
                raise ValueError("field recording requires input-field sending and input recording")
            input_recorder = (MessageFieldsSessionInputRecorder(
                include_name=record_name, include_metadata=record_metadata,
            ) if record_name or record_metadata else None)
            config = self.query_one("#run-config", Input).value.strip()
            if not config:
                raise ValueError("config path is required")
            return _AgentRunRequest(
                self._workspace_path(config), prompt,
                self._workspace_path(input_file) if input_file else None,
                self.query_one("#run-session", Input).value.strip() or None,
                entries, permissions, record, history_options, allow_fields, input_recorder, budget_entry, knowledge, service_usage,
            )
        except ValueError as error:
            target.update(Text(f"Rejected: {error}"))
            return None

    def _history_integer(self, field: str) -> int | None:
        value = self.query_one(f"#run-history-{field}", Input).value.strip()
        if not value:
            return None
        if len(value) > 12 or not value.isascii() or not value.isdecimal():
            raise ValueError("history numeric settings must be unsigned decimal integers")
        return int(value)

    def _lock_agent_run(self, locked: bool) -> None:
        for name in _RUN_FIELDS:
            self.query_one(f"#run-{name}").disabled = locked
        self.query_one("#run-button", Button).disabled = locked
        self.query_one("#run-cancel", Button).disabled = not locked

    def _begin_agent_run(self) -> _AgentRunRequest | None:
        if self._agent_ui_closing or self._agent_busy or (
            self._agent_worker is not None and not self._agent_worker.is_finished
        ):
            return None
        request = self._capture_agent_run()
        if request is not None:
            self._agent_busy = True
            self._agent_started = False
            self._agent_cancel_requested = False
            self._lock_agent_run(True)
        return request

    def _start_configured_agent(self) -> None:
        request = self._begin_agent_run()
        if request is not None:
            self._agent_worker = self.run_worker(
                self._execute_agent_run(request), name="configured-agent",
                group="configured-agent", exclusive=False, exit_on_error=False,
            )

    async def _run_configured_agent(self) -> None:
        """Awaitable adapter retained for embedders and focused UI tests."""
        request = self._begin_agent_run()
        if request is not None:
            await self._execute_agent_run(request)

    def _cancel_configured_agent(self) -> None:
        if not self._agent_busy or self._agent_ui_closing or self._agent_cancel_requested:
            return
        self._agent_cancel_requested = True
        # A not-yet-started coroutine must run its finally block to unlock fields.
        if self._agent_started and self._agent_worker is not None:
            self._agent_worker.cancel()
        self.query_one("#run-result", Static).update(Text(
            "Cancellation requested. Already-started actions may have side effects."
        ))

    async def _execute_agent_run(self, request: _AgentRunRequest) -> None:
        self._agent_started = True
        target = self.query_one("#run-result", Static)
        event_target = self.query_one("#run-events", Static)
        event_lines: list[str] = []

        async def show_event(event: RunEvent) -> None:
            if self._agent_ui_closing:
                return
            event_lines.append(_event_text(event))
            del event_lines[:-200]
            event_target.update(Text("\n".join(event_lines)))

        try:
            if self._agent_cancel_requested or self._agent_ui_closing:
                raise asyncio.CancelledError
            target.update(Text("Running configured agent…"))
            self.query_one("#run-budget-result", Static).update(Text("Shared budget not read for this attempt."))
            event_target.update(Text("Waiting for the first event…"))
            messages = (await asyncio.to_thread(load_input_manifest, request.input_file,
                        **({"allow_message_fields": True} if request.allow_message_fields else {}))
                        if request.input_file is not None else None)
            if self._agent_cancel_requested or self._agent_ui_closing:
                raise asyncio.CancelledError
            catalog = load_tool_entries(request.tool_entries) if request.tool_entries else {}
            config = load_local_runtime_config(request.config)
            selection = getattr(config, "shared_budget", None)
            usage_selection = getattr(config, "service_usage", None)
            knowledge_selection = getattr(config, "knowledge", None)
            async with (
                budget_binding_scope(request.budget_entry, selected=selection.binding if selection else None,
                                     confirmed=True) as bindings,
                knowledge_binding_scope(request.knowledge, selected=knowledge_selection.binding if knowledge_selection else None) as knowledge_bindings,
                service_usage_binding_scope(request.service_usage.entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=request.service_usage.confirm_code, confirm_record=request.service_usage.confirm_record) as usage_bindings,
            ):
                runtime = open_local_runtime(
                    config, self.workspace / ".wagent", tool_bindings=catalog,
                    **({"shared_budget_bindings": bindings} if request.budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if request.service_usage.entry is not None else {}),
                    **({"knowledge_bindings": knowledge_bindings} if request.knowledge.entry is not None else {}),
                )
                async with runtime:
                    options = {"session_id": request.session_id, "permissions": request.permissions,
                               "event_callback": show_event}
                    if request.record_inputs:
                        options["record_inputs"] = True
                    if request.input_recorder is not None:
                        options["input_recorder"] = request.input_recorder
                    options.update(request.history.runtime_options())
                    options.update(request.knowledge.runtime_options())
                    run = (await runtime.run_messages(messages, **options) if messages is not None
                           else await runtime.run(request.prompt, **options))
                budget = await shared_budget_summary(getattr(runtime, "shared_budget", None))
                service_summary = await service_usage_summary(getattr(runtime, "service_usage", None))
            if self._agent_ui_closing:
                return
            self._show_run_result(target, run)
            self._show_shared_budget("run", budget)
            self._show_service_usage("run", service_summary)
            self.query_one("#run-session", Input).value = run.session.session_id
            self._select_pending_checkpoint(run)
            await self._refresh_sessions()
            await self._refresh_checkpoints()
        except asyncio.CancelledError:
            if not self._agent_ui_closing:
                target.update(Text("Run cancelled; inspect persisted state before retrying. No automatic replay."))
            raise
        except BudgetEntryError as error:
            if not self._agent_ui_closing:
                target.update(Text(f"Budget host failed: {error}"))
        except InputManifestError:
            if not self._agent_ui_closing:
                target.update(Text("Rejected: input file is invalid, unavailable or oversized; no model call started."))
        except Exception as error:
            if not self._agent_ui_closing:
                target.update(Text(f"Run failed: {type(error).__name__}; inspect persisted state before retrying."))
        finally:
            self._agent_busy = False
            self._agent_started = False
            if not self._agent_ui_closing:
                self._lock_agent_run(False)

    async def _resume_configured_agent(self) -> None:
        target = self.query_one("#checkpoint-resume-result", Static)
        try:
            usage_options = self._capture_service_usage("checkpoint")
        except ValueError as error:
            target.update(Text(f"Rejected: {error}"))
            return
        self.query_one("#checkpoint-budget-result", Static).update(Text("Shared budget not read for this attempt."))
        budget_entry = self.query_one("#checkpoint-budget-entry", Input).value.strip() or None
        budget_confirmation = self.query_one("#checkpoint-budget-confirm", Input)
        budget_authorized = budget_confirmation.value.strip() == "LOAD BUDGET"
        budget_confirmation.value = ""
        if budget_entry is not None and not budget_authorized:
            target.update(Text("Rejected: type LOAD BUDGET to authorize unsandboxed budget host code"))
            return
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
        self.query_one("#checkpoint-budget-result", Static).update(Text("Shared budget not read for this attempt."))
        event_target.update("Waiting for the first resumed event…")
        try:
            catalog = load_tool_entries(tool_entries) if tool_entries else {}
            config = load_local_runtime_config(source)
            selection = getattr(config, "shared_budget", None)
            usage_selection = getattr(config, "service_usage", None)
            async with (
                budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                     confirmed=budget_authorized) as bindings,
                service_usage_binding_scope(usage_options.entry, selected=usage_selection.binding if usage_selection else None,
                                            confirmed=usage_options.confirm_code, confirm_record=usage_options.confirm_record) as usage_bindings,
            ):
                runtime = open_local_runtime(
                    config, self.workspace / ".wagent", tool_bindings=catalog,
                    **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                    **({"service_usage_bindings": usage_bindings} if usage_options.entry is not None else {}),
                )
                async with runtime:
                    run = await runtime.resume(
                        session_id, run_id, permissions=permissions,
                        approved_call_ids=frozenset({call_id}), event_callback=show_event,
                    )
                budget = await shared_budget_summary(getattr(runtime, "shared_budget", None))
                service_summary = await service_usage_summary(getattr(runtime, "service_usage", None))
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
        self._show_shared_budget("checkpoint", budget)
        self._show_service_usage("checkpoint", service_summary)
        self._select_pending_checkpoint(run)
        await self._refresh_sessions()
        await self._refresh_checkpoints()

    def _show_shared_budget(self, prefix: str, budget: dict | None) -> None:
        message = ("Shared budget not enabled." if budget is None else
                   "Shared pool / 共享池（不是本次 Run）\n" + json.dumps(budget, ensure_ascii=False, indent=2))
        self.query_one(f"#{prefix}-budget-result", Static).update(Text(message))

    def _capture_service_usage(self, prefix: str) -> ServiceUsageOptions:
        self.query_one(f"#{prefix}-usage-result", Static).update(Text("Service usage not read for this attempt."))
        code = self.query_one(f"#{prefix}-usage-code", Input)
        record = self.query_one(f"#{prefix}-usage-record", Input)
        code_value, record_value = code.value, record.value
        code.value = record.value = ""
        if code_value not in {"", "LOAD USAGE"} or record_value not in {"", "RECORD USAGE"}:
            raise ValueError("usage confirmation phrase is invalid")
        return ServiceUsageOptions(
            self.query_one(f"#{prefix}-usage-entry", Input).value.strip() or None,
            code_value == "LOAD USAGE", record_value == "RECORD USAGE",
        )

    def _show_service_usage(self, prefix: str, summary: dict | None) -> None:
        message = ("Service usage not enabled." if summary is None else
                   "Usage / 用量（宿主 operation 范围，非本次 Run）\n" + json.dumps(summary, ensure_ascii=True, indent=2))
        self.query_one(f"#{prefix}-usage-result", Static).update(Text(message))

    def _chain_value(self, suffix: str) -> str:
        return self.query_one(f"#chain-{suffix}", Input).value.strip()

    def _clear_chain_confirmations(self) -> None:
        for suffix in _CHAIN_CONFIRMATIONS:
            self.query_one(f"#chain-{suffix}", Input).value = ""

    def _chain_query(self) -> _ChainQuery:
        root_value, run_id = self._chain_value("parent-root"), self._chain_value("run")
        if not root_value or not run_id:
            raise ValueError("outer Agent root and Run ID are required")
        parent = self._workspace_path(root_value).resolve()
        workflow = self._workspace_path(self._chain_value("workflow-root")).resolve() if self._chain_value("workflow-root") else parent
        child = self._workspace_path(self._chain_value("child-root")).resolve() if self._chain_value("child-root") else parent
        if not all(path.is_dir() for path in (parent / "runs", workflow / "workflows", child / "runs")):
            raise ValueError("select existing state directories for all three stores")
        return _ChainQuery(parent, workflow, child, run_id, _split_values(self._chain_value("state-keys")))

    def _lock_chain_controls(self):
        widgets = [self.query_one(f"#chain-{suffix}") for suffix in (*_CHAIN_FIELDS, "review", "select", "resume")]
        widgets.extend(self.query_one(f"#{name}") for name in (
            "workflow-checkpoint-resume", "workflow-approval-resume", "checkpoint-resume", "run-button",
        ))
        states = [(widget, widget.disabled) for widget in widgets]
        for widget in widgets:
            widget.disabled = True
        return states

    def _start_chain_operation(self, *, review: bool) -> None:
        if self._workflow_ui_closing or self._chain_busy or self._active_workflow is not None or (
            self._workflow_worker is not None and not self._workflow_worker.is_finished
        ):
            return
        self._workflow_worker = self.run_worker(
            self._review_chain() if review else self._resume_chain(),
            name="approval-chain", group="workflow-resume", exclusive=False, exit_on_error=False,
        )

    async def _review_chain(self) -> None:
        if self._chain_busy or self._active_workflow is not None or self._workflow_ui_closing:
            return
        target = self.query_one("#chain-review-result", Static)
        self._chain_review = None
        self._chain_selection = None
        self._clear_chain_confirmations()
        self.query_one("#chain-row", Input).value = ""
        self.query_one("#chain-selected", Static).update("No row selected.")
        try:
            query = self._chain_query()
        except (ValueError, OSError) as error:
            target.update(f"Review rejected: {type(error).__name__}")
            return
        self._chain_busy = True
        states = self._lock_chain_controls()
        try:
            reviews = await review_workflow_tool_approvals(
                JsonlRunStore(query.parent_root), JsonlWorkflowStore(query.workflow_root),
                JsonlRunStore(query.child_root), query.run_id, state_keys=query.state_keys or None,
            )
            if self._workflow_ui_closing:
                return
            if self._chain_query() != query:
                raise ValueError("review inputs changed")
            self._chain_review = (query, reviews)
            target.update(Text(
                "Read-only snapshots; no code loaded or authority granted.\n"
                + (json.dumps([{"row": index, **item.to_dict()} for index, item in enumerate(reviews, 1)],
                              ensure_ascii=False, indent=2) if reviews else
                   "No linked inner approvals. This does not prove completion.")
            ))
        except asyncio.CancelledError:
            if not self._workflow_ui_closing:
                target.update("Review interrupted; query again.")
            raise
        except Exception as error:
            if not self._workflow_ui_closing:
                target.update(f"Chain review failed: {type(error).__name__}")
        finally:
            self._chain_busy = False
            if not self._workflow_ui_closing:
                for widget, disabled in states:
                    widget.disabled = disabled

    def _select_chain_row(self) -> None:
        if self._chain_busy or self._workflow_ui_closing:
            return
        self._chain_selection = None
        self._clear_chain_confirmations()
        target = self.query_one("#chain-selected", Static)
        try:
            if self._chain_review is None or self._chain_review[0] != self._chain_query():
                raise ValueError("query the current chain first")
            row = int(self._chain_value("row"))
            reviews = self._chain_review[1]
            if row < 1 or row > len(reviews):
                raise ValueError("select an existing row")
            selected = reviews[row - 1]
            if selected.child.link_status is not WorkflowApprovalLinkStatus.MATCHED:
                raise ValueError("selected row is not a matching pending approval")
            self._chain_selection = (row, selected)
            target.update(Text(
                f"Selected row {row}; sequence {selected.sequence}. Review actual actions separately.\n"
                + json.dumps(selected.to_dict(), ensure_ascii=False, indent=2)
            ))
        except (ValueError, OSError) as error:
            target.update(f"Selection rejected: {type(error).__name__}; review and select again.")

    async def _resume_chain(self) -> None:
        if self._chain_busy or self._active_workflow is not None or self._workflow_ui_closing:
            return
        target = self.query_one("#chain-result", Static)
        try:
            query = self._chain_query()
            if self._chain_review is None or self._chain_review[0] != query or self._chain_selection is None:
                raise ValueError("review and select the current chain first")
            row, selected = self._chain_selection
            if row != int(self._chain_value("row")):
                raise ValueError("select the edited row before authorizing")
            factory = self._chain_value("factory")
            if not factory:
                raise ValueError("parent-loop factory is required")
            required = {
                "code-confirm": "LOAD AGENT",
                "parent-confirm": f"APPROVE PARENT {selected.parent.call_id}",
                "child-confirm": f"APPROVE CHILD {selected.child.reference.call_id}",
                "resume-confirm": f"RESUME AGENT {selected.parent.agent_run_id}",
            }
            if any(self._chain_value(key) != value for key, value in required.items()):
                raise ValueError("all four exact confirmations are required")
            parent_permissions = frozenset(_split_values(self._chain_value("parent-permissions")))
            child_permissions = frozenset(_split_values(self._chain_value("child-permissions")))
        except (ValueError, OSError) as error:
            target.update(f"Recovery rejected: {type(error).__name__}; check selection and four confirmations.")
            return
        # Freeze the request before yielding and discard UI authority immediately.
        self._chain_busy = True
        self._chain_review = None
        self._chain_selection = None
        self._clear_chain_confirmations()
        self.query_one("#chain-row", Input).value = ""
        self.query_one("#chain-selected", Static).update("Selection consumed; review again after recovery.")
        states = self._lock_chain_controls()
        target.update("Recovering outer Agent; confirmation applies to this operation only…")
        try:
            result = await resume_workflow_tool_approval(
                JsonlRunStore(query.parent_root), JsonlWorkflowStore(query.workflow_root),
                JsonlRunStore(query.child_root), selected,
                lambda context: open_workflow_tool_approval_entry(factory, context),
                parent_permissions=parent_permissions, child_permissions=child_permissions,
                state_keys=query.state_keys or None,
            )
            if self._workflow_ui_closing:
                return
            pending = result.pending_tool_call
            target.update(Text(
                f"Run: {result.run_id}\nStop: {result.stop_reason.value}\n"
                f"Checkpoint: {result.checkpoint_id or '-'}\nSteps: {result.steps}; tools: {result.tool_calls}\n"
                f"Pending call: {pending.id if pending else '-'}; tool: {pending.name if pending else '-'}\n"
                f"Tokens: input={result.usage.input_tokens}, output={result.usage.output_tokens}, "
                f"total={result.usage.total_tokens}, complete={result.usage_complete}\n"
                f"Cost: {_cost_text(result.cost, complete=result.cost_complete)}\n"
                "Model output, arguments, scope and event bodies are hidden.\n"
                "This result alone does not confirm the selected inner tool ran. Review again."
            ))
        except asyncio.CancelledError:
            if not self._workflow_ui_closing:
                target.update("Recovery interrupted; inspect retained checkpoints. No automatic replay.")
            raise
        except Exception as error:
            if not self._workflow_ui_closing:
                target.update(f"Chain recovery failed: {type(error).__name__}; review again.")
        finally:
            self._chain_busy = False
            if not self._workflow_ui_closing:
                for widget, disabled in states:
                    widget.disabled = disabled

    def _start_workflow_resume(self, *, approve: bool = False) -> None:
        if self._workflow_ui_closing or self._chain_busy:
            return
        if self._active_workflow is not None or (
            self._workflow_worker is not None and not self._workflow_worker.is_finished
        ):
            return
        self._workflow_worker = self.run_worker(
            self._resume_workflow(approve=approve),
            name="workflow-resume",
            group="workflow-resume",
            exclusive=False,
            exit_on_error=False,
        )

    def _request_workflow_pause(self) -> None:
        active = self._active_workflow
        if active is None or self._workflow_ui_closing:
            return
        pause_button = self.query_one("#workflow-checkpoint-pause", Button)
        if pause_button.disabled:
            return
        active.control.request_pause(active.run_id)
        pause_button.disabled = True
        self.query_one("#workflow-control-status", Static).update(
            Text(
                f"Pause requested for {active.run_id}\n"
                f"State root: {active.state_root}\n"
                "Waiting for the current node/batch to finish. "
                "This request has not yet been acknowledged as paused.\n"
                "Source: this UI only; no persistent SQLite request was changed."
            )
        )

    def _workflow_approval_request(self, run_id: str) -> _WorkflowApprovalRequest:
        def value(suffix: str) -> str:
            return self.query_one(f"#workflow-approval-{suffix}", Input).value.strip()

        root_value = self.query_one("#workflow-checkpoint-state-root", Input).value.strip()
        if not root_value or not value("factory"):
            raise ValueError("workflow state root and approval factory are required")
        root = self._workspace_path(root_value).resolve()
        agent_root = self._workspace_path(value("agent-root")).resolve() if value("agent-root") else root
        if not (root / "workflows").is_dir() or not (agent_root / "runs").is_dir():
            raise ValueError("select existing Workflow and Agent state roots")
        reference = AgentWorkflowApproval(
            run_id, value("node"), value("agent-run"), value("agent-name"), value("call"), value("tool"),
        )
        if value("confirm") != f"APPROVE {reference.call_id}":
            raise ValueError("type APPROVE followed by the exact pending Call ID")
        return _WorkflowApprovalRequest(
            root, agent_root, reference, value("factory"),
            _split_values(value("state-keys")), frozenset(_split_values(value("permissions"))),
        )

    async def _resume_workflow(self, *, approve: bool = False) -> None:
        if self._active_workflow is not None or self._workflow_ui_closing or self._chain_busy:
            return
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
        approval_request = None
        entries = ()
        try:
            if approve:
                approval_request = self._workflow_approval_request(run_id)
            else:
                entries = _split_values(
                    self.query_one("#workflow-checkpoint-entries", Input).value
                )
        except OSError as error:
            target.update(f"Workflow approval paths unavailable: {type(error).__name__}")
            return
        except ValueError as error:
            target.update(f"Rejected: {error}")
            return
        if not approve and not entries:
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
        self.query_one("#workflow-approval-confirm", Input).value = ""
        try:
            store = (
                JsonlWorkflowStore(approval_request.state_root)
                if approval_request is not None else self._workflow_store()
            )
        except (OSError, ValueError) as error:
            target.update(f"Workflow store unavailable: {type(error).__name__}")
            return

        threaded = self.query_one("#workflow-checkpoint-threaded", Checkbox).value
        active = _ActiveWorkflowResume(
            store.root,
            run_id,
            WorkflowPauseController(),
            self.query_one("#workflow-checkpoint-external-pause", Checkbox).value,
        )
        controls = [
            self.query_one(f"#workflow-checkpoint-{suffix}")
            for suffix in (
                "state-root", "run", "entries", "load-confirm", "resume-confirm",
                "resume", "threaded", "external-pause",
            )
        ]
        controls.extend(
            self.query_one(f"#workflow-approval-{suffix}")
            for suffix in (
                "agent-root", "state-keys", "review", "factory", "node", "agent-run",
                "agent-name", "call", "tool", "permissions", "confirm", "resume",
            )
        )
        original_disabled = [(widget, widget.disabled) for widget in controls]
        pause_button = self.query_one("#workflow-checkpoint-pause", Button)
        control_status = self.query_one("#workflow-control-status", Static)
        self._active_workflow = active
        for widget in controls:
            widget.disabled = True
        pause_button.disabled = False
        control_status.update(
            Text(
                f"Active recovery: {run_id}\nState root: {active.state_root}\n"
                "Cross-process SQLite pause observation: "
                f"{'enabled' if active.observe_external_pause else 'disabled'}\n"
                "Observation is checked at node/batch boundaries, not a live ACK."
                + (
                    f"\nApproval recovery: child={approval_request.reference.agent_run_id} "
                    f"call={approval_request.reference.call_id}\n"
                    "All three confirmations were consumed for this recovery only."
                    if approval_request is not None else ""
                )
            )
        )
        try:
            pause_source = (
                AnyWorkflowPauseSource(
                    active.control, SQLiteWorkflowPauseController(active.state_root)
                )
                if active.observe_external_pause else active.control
            )
            invoker = ThreadedWorkflowNodeInvoker() if threaded else None
            if approval_request is not None:
                result = await resume_workflow_approval(
                    store, JsonlRunStore(approval_request.agent_root), approval_request.reference,
                    lambda context: open_workflow_approval_entry(approval_request.factory, context),
                    permissions=approval_request.permissions,
                    state_keys=approval_request.state_keys or None,
                    node_invoker=invoker, pause_source=pause_source,
                )
            else:
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
                    raise WorkflowStoreError("loaded workflow kind differs from the checkpoint")
                async with open_local_workflow(
                    active.state_root, pause_source=pause_source, node_invoker=invoker,
                ) as host:
                    result = await host.invoke("resume", definition, run_id)
            pause_button.disabled = True
            if self._workflow_ui_closing:
                return
            event_target.update(
                Text(
                    "\n".join(_workflow_event_text(event) for event in result.events)
                    or "No workflow events."
                )
            )
            target.update(
                Text(
                    f"Run: {result.run_id}\n"
                    f"Stop: {result.stop_reason.value}\n"
                    f"Completed nodes: {','.join(result.completed_nodes) or '-'}\n"
                    f"Checkpoint retained: {result.checkpoint_id or '-'}\n"
                    f"Events: {len(result.events)}\n"
                    "Runtime input, state, output, and metadata are hidden."
                    + (
                        "\nA stopped or paused parent does not prove the selected tool ran. "
                        "Review linked approvals again before another grant."
                        if approval_request is not None else ""
                    )
                )
            )
            control_status.update(
                Text(
                    f"Recovery stopped: {run_id} | {result.stop_reason.value}\n"
                    "Resuming a retained checkpoint requires fresh confirmations."
                    + (
                        "\nPersistent SQLite requests were not cleared. Inspect with "
                        "workflow-pause-status and clear explicitly when appropriate."
                        if active.observe_external_pause else ""
                    )
                )
            )
            await self._refresh_workflow_checkpoints()
        except asyncio.CancelledError:
            if not self._workflow_ui_closing:
                target.update("Recovery interrupted; inspect the retained checkpoint.")
                control_status.update("Recovery interrupted; no automatic replay.")
            raise
        except (
            OSError,
            WorkflowEntryLoadError,
            WorkflowStoreError,
            WorkflowPauseControlError,
            ValueError,
        ) as error:
            if not self._workflow_ui_closing:
                target.update(f"Workflow resume rejected: {type(error).__name__}")
                control_status.update("Recovery stopped; inspect the checkpoint.")
        except Exception as error:
            if not self._workflow_ui_closing:
                target.update(f"Workflow resume failed: {type(error).__name__}")
                control_status.update("Recovery stopped; inspect the checkpoint.")
        finally:
            # Only this UI's request belongs to this recovery. Never clear
            # durable requests written by another process on exit or failure.
            active.control.clear(run_id)
            self._active_workflow = None
            if not self._workflow_ui_closing:
                pause_button.disabled = True
                for widget, disabled in original_disabled:
                    widget.disabled = disabled

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
        if getattr(self, "_evaluation_busy", False):
            return
        self._evaluation_busy = True
        try:
            await self._execute_evaluation()
        finally:
            self._evaluation_busy = False

    async def _execute_evaluation(self) -> None:
        target = self.query_one("#evaluation-result", Static)
        try:
            usage_options = self._capture_service_usage("evaluation")
        except ValueError as error:
            target.update(Text(f"Rejected: {error}"))
            return
        knowledge_entry = self.query_one("#evaluation-knowledge-entry", Input).value.strip() or None
        knowledge_code = self.query_one("#evaluation-knowledge-code", Input)
        knowledge_queries = self.query_one("#evaluation-knowledge-queries", Input)
        knowledge_code_authorized = knowledge_code.value.strip() == "LOAD KNOWLEDGE"
        knowledge_queries_authorized = knowledge_queries.value.strip() == "QUERY ALL CASES"
        knowledge_code.value = knowledge_queries.value = ""
        try:
            knowledge_options = KnowledgeEvaluationOptions(knowledge_entry, knowledge_code_authorized, knowledge_queries_authorized)
        except ValueError:
            target.update(Text("Rejected: knowledge evaluation requires LOAD KNOWLEDGE and QUERY ALL CASES."))
            return
        self.query_one("#evaluation-budget-result", Static).update(Text("Shared budget not read for this attempt."))
        budget_entry = self.query_one("#evaluation-budget-entry", Input).value.strip() or None
        budget_confirmation = self.query_one("#evaluation-budget-confirm", Input)
        budget_authorized = budget_confirmation.value.strip() == "LOAD BUDGET"
        budget_confirmation.value = ""
        if budget_entry is not None and not budget_authorized:
            target.update(Text("Rejected: type LOAD BUDGET to authorize unsandboxed budget host code"))
            return
        confirmation = self.query_one("#evaluation-confirm", Input)
        if confirmation.value.strip() != "EVALUATE":
            target.update("Rejected: type EVALUATE to authorize model calls")
            return
        confirmation.value = ""
        try:
            tool_entries = _split_values(
                self.query_one("#evaluation-tool-entries", Input).value
            )
            permissions = frozenset(
                _split_values(
                    self.query_one("#evaluation-permissions", Input).value
                )
            )
        except ValueError as error:
            target.update(f"Rejected: {error}")
            return
        tool_confirmation = self.query_one("#evaluation-tool-confirm", Input)
        if (
            tool_entries
            and tool_confirmation.value.strip() != "LOAD EVAL TOOLS"
        ):
            target.update(
                "Rejected: type LOAD EVAL TOOLS to authorize developer Python imports"
            )
            return
        tool_confirmation.value = ""
        dataset_value = self.query_one("#evaluation-dataset", Input).value.strip()
        dataset = (
            dataset_value
            if dataset_value.startswith("builtin:")
            else self._workspace_path(dataset_value)
        )
        config_path = self._workspace_path(
            self.query_one("#evaluation-config", Input).value
        )
        report_value = self.query_one("#evaluation-report", Input).value.strip()
        report_path = self._workspace_path(report_value) if report_value else None
        target.update("Running evaluation…")
        try:
            evaluation_dataset = load_evaluation_dataset(dataset)
            cases = evaluation_dataset.cases
            knowledge_options.validate_queries(tuple(case.prompt for case in cases))
            scorers = _tui_evaluation_scorers(evaluation_dataset.scorers)
            catalog = load_tool_entries(tool_entries) if tool_entries else {}
            config = load_local_runtime_config(config_path)
            selection = getattr(config, "shared_budget", None)
            usage_selection = getattr(config, "service_usage", None)
            knowledge_selection = getattr(config, "knowledge", None)
            with TemporaryDirectory(prefix="wagent-tui-eval-") as state_root:
                async with (
                    budget_binding_scope(budget_entry, selected=selection.binding if selection else None,
                                         confirmed=budget_authorized) as bindings,
                    knowledge_binding_scope(knowledge_options, selected=knowledge_selection.binding if knowledge_selection else None) as knowledge_bindings,
                    service_usage_binding_scope(usage_options.entry, selected=usage_selection.binding if usage_selection else None,
                                                confirmed=usage_options.confirm_code, confirm_record=usage_options.confirm_record) as usage_bindings,
                ):
                    runtime = open_local_runtime(
                        config, state_root, tool_bindings=catalog,
                        **({"shared_budget_bindings": bindings} if budget_entry is not None else {}),
                        **({"service_usage_bindings": usage_bindings} if usage_options.entry is not None else {}),
                        **({"knowledge_bindings": knowledge_bindings} if knowledge_entry is not None else {}),
                    )

                    async def run_case(case: EvaluationCase):
                        run = await runtime.run(
                            case.prompt, session_title=f"Evaluation: {case.name}", permissions=permissions,
                            **knowledge_options.runtime_options(case.prompt),
                        )
                        return run.result

                    async with runtime:
                        report = await LocalEvaluationRunner().run(cases, run_case, scorers=scorers)
                    budget = await shared_budget_summary(getattr(runtime, "shared_budget", None))
                    service_summary = await service_usage_summary(getattr(runtime, "service_usage", None))
            if report_path is not None:
                await JsonEvaluationReporter(
                    **({"accounting_scope": "model-runs-only; retrieval-not-included"} if knowledge_entry is not None else {}),
                ).write(report, report_path)
        except (
            EvaluationDatasetError,
            LocalRuntimeConfigError,
            OSError,
            ToolEntryLoadError,
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
        if knowledge_entry is not None:
            lines.append("Knowledge: per-case retrieval; retrieval usage/cost not included in model totals.")
        target.update("\n".join(lines))
        self._show_shared_budget("evaluation", budget)
        self._show_service_usage("evaluation", service_summary)

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


def _tui_evaluation_scorers(
    names: tuple[str, ...],
) -> tuple[EvaluationScorer, ...]:
    if names == ("none",):
        return ()
    available: dict[str, EvaluationScorer] = {
        "exact-text": ExactTextScorer(),
        "contains-text": ContainsTextScorer(),
        "case-contract": CaseContractScorer(),
    }
    try:
        return tuple(available[name] for name in names)
    except KeyError as error:
        raise ValueError(f"unsupported evaluation scorer: {error.args[0]}") from error


def _event_text(event: RunEvent) -> str:
    """Render a prompt/argument/output-free event projection for the TUI."""

    projected = safe_run_event_to_dict(event)["data"]
    details: list[str] = []
    for name, value in projected.items():
        if isinstance(value, dict):
            details.append(f"{name}={value['total']} {value['currency']}")
        else:
            details.append(f"{name}={value}")
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
    if (
        event.type.value == "workflow-paused"
        and event.data.get("source") == "external-request"
    ):
        details.append("source=external-request")
    prefix = f"{event.sequence:03d} {event.type.value}"
    return prefix if not details else f"{prefix} | {' | '.join(details)}"


def _cost_text(cost: ModelCost | None, *, complete: bool) -> str:
    if cost is None:
        return "unavailable"
    suffix = "" if complete else " (incomplete)"
    return f"{cost.total} {cost.currency}@{cost.price_table_version}{suffix}"


def _service_usage_widgets(prefix: str):
    yield Input(placeholder="Usage host / 用量宿主 module:factory (optional)", id=f"{prefix}-usage-entry")
    yield Input(placeholder="LOAD USAGE — authorize unsandboxed host code", id=f"{prefix}-usage-code")
    yield Input(placeholder="RECORD USAGE — authorize ledger observations", id=f"{prefix}-usage-record")
    yield Static("Service usage not read.", id=f"{prefix}-usage-result", classes="panel")


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
