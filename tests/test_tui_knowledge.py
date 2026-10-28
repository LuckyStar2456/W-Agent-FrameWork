"""Draft TUI knowledge entry capture/consent tests; not executed."""

import pytest

pytest.importorskip("textual")

import w_agent.tui as tui


class App(tui.WAgentTui):
    async def on_mount(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("code,query", [("", ""), ("LOAD KNOWLEDGE", ""), ("", "QUERY KNOWLEDGE")])
async def test_tui_requires_both_knowledge_confirmations_before_load(tmp_path, monkeypatch, code, query):
    monkeypatch.setattr(tui, "load_local_runtime_config", lambda *args: pytest.fail("unauthorized config load"))
    app = App(tmp_path)
    async with app.run_test():
        app.query_one("#run-prompt").value = "question"
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-knowledge-entry").value = "host:factory"
        app.query_one("#run-knowledge-query").value = "PRIVATE_QUERY"
        app.query_one("#run-knowledge-code-confirm").value = code
        app.query_one("#run-knowledge-query-confirm").value = query
        await app._run_configured_agent()
        output = str(app.query_one("#run-result").content)
        assert "Rejected" in output and "PRIVATE_QUERY" not in output
        assert all(not app.query_one(f"#run-{name}").value for name in tui._RUN_CONFIRMATIONS)


@pytest.mark.asyncio
async def test_tui_captures_knowledge_options_and_locks_fields(tmp_path):
    app = App(tmp_path)
    async with app.run_test(size=(50, 30)):
        app.query_one("#run-prompt").value = "question"
        app.query_one("#run-confirm").value = "RUN"
        app.query_one("#run-history").value = "none"
        app.query_one("#run-knowledge-entry").value = "host:factory"
        app.query_one("#run-knowledge-query").value = "original"
        app.query_one("#run-knowledge-code-confirm").value = "LOAD KNOWLEDGE"
        app.query_one("#run-knowledge-query-confirm").value = "QUERY KNOWLEDGE"
        request = app._capture_agent_run()
        assert request is not None and request.knowledge.query == "original"
        app._lock_agent_run(True)
        assert all(app.query_one(f"#run-{name}").disabled for name in tui._RUN_FIELDS)
        app.query_one("#run-knowledge-query").value = "changed"
        assert request.knowledge.runtime_options() == {"knowledge_query": "original", "confirm_knowledge_query": True}
        app._lock_agent_run(False)
