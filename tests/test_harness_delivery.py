"""M5 developer delivery and final-invariant regressions; all offline."""

from pathlib import Path
import subprocess
import sys

import pytest

from examples import coding_harness, custom_harness, support_harness
from w_agent import (
    ApplicationContext, ApplicationPlugin, BorrowedComponent, ComponentDefinition,
    ComponentRef, PluginManager, PostConstruct, PreDestroy, ServiceComponent,
    compile_assembly, compile_configured, compile_decorated,
)


async def test_custom_harness_has_no_default_loop_and_closes_storage():
    assert await custom_harness.run_demo() == ("LOCAL:HELLO", ("LOCAL:HELLO",), True)


async def test_support_scanning_injection_lifecycle_and_aspects():
    result = await support_harness.run_demo()
    assert result["reply"] == {
        "answer": "Friendly: Demo orders ship within two working days.",
        "source": "local-faq", "handoff": False,
    }
    assert result["lifecycle"] == ["store-open", "harness-ready", "reply-saved", "harness-closed", "store-closed"]
    assert result["trace"] == ["before:answer", "finally:success"]
    assert result["closed"] is True


async def test_support_unknown_question_does_not_invent_an_answer():
    async with support_harness.create_project().open() as host:
        result = await host.invoke("run", "Can you make a special exception?")
    assert result["handoff"] is True and result["source"] == "handoff"


async def test_configured_coding_preview_approval_and_lifecycle():
    result = await coding_harness.run_demo()
    assert result["applied"]["content"] == "greeting = 'framework'\nprint(greeting)\n"
    assert result["revisions"] == 1 and result["closed"] is True
    assert result["trace"] == ["before:preview", "finally:success", "before:apply", "finally:success"]


async def test_coding_tool_approval_survives_removal_of_trace():
    project = coding_harness.create_project()
    # Explicitly remove the optional aspect, not the mandatory tool check.
    plan = compile_assembly(project.plan.components)
    async with ApplicationContext(plan) as app:
        workspace = app.resolve("coding_store")
        original = dict(workspace.files)
        async with app.scope("run", "attempt") as run:
            with pytest.raises(PermissionError):
                await run.resolve("coding").apply("hello.py", greeting="framework", approved_digest="")
        assert workspace.files == original and workspace.revisions == []


async def test_coding_rejects_changed_preview_and_stale_source():
    async with coding_harness.create_project().open() as host:
        preview = await host.invoke("preview", "hello.py", greeting="framework")
        with pytest.raises(PermissionError):
            await host.invoke("apply", "hello.py", greeting="different", approved_digest=preview["digest"])
        workspace = host.context.resolve("coding_store")
        assert workspace.revisions == []
        proposal = coding_harness.PatchProposal(preview["path"], preview["before"], preview["after"])
        workspace.files["hello.py"] = "changed independently"
        with pytest.raises(ValueError, match="source changed"):
            host.context.resolve("patch_tool").apply(proposal, approved_digest=proposal.digest)


async def test_three_assembly_modes_preserve_failed_start_borrowing_and_cleanup():
    results = []
    for mode in ("python", "decorator", "configuration"):
        events = []

        class HostStore:
            def close(self):
                pytest.fail("borrowed host resource was closed")

        external = HostStore()

        @ServiceComponent("harness")
        class Harness:
            def __init__(self, store):
                assert store is external

            @PostConstruct
            def initialize(self):
                events.append("start")
                raise RuntimeError("startup-failed")

            @PreDestroy
            def close(self):
                events.append("close")

        borrowed = BorrowedComponent("store", external)
        if mode == "python":
            plan = compile_assembly((borrowed, ComponentDefinition(
                "harness", Harness, {"store": ComponentRef("store")},
                initialize=Harness.initialize, dispose=Harness.close,
            )))
        elif mode == "decorator":
            plan = compile_decorated((borrowed, Harness))
        else:
            plan = compile_configured({"components": ["store", "harness"]},
                                       catalog={"store": borrowed, "harness": Harness})
        with pytest.raises(RuntimeError, match="startup-failed"):
            async with ApplicationContext(plan):
                pass
        results.append(events)
    assert results == [["start", "close"]] * 3


async def test_plugin_bridge_preserves_custom_scope_order():
    disposed = []
    order = ("application", "workspace", "session", "dialogue", "agent", "run", "step")
    plugin = ApplicationPlugin(name="custom-scopes", version="1", scope_order=order,
                               components=(ComponentDefinition("turn", object, scope="dialogue",
                                                               dispose=disposed.append),))
    manager = PluginManager()
    try:
        await manager.load(plugin)
        assert plugin.application.plan.scope_order == order
        async with plugin.application.scope("dialogue", "test") as scope:
            instance = scope.resolve("turn")
        assert disposed == [instance]
    finally:
        await manager.close()
    assert disposed == [instance]


def test_custom_core_runs_when_optional_http_and_tui_imports_are_unavailable():
    code = '''
import asyncio
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'httpx', 'textual'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, BlockOptional())
from examples.custom_harness import run_demo
assert asyncio.run(run_demo()) == ('LOCAL:HELLO', ('LOCAL:HELLO',), True)
assert not any(name.split('.')[0] in {'httpx', 'textual'} for name in sys.modules)
print('optional dependencies absent: custom framework passed')
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
