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
from w_agent.sandbox import DockerSandboxProvider


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
    #composition-result, #probe-result { min-height: 8; }
    """

    def __init__(self, workspace: str | Path = ".") -> None:
        super().__init__()
        self.workspace = Path(workspace).resolve()

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
            with TabPane("Run", id="run"):
                yield Static(
                    "Assemble a ModelExecutor, ToolRegistry, and AgentLoop through "
                    "the public Python API. Interactive configured runs are the "
                    "next TUI increment.",
                    classes="panel",
                )
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
        summary = (
            f"Workspace: {self.workspace}\n"
            f"Python framework version: {__version__}\n"
            f"Stored compositions: {len(entries)}\n"
            "No hosted service or background daemon is required."
        )
        self.query_one("#home-summary", Static).update(summary)
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
