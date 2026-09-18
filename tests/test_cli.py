import asyncio
import json
from types import SimpleNamespace

from typer.testing import CliRunner

import w_agent.cli as cli_module
from w_agent import (
    LocalProviderAssembly,
    JsonlWorkflowStore,
    LocalWorkflowEngine,
    MessageRole,
    ModelCapability,
    ModelDescriptor,
    ModelMessage,
    ModelCost,
    RunResult,
    StopReason,
    TokenUsage,
    PythonWorkflowDefinition,
    WorkflowContext,
    WorkflowNodeResult,
)
from w_agent.cli import app

runner = CliRunner()


def test_cli_version_and_profile_json_are_machine_readable():
    version = runner.invoke(app, ["--version"])
    profiles = runner.invoke(app, ["profile", "list", "--json"])

    assert version.exit_code == 0
    assert "2.0.0a3" in version.stdout
    assert profiles.exit_code == 0
    assert [item["key"] for item in json.loads(profiles.stdout)] == [
        "customer-support",
        "coding",
    ]


def test_cli_init_is_idempotent_and_never_overwrites_config(tmp_path):
    first = runner.invoke(app, ["init", str(tmp_path), "--json"])
    config = tmp_path / ".wagent" / "config.json"
    config.write_text('{"keep":true}\n', encoding="utf-8")
    second = runner.invoke(app, ["init", str(tmp_path), "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert json.loads(second.stdout)["created"] == []
    assert config.read_text(encoding="utf-8") == '{"keep":true}\n'
    assert (tmp_path / ".wagent" / "sessions").is_dir()


def test_cli_composition_export_inspect_save_and_list(tmp_path):
    source = tmp_path / "manifest.json"
    source.write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "profiles": {"default": "coding"},
            }
        ),
        encoding="utf-8",
    )
    exported = runner.invoke(app, ["composition", "export", str(source)])
    assert exported.exit_code == 0
    code = exported.stdout.strip()

    inspected = runner.invoke(
        app,
        ["composition", "inspect", code, "--json"],
    )
    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["manifest"]["name"] == "demo"

    root = tmp_path / "store"
    saved = runner.invoke(
        app,
        ["composition", "save", code, "--root", str(root), "--alias", "dev"],
    )
    listed = runner.invoke(
        app,
        ["composition", "list", "--root", str(root), "--json"],
    )
    assert saved.exit_code == 0
    assert json.loads(listed.stdout) == [{"name": "demo", "version": "1.0.0"}]


def test_cli_composition_inspect_has_stable_failure_exit():
    result = runner.invoke(app, ["composition", "inspect", "not-a-code"])

    assert result.exit_code == 2
    assert "unsupported composition-code prefix" in result.stderr


def test_cli_keeps_basic_legacy_command_names():
    config = runner.invoke(app, ["config", "list", "--json"])
    beans = runner.invoke(app, ["bean", "list"])

    assert config.exit_code == 0
    assert json.loads(config.stdout) == {}
    assert beans.exit_code == 0


def test_cli_session_lifecycle_and_machine_readable_usage(tmp_path):
    root = tmp_path / "sessions"
    created = runner.invoke(
        app,
        [
            "session",
            "create",
            "Support case",
            "--id",
            "case-1",
            "--root",
            str(root),
            "--json",
        ],
    )
    listed = runner.invoke(
        app,
        ["session", "list", "--root", str(root), "--json"],
    )
    shown = runner.invoke(
        app,
        ["session", "show", "case-1", "--root", str(root), "--json"],
    )
    archived = runner.invoke(
        app,
        ["session", "archive", "case-1", "--root", str(root), "--json"],
    )
    hidden = runner.invoke(
        app,
        ["session", "list", "--root", str(root), "--json"],
    )
    restored = runner.invoke(
        app,
        ["session", "unarchive", "case-1", "--root", str(root), "--json"],
    )

    assert created.exit_code == listed.exit_code == shown.exit_code == 0
    assert archived.exit_code == hidden.exit_code == restored.exit_code == 0
    assert json.loads(created.stdout)["session_id"] == "case-1"
    assert json.loads(listed.stdout)[0]["total_tokens"] == 0
    assert json.loads(shown.stdout)["runs"] == []
    assert json.loads(archived.stdout)["status"] == "archived"
    assert json.loads(hidden.stdout) == []
    assert json.loads(restored.stdout)["status"] == "active"


