import pytest
from types import SimpleNamespace

pytest.importorskip("textual")

import w_agent.tui as tui_module
from w_agent import (
    CompositionManifest,
    LocalProviderAssembly,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelCost,
    RunEvent,
    RunEventType,
    RunResult,
    StopReason,
    TokenUsage,
    PythonWorkflowDefinition,
    WorkflowContext,
    WorkflowNodeResult,
    WorkflowStopReason,
    encode_composition,
)
from w_agent.tui import WAgentTui
from textual.widgets import TabbedContent


@pytest.mark.asyncio
async def test_tui_mounts_all_first_release_sections_and_inspects_code(tmp_path):
    app = WAgentTui(tmp_path)
    code = encode_composition(CompositionManifest("demo", "1.0.0"))

    async with app.run_test(size=(140, 50)) as pilot:
        assert "Workspace:" in str(app.query_one("#home-summary").content)
        assert len(app.query("TabPane")) == 10
        assert "No agent checkpoints" in str(
            app.query_one("#checkpoint-result").content
        )
        assert "No workflow checkpoints" in str(
            app.query_one("#workflow-checkpoint-result").content
        )

        app.query_one(TabbedContent).active = "composition"
        await pilot.pause()
        app.query_one("#composition-code").value = code
        await pilot.click("#composition-button")
        await pilot.pause()

        rendered = str(app.query_one("#composition-result").content)
        assert '"name": "demo"' in rendered


@pytest.mark.asyncio
async def test_tui_creates_archives_and_unarchives_local_session(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 55)) as pilot:
        app.query_one(TabbedContent).active = "sessions"
        await pilot.pause()
        app.query_one("#session-title").value = "Coding task"
        await pilot.click("#session-create")
        await pilot.pause()

        created = str(app.query_one("#session-result").content)
        session_id = app.query_one("#session-id").value
        assert "Coding task" in created
        assert session_id.startswith("session-")

        await pilot.click("#session-archive")
        await pilot.pause()
        assert "| archived | Coding task" in str(
            app.query_one("#session-result").content
        )

        await pilot.click("#session-unarchive")
        await pilot.pause()
        assert "| active | Coding task" in str(app.query_one("#session-result").content)


@pytest.mark.asyncio
async def test_tui_rejects_invalid_composition_without_loading(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(120, 40)) as pilot:
        app.query_one(TabbedContent).active = "composition"
        await pilot.pause()
        app.query_one("#composition-code").value = "invalid"
        await pilot.click("#composition-button")
        await pilot.pause()

        rendered = str(app.query_one("#composition-result").content)
        assert "Rejected: unsupported composition-code prefix" in rendered


@pytest.mark.asyncio
async def test_tui_run_requires_explicit_confirmation_before_config_or_network(
    tmp_path,
):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 55)) as pilot:
        app.query_one(TabbedContent).active = "run"
        await pilot.pause()
        app.query_one("#run-prompt").value = "hello"
        await pilot.click("#run-button")
        await pilot.pause()

        rendered = str(app.query_one("#run-result").content)
        assert "type RUN to authorize" in rendered

        app.query_one("#run-confirm").value = "RUN"
        await pilot.pause()
        await app._run_configured_agent()
        await pilot.pause()
        assert app.query_one("#run-confirm").value == ""
        assert "config" in str(app.query_one("#run-result").content).lower()


@pytest.mark.asyncio
async def test_tui_tool_code_requires_separate_import_confirmation(
    tmp_path,
    monkeypatch,
):
    loaded = []
    monkeypatch.setattr(
        tui_module,
        "load_tool_entries",
        lambda entries: loaded.append(entries) or {},
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 65)) as pilot:
        app.query_one(TabbedContent).active = "run"
        await pilot.pause()
        app.query_one("#run-prompt").value = "hello"
        app.query_one("#run-tool-entries").value = "my_tools:bindings"
        app.query_one("#run-confirm").value = "RUN"
        await pilot.click("#run-button")
        await pilot.pause()

        assert loaded == []
        assert "type LOAD TOOLS" in str(app.query_one("#run-result").content)


