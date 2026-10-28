import json

import pytest
import typer
from typer.testing import CliRunner

from w_agent.knowledge_sync_cli import register_knowledge_sync_commands


@pytest.fixture
def app():
    result = typer.Typer()
    register_knowledge_sync_commands(result)
    return result


def test_help_registers_full_chain(app):
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("import", "prepare", "inspect", "execute", "retry-not-sent", "reconcile"):
        assert "knowledge-sync-" + command in result.output


def test_cli_import_preview_save_digest_lock(app, tmp_path):
    (tmp_path / "a.md").write_text("private body", encoding="utf-8")
    args = ["knowledge-sync-import", "--trace-database", str(tmp_path / "trace.db"), "--root", str(tmp_path),
            "--path", "a.md", "--namespace", "manual", "--version", "v1", "--confirm-read"]
    runner = CliRunner()
    preview = runner.invoke(app, args)
    assert preview.exit_code == 0, preview.output
    assert "private body" not in preview.output
    assert not (tmp_path / "trace.db").exists()
    digest = json.loads(preview.output)["preview_digest"]
    rejected = runner.invoke(app, args + ["--confirm-record", "--confirm-create"])
    assert rejected.exit_code == 2 and not (tmp_path / "trace.db").exists()
    saved = runner.invoke(app, args + ["--confirm-record", "--confirm-create", "--expected-preview-digest", digest])
    assert saved.exit_code == 0, saved.output
    assert json.loads(saved.output)["recorded"] and (tmp_path / "trace.db").is_file()


@pytest.mark.parametrize("command", ["knowledge-sync-inspect", "knowledge-sync-execute", "knowledge-sync-prepare", "knowledge-sync-retry-not-sent", "knowledge-sync-reconcile"])
def test_command_help(app, command):
    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0


def test_failure_sanitized_no_missing_database_creation(app, tmp_path):
    result = CliRunner().invoke(app, ["knowledge-sync-inspect", "--journal-database", str(tmp_path / "private.db"),
        "--plan-digest", "a" * 64, "--confirm-read"])
    assert result.exit_code == 2
    assert "private.db" not in result.output and str(tmp_path) not in result.output
    assert not (tmp_path / "private.db").exists()