def test_cli_session_missing_id_has_stable_failure(tmp_path):
    result = runner.invoke(
        app,
        ["session", "show", "missing", "--root", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "session does not exist" in result.stderr


def test_cli_run_requires_explicit_model_call_authorization():
    result = runner.invoke(app, ["run", "hello"])

    assert result.exit_code == 2
    assert "--confirm-model-call" in result.stderr


def test_cli_run_reports_invalid_config_without_model_call(tmp_path):
    source = tmp_path / "config.json"
    source.write_text("{}\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "hello",
            "--config",
            str(source),
            "--state-root",
            str(tmp_path / "state"),
            "--confirm-model-call",
        ],
    )

    assert result.exit_code == 2
    assert "provider must be an object" in result.stderr


def test_cli_active_provider_probe_requires_separate_authorization():
    result = runner.invoke(app, ["provider-probe", "--mode", "active"])

    assert result.exit_code == 2
    assert "--confirm-active-probe" in result.stderr


def test_cli_safe_provider_probe_uses_configured_provider_without_generation(
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
    monkeypatch.setattr(cli_module, "load_local_runtime_config", lambda path: config)
    monkeypatch.setattr(
        cli_module,
        "assemble_local_provider",
        lambda value: LocalProviderAssembly("configured", provider),
    )

    result = runner.invoke(app, ["provider-probe", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "safe"
    assert payload["successful"] is True
    assert payload["routes"] == [{"model": "chat", "provider": "configured"}]
    assert provider.stream_calls == 0
    assert provider.closed is True


def test_cli_run_requires_separate_authority_for_python_tool_entries():
    result = runner.invoke(
        app,
        [
            "run",
            "hello",
            "--confirm-model-call",
            "--tool-entry",
            "example:tools",
        ],
    )

    assert result.exit_code == 2
    assert "--confirm-tool-code" in result.stderr


def test_cli_run_resume_requires_model_and_exact_tool_call_authority():
    missing_model = runner.invoke(app, ["run-resume", "session-1", "run-1"])
    missing_call = runner.invoke(
        app,
        [
            "run-resume",
            "session-1",
            "run-1",
            "--confirm-model-call",
        ],
    )

    assert missing_model.exit_code == 2
    assert "--confirm-model-call" in missing_model.stderr
    assert missing_call.exit_code == 2
    assert "--approve-tool-call" in missing_call.stderr


def test_cli_checkpoint_list_is_machine_readable_and_prompt_free(tmp_path):
    result = runner.invoke(
        app,
        ["checkpoint", "list", "--state-root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_cli_workflow_checkpoint_list_is_machine_readable_and_value_free(tmp_path):
    definition = PythonWorkflowDefinition(
        "private-review",
        lambda context: WorkflowNodeResult(
            output="SECRET_OUTPUT",
            state_updates={"draft": "SECRET_STATE"},
            pause=True,
        ),
        version="4",
    )
    asyncio.run(
        LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).start(
            definition,
            WorkflowContext("workflow-1", input="SECRET_INPUT"),
        )
    )

    result = runner.invoke(
        app,
        ["checkpoint", "workflow-list", "--state-root", str(tmp_path), "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload[0]["run_id"] == "workflow-1"
    assert payload[0]["workflow_name"] == "private-review"
    assert payload[0]["workflow_version"] == "4"
    assert payload[0]["status"] == "paused"
    assert "SECRET_INPUT" not in result.stdout
    assert "SECRET_STATE" not in result.stdout
    assert "SECRET_OUTPUT" not in result.stdout


def test_cli_workflow_resume_requires_code_and_execution_authority():
    missing_resume = runner.invoke(
        app,
        [
            "checkpoint",
            "workflow-resume",
            "workflow-1",
            "--workflow-entry",
            "example:workflow",
        ],
    )
    missing_code = runner.invoke(
        app,
        [
            "checkpoint",
            "workflow-resume",
            "workflow-1",
            "--workflow-entry",
            "example:workflow",
            "--confirm-resume",
        ],
    )

    assert missing_resume.exit_code == 2
    assert "--confirm-resume" in missing_resume.stderr
    assert missing_code.exit_code == 2
    assert "--confirm-workflow-code" in missing_code.stderr


def test_cli_resumes_exact_workflow_and_hides_runtime_values(tmp_path, monkeypatch):
    def handler(context):
        if context.resume_count == 0:
            return WorkflowNodeResult(
                output="SECRET_WAITING_OUTPUT",
                state_updates={"draft": "SECRET_STATE"},
                pause=True,
            )
        return WorkflowNodeResult(output="SECRET_FINAL_OUTPUT")

    definition = PythonWorkflowDefinition("review", handler, version="5")
    asyncio.run(
        LocalWorkflowEngine(JsonlWorkflowStore(tmp_path)).start(
            definition,
            WorkflowContext("workflow-2", input="SECRET_INPUT"),
        )
    )
    monkeypatch.setattr(
        cli_module,
        "load_workflow_entries",
        lambda entries: {("review", "5"): definition},
    )

    result = runner.invoke(
        app,
        [
            "checkpoint",
            "workflow-resume",
            "workflow-2",
            "--workflow-entry",
            "example:workflow",
            "--state-root",
            str(tmp_path),
            "--confirm-workflow-code",
            "--confirm-resume",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["stop_reason"] == "completed"
    assert payload["checkpoint_id"] is None
    assert "SECRET_INPUT" not in result.stdout
    assert "SECRET_STATE" not in result.stdout
    assert "SECRET_WAITING_OUTPUT" not in result.stdout
    assert "SECRET_FINAL_OUTPUT" not in result.stdout


def test_cli_evaluate_requires_explicit_model_call_authorization(tmp_path):
    result = runner.invoke(app, ["evaluate", str(tmp_path / "cases.json")])

    assert result.exit_code == 2
    assert "--confirm-model-call" in result.stderr


def test_cli_evaluate_runs_dataset_and_writes_private_report(tmp_path, monkeypatch):
    dataset = tmp_path / "cases.json"
    dataset.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "case-one",
                        "prompt": "secret prompt",
                        "expected_output": "VISIBLE_OUTPUT",
                    }
                ]
            }
        ),
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
            assert prompt == "secret prompt"
            result = RunResult(
                "eval-run",
                StopReason.COMPLETED,
                "VISIBLE_OUTPUT",
                (ModelMessage.text(MessageRole.ASSISTANT, "VISIBLE_OUTPUT"),),
                (),
                steps=1,
                tool_calls=0,
                usage=TokenUsage(3, 2),
                model_calls=1,
                reported_usage_calls=1,
                cost=ModelCost("USD", "prices-v1", "0.01", "0.02"),
                priced_usage_calls=1,
            )
            return SimpleNamespace(result=result)

    monkeypatch.setattr(cli_module, "load_local_runtime_config", lambda path: object())
    runtime = Runtime()
    monkeypatch.setattr(
        cli_module,
        "assemble_local_runtime",
        lambda config, state_root, tool_bindings: runtime,
    )
    report = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "evaluate",
            str(dataset),
            "--config",
            str(tmp_path / "config.json"),
            "--report",
            str(report),
            "--confirm-model-call",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    persisted = report.read_text(encoding="utf-8")
    assert payload["passed"] == 1
    assert payload["usage"]["input_tokens"] == 3
    assert payload["usage"]["output_tokens"] == 2
    assert payload["usage_complete"] is True
    assert payload["cost"]["total"] == "0.03"
    assert payload["cost_complete"] is True
    assert "output" not in payload["cases"][0]
    assert "secret prompt" not in persisted
    assert "VISIBLE_OUTPUT" not in persisted
    assert runtime.closed is True