@pytest.mark.asyncio
async def test_tui_projects_live_events_without_prompt_or_arguments(
    tmp_path,
    monkeypatch,
):
    class Runtime:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            self.closed = True

        async def run(self, prompt, **kwargs):
            assert prompt == "SECRET_PROMPT"
            assert kwargs["permissions"] == frozenset({"notes.write"})
            await kwargs["event_callback"](
                RunEvent(
                    1,
                    RunEventType.TOOL_REQUESTED,
                    "run-live",
                    {
                        "step": 1,
                        "call_id": "call-1",
                        "name": "save_note",
                        "arguments": {"text": "SECRET_ARGUMENT"},
                        "text": "SECRET_OUTPUT",
                    },
                    session_id="session-live",
                )
            )
            return SimpleNamespace(
                session=SimpleNamespace(session_id="session-live"),
                result=RunResult(
                    "run-live",
                    StopReason.COMPLETED,
                    "done",
                    (ModelMessage.text(MessageRole.ASSISTANT, "done"),),
                    (),
                    steps=1,
                    tool_calls=1,
                ),
            )

    runtime = Runtime()
    loaded = []
    monkeypatch.setattr(tui_module, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(
        tui_module,
        "load_tool_entries",
        lambda entries: loaded.append(entries) or {"save_note": object()},
    )
    monkeypatch.setattr(
        tui_module,
        "assemble_local_runtime",
        lambda config, state_root, *, tool_bindings: runtime,
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(150, 70)) as pilot:
        app.query_one(TabbedContent).active = "run"
        await pilot.pause()
        app.query_one("#run-prompt").value = "SECRET_PROMPT"
        app.query_one("#run-tool-entries").value = "my_tools:bindings"
        app.query_one("#run-permissions").value = "notes.write"
        app.query_one("#run-tool-confirm").value = "LOAD TOOLS"
        app.query_one("#run-confirm").value = "RUN"
        await pilot.click("#run-button")
        await pilot.pause()

        rendered = str(app.query_one("#run-events").content)
        assert "tool-requested" in rendered
        assert "call_id=call-1" in rendered
        assert "SECRET_PROMPT" not in rendered
        assert "SECRET_ARGUMENT" not in rendered
        assert "SECRET_OUTPUT" not in rendered
        assert loaded == [("my_tools:bindings",)]
        assert runtime.closed is True


@pytest.mark.asyncio
async def test_tui_resumes_exact_approved_call_with_live_events(
    tmp_path,
    monkeypatch,
):
    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            pass

        async def resume(self, session_id, run_id, **kwargs):
            assert session_id == "session-1"
            assert run_id == "run-1"
            assert kwargs["approved_call_ids"] == frozenset({"call-1"})
            assert kwargs["permissions"] == frozenset({"notes.write"})
            await kwargs["event_callback"](
                RunEvent(
                    2,
                    RunEventType.RUN_RESUMED,
                    "run-1",
                    {"checkpoint_status": "resuming", "pending_call_id": "call-1"},
                    session_id="session-1",
                )
            )
            return SimpleNamespace(
                session=SimpleNamespace(session_id="session-1"),
                result=RunResult(
                    "run-1",
                    StopReason.COMPLETED,
                    "approved",
                    (ModelMessage.text(MessageRole.ASSISTANT, "approved"),),
                    (),
                    steps=2,
                    tool_calls=1,
                ),
            )

    runtime = Runtime()
    monkeypatch.setattr(tui_module, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(tui_module, "load_tool_entries", lambda entries: {})
    monkeypatch.setattr(
        tui_module,
        "assemble_local_runtime",
        lambda config, state_root, *, tool_bindings: runtime,
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(150, 75)) as pilot:
        app.query_one(TabbedContent).active = "checkpoints"
        await pilot.pause()
        app.query_one("#checkpoint-session").value = "session-1"
        app.query_one("#checkpoint-run").value = "run-1"
        app.query_one("#checkpoint-call").value = "call-1"
        app.query_one("#checkpoint-tool-entries").value = "my_tools:bindings"
        app.query_one("#checkpoint-permissions").value = "notes.write"
        app.query_one("#checkpoint-tool-confirm").value = "LOAD TOOLS"
        app.query_one("#checkpoint-confirm").value = "RESUME"
        await pilot.click("#checkpoint-resume")
        await pilot.pause()

        assert "Stop: completed" in str(
            app.query_one("#checkpoint-resume-result").content
        )
        events = str(app.query_one("#checkpoint-events").content)
        assert "run-resumed" in events
        assert "pending_call_id=call-1" in events
        assert app.query_one("#checkpoint-confirm").value == ""
        assert app.query_one("#checkpoint-tool-confirm").value == ""


@pytest.mark.asyncio
async def test_tui_workflow_code_requires_separate_import_confirmation(
    tmp_path,
    monkeypatch,
):
    loaded = []
    monkeypatch.setattr(
        tui_module,
        "load_workflow_entries",
        lambda entries: loaded.append(entries) or {},
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(150, 80)) as pilot:
        app.query_one(TabbedContent).active = "checkpoints"
        await pilot.pause()
        app.query_one("#workflow-checkpoint-run").value = "workflow-1"
        app.query_one("#workflow-checkpoint-entries").value = "my_workflows:review"
        app.query_one("#workflow-checkpoint-resume-confirm").value = (
            "RESUME WORKFLOW"
        )
        await app._resume_workflow()

        assert loaded == []
        assert "type LOAD WORKFLOW" in str(
            app.query_one("#workflow-checkpoint-resume-result").content
        )


@pytest.mark.asyncio
async def test_tui_lists_and_resumes_exact_workflow_without_runtime_values(
    tmp_path,
    monkeypatch,
):
    calls = []

    def handler(context):
        calls.append(context.resume_count)
        if context.resume_count == 0:
            return WorkflowNodeResult(
                output="SECRET_WAITING_OUTPUT",
                state_updates={"draft": "SECRET_STATE"},
                pause=True,
            )
        return WorkflowNodeResult(output="SECRET_FINAL_OUTPUT")

    definition = PythonWorkflowDefinition("review", handler, version="3")
    store = JsonlWorkflowStore(tmp_path / ".wagent")
    first = await LocalWorkflowEngine(store).start(
        definition,
        WorkflowContext(
            "workflow-1",
            input="SECRET_INPUT",
            metadata={"credential": "SECRET_METADATA"},
        ),
    )
    assert first.stop_reason == WorkflowStopReason.PAUSED
    monkeypatch.setattr(
        tui_module,
        "load_workflow_entries",
        lambda entries: {("review", "3"): definition},
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(160, 90)) as pilot:
        app.query_one(TabbedContent).active = "checkpoints"
        await pilot.pause()
        listed = str(app.query_one("#workflow-checkpoint-result").content)
        assert "workflow-1" in listed
        assert "review@3" in listed
        assert "status=paused" in listed
        assert "SECRET_INPUT" not in listed
        assert "SECRET_STATE" not in listed
        assert "SECRET_WAITING_OUTPUT" not in listed
        assert "SECRET_METADATA" not in listed

        app.query_one("#workflow-checkpoint-run").value = "workflow-1"
        app.query_one("#workflow-checkpoint-entries").value = "my_workflows:review"
        app.query_one("#workflow-checkpoint-load-confirm").value = "LOAD WORKFLOW"
        app.query_one("#workflow-checkpoint-resume-confirm").value = (
            "RESUME WORKFLOW"
        )
        await app._resume_workflow()
        await pilot.pause()

        result = str(app.query_one("#workflow-checkpoint-resume-result").content)
        events = str(app.query_one("#workflow-checkpoint-events").content)
        assert "Stop: completed" in result
        assert "Runtime input, state, output, and metadata are hidden" in result
        assert "workflow-resumed" in events
        assert "SECRET_FINAL_OUTPUT" not in result
        assert "SECRET_FINAL_OUTPUT" not in events
        assert "No workflow checkpoints" in str(
            app.query_one("#workflow-checkpoint-result").content
        )
        assert app.query_one("#workflow-checkpoint-load-confirm").value == ""
        assert app.query_one("#workflow-checkpoint-resume-confirm").value == ""
        assert calls == [0, 1]


@pytest.mark.asyncio
async def test_tui_active_provider_probe_requires_explicit_confirmation(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 60)) as pilot:
        app.query_one(TabbedContent).active = "models"
        await pilot.pause()
        await pilot.click("#provider-probe-active")
        await pilot.pause()

        rendered = str(app.query_one("#provider-probe-result").content)
        assert "type ACTIVE to authorize" in rendered


@pytest.mark.asyncio
async def test_tui_safe_configured_provider_probe_never_generates(
    tmp_path,
    monkeypatch,
):
    class Provider:
        def __init__(self):
            self.stream_calls = 0
            self.closed = False

        async def list_models(self):
            return (
                ModelDescriptor(
                    "configured",
                    "chat",
                    frozenset(
                        {
                            ModelCapability.TEXT_INPUT,
                            ModelCapability.TEXT_OUTPUT,
                        }
                    ),
                ),
            )

        async def resolve(self, model):
            return (await self.list_models())[0]

        async def stream(self, request, *, cancellation=None):
            self.stream_calls += 1
            if False:
                yield request

        async def aclose(self):
            self.closed = True

    provider = Provider()
    config = SimpleNamespace(provider=SimpleNamespace(model="chat"))
    monkeypatch.setattr(tui_module, "load_local_runtime_config", lambda path: config)
    monkeypatch.setattr(
        tui_module,
        "assemble_local_provider",
        lambda value: LocalProviderAssembly("configured", provider),
    )
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 60)) as pilot:
        app.query_one(TabbedContent).active = "models"
        await pilot.pause()
        await pilot.click("#provider-probe-safe")
        await pilot.pause()

        rendered = str(app.query_one("#provider-probe-result").content)
        assert "Mode: safe" in rendered
        assert "Successful: True" in rendered
        assert provider.stream_calls == 0
        assert provider.closed is True


