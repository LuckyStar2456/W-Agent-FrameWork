"""Optional in-process Textual UI over public W-Agent APIs."""

from __future__ import annotations

import json
from pathlib import Path

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
from w_agent.agents import CODING_AGENT_TEMPLATE, CUSTOMER_SUPPORT_AGENT_TEMPLATE
from w_agent.compositions import (
    CompositionError,
    CompositionStore,
    inspect_composition,
    manifest_to_dict,
)
from w_agent.models import EndpointProbe
from w_agent.local_runtime import (
    LocalRuntimeConfigError,
    assemble_local_runtime,
    load_local_runtime_config,
)
from w_agent.sandbox import DockerSandboxProvider
from w_agent.sessions import JsonSessionStore, SessionError, SessionManager


class WAgentTui(App[None]):
    """Local UI shell; it owns no capability unavailable through public APIs."""

    TITLE = "W-Agent"
    SUB_TITLE = "local agent development"
    BINDINGS = [("q", "quit", "Quit")]
    CSS = """
    Screen { background: $surface; }
    TabPane { padding: 1 2; }
    .panel { border: round $primary; padding: 1 2; margin-bottom: 1; }
    Input { margin-bottom: 1; }
    Button { margin-bottom: 1; }
    #composition-result, #probe-result, #session-result, #run-result { min-height: 8; }
    """

    def __init__(self, workspace: str | Path = ".") -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()
        self.sessions = SessionManager(
            JsonSessionStore(self.workspace / ".wagent" / "sessions")
        )

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
            with TabPane("Profiles", id="profiles"):
                yield Static(self._profile_text(), classes="panel")
            with TabPane("Plugins", id="plugins"):
                yield Static(
                    "Plugin installation and loading require explicit application "
                    "confirmation. This UI never auto-installs or auto-updates.",
                    classes="panel",
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
                    placeholder="Type RUN to authorize the model call",
                    id="run-confirm",
                )
                yield Button("Start configured run", id="run-button", variant="primary")
                yield Static("No configured run started.", id="run-result", classes="panel")
            with TabPane("Checkpoints", id="checkpoints"):
                yield Static(
                    "Agent and workflow checkpoint stores are local and fail closed. "
                    "Cross-store listing and guided resume remain planned.",
                    classes="panel",
                )
            with TabPane("Sandbox", id="sandbox"):
                yield Static("Checking Docker/OCI…", id="sandbox-summary", classes="panel")
            with TabPane("Evaluation", id="evaluation"):
                yield Static(
                    "Local benchmark suites and record/replay remain planned.",
                    classes="panel",
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
        available = await DockerSandboxProvider().available()
        self.query_one("#sandbox-summary", Static).update(
            f"Docker/OCI available: {available}\n"
            "Unsafe local execution is never enabled by this UI. It requires an "
            "explicit runtime authorization object from the host application."
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composition-button":
            self._inspect_composition()
        elif event.button.id == "probe-button":
            await self._probe_endpoint()
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
                f"tokens={sum(run.usage.total_tokens for run in item.runs)}"
            )
            for item in sessions
        ]
        body = "\n".join(lines) if lines else "No local sessions."
        self.query_one("#session-result", Static).update(prefix + body)

    async def _run_configured_agent(self) -> None:
        target = self.query_one("#run-result", Static)
        confirmation = self.query_one("#run-confirm", Input)
        if confirmation.value.strip() != "RUN":
            target.update("Rejected: type RUN to authorize the model call")
            return
        confirmation.value = ""
        prompt = self.query_one("#run-prompt", Input).value
        if not prompt:
            target.update("Rejected: prompt is required")
            return
        source = Path(self.query_one("#run-config", Input).value)
        if not source.is_absolute():
            source = self.workspace / source
        session_id = self.query_one("#run-session", Input).value.strip() or None
        target.update("Running configured agent…")
        try:
            runtime = assemble_local_runtime(
                load_local_runtime_config(source),
                self.workspace / ".wagent",
            )
            run = await runtime.run(prompt, session_id=session_id)
        except (LocalRuntimeConfigError, SessionError, ValueError) as error:
            target.update(f"Rejected: {error}")
            return
        except Exception as error:
            target.update(f"Run failed: {type(error).__name__}")
            return
        result = run.result
        target.update(
            f"Session: {run.session.session_id}\n"
            f"Run: {result.run_id}\n"
            f"Stop: {result.stop_reason.value}\n"
            f"Attempts: {len(result.attempts)}\n"
            f"Tokens: in={result.usage.input_tokens}, "
            f"out={result.usage.output_tokens}, "
            f"total={result.usage.total_tokens}, "
            f"complete={result.usage_complete}\n\n"
            f"{result.output}"
        )
        self.query_one("#run-session", Input).value = run.session.session_id
        await self._refresh_sessions()

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
