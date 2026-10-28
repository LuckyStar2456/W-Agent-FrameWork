"""Copy beside the three examples; run only with the installed candidate wheel.

This is deliberately independent of pytest and repository import paths. It
asserts installation provenance and checks Python, CLI and a headless TUI.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import w_agent
from w_agent import execute_application_entry, load_application_call

import coding_harness
import custom_harness
import support_harness


async def check_tui(entry, path, expected):
    from textual.app import App
    from textual.widgets import Input, Static
    from w_agent.tui_application import ApplicationPanel

    class DeliveryApp(App):
        def compose(self):
            yield ApplicationPanel(path.parent)

    app = DeliveryApp()
    async with app.run_test(size=(110, 35)):
        panel = app.query_one(ApplicationPanel)
        app.query_one("#application-entry", Input).value = entry
        app.query_one("#application-input", Input).value = path.name
        app.query_one("#application-confirm", Input).value = "RUN APPLICATION"
        panel._begin()
        await panel._operation_task
        actual = str(app.query_one("#application-result", Static).content)
        assert json.loads(actual) == {"result": expected}, actual


async def main():
    package = Path(w_agent.__file__).resolve()
    assert sys.prefix != sys.base_prefix, "acceptance requires an isolated virtual environment"
    assert package.is_relative_to(Path(sys.prefix).resolve()), f"not installed: {package}"
    assert await custom_harness.run_demo() == ("LOCAL:HELLO", ("LOCAL:HELLO",), True)
    support = await support_harness.run_demo()
    assert support["closed"] and support["reply"]["source"] == "local-faq"
    coding = await coding_harness.run_demo()
    assert coding["closed"] and coding["revisions"] == 1
    root = Path(__file__).resolve().parent
    child_environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    cases = []
    for name in ("custom_harness", "support_harness", "coding_harness"):
        entry = f"{name}:create_project"
        path = root / f"{name}_call.json"
        expected = await execute_application_entry(entry, load_application_call(path), confirmed=True)
        process = await asyncio.to_thread(subprocess.run, [
            sys.executable, "-m", "w_agent.cli", "application", "run",
            "--entry", entry, "--input-file", str(path), "--confirm-code",
        ], cwd=root, env=child_environment, capture_output=True, text=True,
           encoding="utf-8", timeout=30, check=True)
        assert json.loads(process.stdout) == {"result": expected}, process.stdout
        await check_tui(entry, path, expected)
        demo = await asyncio.to_thread(subprocess.run, [sys.executable, str(root / f"{name}.py")],
                                       cwd=root, env=child_environment,
                                       capture_output=True, text=True, encoding="utf-8",
                                       timeout=30, check=True)
        if name == "custom_harness":
            assert "LOCAL:HELLO" in demo.stdout and "journal_closed=True" in demo.stdout
        else:
            assert json.loads(demo.stdout)["closed"] is True
        cases.append({"project": name, "python": True, "cli": True, "headless_tui": True,
                      "script_entrypoint": True})

    # Also mount the real TUI shell from the installed package. Avoid contacting
    # Docker: sandbox availability is unrelated to application composition.
    from textual.widgets import TabPane
    from w_agent.tui import WAgentTui

    async def no_docker_probe():
        return False

    with patch("w_agent.tui.DockerSandboxProvider.available", new=staticmethod(no_docker_probe)):
        async with WAgentTui(root).run_test(size=(140, 50)) as pilot:
            assert "application" in {pane.id for pane in pilot.app.query(TabPane)}
            assert "Workspace:" in str(pilot.app.query_one("#home-summary").content)

    for command in ("wagent", "w-agent"):
        scripts = Path(sys.executable).parent
        executable = scripts / (f"{command}.exe" if sys.platform == "win32" else command)
        help_result = await asyncio.to_thread(subprocess.run, [str(executable), "--help"],
                                              cwd=root, env=child_environment,
                                              capture_output=True, text=True,
                                              encoding="utf-8", timeout=30, check=True)
        assert "application" in help_result.stdout
    print(json.dumps({"package": str(package), "python": sys.version.split()[0],
                      "lifecycle_demos": 3, "projects": cases,
                      "full_tui_mount": True, "console_aliases": True}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
