import json

from typer.testing import CliRunner

from w_agent.cli import app

runner = CliRunner()


def test_cli_version_and_profile_json_are_machine_readable():
    version = runner.invoke(app, ["--version"])
    profiles = runner.invoke(app, ["profile", "list", "--json"])

    assert version.exit_code == 0
    assert "2.0.0a1" in version.stdout
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