@pytest.mark.asyncio
async def test_tui_evaluation_requires_explicit_confirmation(tmp_path):
    app = WAgentTui(tmp_path)

    async with app.run_test(size=(140, 60)) as pilot:
        app.query_one(TabbedContent).active = "evaluation"
        await pilot.pause()
        await pilot.click("#evaluation-button")
        await pilot.pause()

        rendered = str(app.query_one("#evaluation-result").content)
        assert "type EVALUATE to authorize" in rendered


@pytest.mark.asyncio
async def test_tui_runs_private_evaluation_and_closes_runtime(tmp_path, monkeypatch):
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        '{"cases":[{"name":"one","prompt":"SECRET_PROMPT",'
        '"expected_output":"VISIBLE_OUTPUT"}]}',
        encoding="utf-8",
    )

    class Runtime:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            self.closed = True

        async def run(self, prompt, **kwargs):
            assert prompt == "SECRET_PROMPT"
            return SimpleNamespace(
                result=RunResult(
                    "tui-eval",
                    StopReason.COMPLETED,
                    "VISIBLE_OUTPUT",
                    (ModelMessage.text(MessageRole.ASSISTANT, "VISIBLE_OUTPUT"),),
                    (),
                    steps=1,
                    tool_calls=0,
                    usage=TokenUsage(4, 2),
                    model_calls=1,
                    reported_usage_calls=1,
                    cost=ModelCost("USD", "prices-v1", "0.01", "0.02"),
                    priced_usage_calls=1,
                )
            )

    runtime = Runtime()
    monkeypatch.setattr(tui_module, "load_local_runtime_config", lambda path: object())
    monkeypatch.setattr(
        tui_module,
        "assemble_local_runtime",
        lambda config, state_root: runtime,
    )
    app = WAgentTui(tmp_path)
    report = tmp_path / "report.json"

    async with app.run_test(size=(140, 65)) as pilot:
        app.query_one(TabbedContent).active = "evaluation"
        await pilot.pause()
        app.query_one("#evaluation-dataset").value = "cases.json"
        app.query_one("#evaluation-report").value = "report.json"
        app.query_one("#evaluation-confirm").value = "EVALUATE"
        await pilot.click("#evaluation-button")
        await pilot.pause()

        rendered = str(app.query_one("#evaluation-result").content)
        assert "Passed: 1/1" in rendered
        assert "in=4, out=2" in rendered
        assert "Cost: 0.03 USD" in rendered
        assert "SECRET_PROMPT" not in rendered
        assert "VISIBLE_OUTPUT" not in rendered
        assert app.query_one("#evaluation-confirm").value == ""
        assert runtime.closed is True
        persisted = report.read_text(encoding="utf-8")
        assert "SECRET_PROMPT" not in persisted
        assert "VISIBLE_OUTPUT" not in persisted
