"""Draft trusted-cache integration regressions; execution needs authorization."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("textual")
from textual.app import App

import w_agent.tui_replay as ui
import w_agent._cli_replay as cache_io
from w_agent import (
    JsonlRunStore, JsonSessionStore, MessageRole, RunEvent, RunEventType,
    SessionMessage, SessionRecord, SessionRunRecord, TokenUsage,
)
from w_agent._cli_replay import ViewOptions, run_view, session_view


async def seed(tmp_path, kind="run"):
    root = tmp_path / ".wagent"
    runs = JsonlRunStore(root)
    for run_id in ("first", "second"):
        await runs.append(RunEvent(1, RunEventType.MODEL_TEXT_DELTA, run_id,
            {"step": 1, "block_index": 0, "text": "PRIVATE\x1b[2J\u202e[red]"}, session_id="session"))
        await runs.append(RunEvent(2, RunEventType.TOKEN_USAGE, run_id,
            {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}, session_id="session"))
    await JsonSessionStore(root / "sessions").save(SessionRecord(
        "session", "title", messages=(SessionMessage(MessageRole.USER, "PRIVATE_INPUT", "first"),),
        runs=tuple(SessionRunRecord(key, "agent", "completed", "answer", TokenUsage(3, 2), True, 1, 0)
                   for key in ("first", "second")),
    ))
    return ui.ReplaySelection(kind, "first" if kind == "run" else "session", root, root / "sessions")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["run", "session"])
async def test_export_import_continues_and_is_cli_compatible(tmp_path, kind):
    selection = await seed(tmp_path, kind)
    first = await ui.read_replay_view(selection, event_limit=1, run_limit=1)
    path = tmp_path / "snapshot.json"
    ui.export_replay_view(first, path, confirmed=True, save_confirmed=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["cache"]["snapshot"] == first.snapshot.to_dict()
    assert "PRIVATE" not in path.read_text(encoding="utf-8")
    # Offset is explicit; import never trusts page metadata as execution authority.
    resumed = await ui.import_replay_view(selection, path, confirmed=True, trusted=True)
    whole = await ui.read_replay_view(selection)
    assert resumed.snapshot == whole.snapshot
    options = ViewOptions(confirm_sensitive=True, trust_snapshot=True)
    rendered = (await run_view(selection.identifier, selection.state_root, options=options, snapshot=path)
                if kind == "run" else await session_view(selection.identifier, selection.state_root,
                    selection.session_root, options=options, snapshot=path))
    assert json.loads(rendered)["cache"]["snapshot"] == whole.snapshot.to_dict()
    cli_path = tmp_path / "cli.json"
    cli_path.write_text(rendered, encoding="utf-8")
    assert (await ui.import_replay_view(selection, cli_path, confirmed=True, trusted=True)).snapshot == whole.snapshot


@pytest.mark.asyncio
async def test_confirmations_precede_any_path_access(tmp_path, monkeypatch):
    selection = ui.ReplaySelection("run", "first", tmp_path, tmp_path / "sessions")
    def forbidden(*args, **kwargs):
        pytest.fail("path accessed before consent")
    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    for confirmed, secondary in ((False, False), (True, False), (False, True)):
        with pytest.raises(ui.ReplayReadError, match="TRUST CACHE"):
            await ui.import_replay_view(selection, tmp_path / "cache.json", confirmed=confirmed, trusted=secondary)
        with pytest.raises(ui.ReplayReadError, match="SAVE CACHE"):
            ui.export_replay_view(None, tmp_path / "cache.json", confirmed=confirmed, save_confirmed=secondary)


@pytest.mark.asyncio
async def test_sensitive_roundtrip_is_escaped_and_projection_mismatch_rejected(tmp_path):
    selection = replace(await seed(tmp_path), text=True)
    first = await ui.read_replay_view(selection, confirmed=True, event_limit=1)
    path = tmp_path / "private.json"
    ui.export_replay_view(first, path, confirmed=True, save_confirmed=True)
    raw = path.read_text(encoding="utf-8")
    assert "PRIVATE" in raw and "\x1b" not in raw and "\u202e" not in raw
    assert r"\u001b" in raw and r"\u202e" in raw
    resumed = await ui.import_replay_view(selection, path, confirmed=True, trusted=True)
    assert "PRIVATE" in resumed.body
    with pytest.raises(ui.ReplayReadError, match="Cache import failed"):
        await ui.import_replay_view(replace(selection, text=False), path, confirmed=True, trusted=True)
    assert first.snapshot.cursor.sequence == 1


@pytest.mark.asyncio
async def test_source_and_identifier_mismatch_rejected(tmp_path):
    selection = await seed(tmp_path)
    first = await ui.read_replay_view(selection)
    path = tmp_path / "cache.json"
    ui.export_replay_view(first, path, confirmed=True, save_confirmed=True)
    other = await seed(tmp_path / "other")
    for changed in (other, replace(selection, identifier="second")):
        with pytest.raises(ui.ReplayReadError):
            await ui.import_replay_view(changed, path, confirmed=True, trusted=True)


@pytest.mark.asyncio
async def test_export_never_overwrites_or_creates_directories_or_store_files(tmp_path):
    selection = await seed(tmp_path)
    view = await ui.read_replay_view(selection)
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    paths = (existing, tmp_path / "missing" / "cache.json", tmp_path / "cache.txt",
             selection.state_root / "runs" / "new.json", selection.session_root / "new.json",
             tmp_path / "existing.json:stream.json")
    for path in paths:
        with pytest.raises(ui.ReplayReadError):
            ui.export_replay_view(view, path, confirmed=True, save_confirmed=True)
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "missing").exists()
    assert all(not path.exists() for path in paths[2:])


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['PRIVATE_INVALID', '{"cache": {}, "cache": {}, "page": {}}',
                                '{"cache": NaN, "page": {}}'])
async def test_malformed_cache_errors_do_not_disclose_content(tmp_path, raw):
    selection = await seed(tmp_path)
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ui.ReplayReadError) as error:
        await ui.import_replay_view(selection, path, confirmed=True, trusted=True)
    assert "PRIVATE" not in str(error.value) and "NaN" not in str(error.value)


@pytest.mark.asyncio
async def test_cache_byte_limit_failure_does_not_write(tmp_path, monkeypatch):
    selection = await seed(tmp_path)
    view = await ui.read_replay_view(selection)
    path = tmp_path / "bounded.json"
    ui.export_replay_view(view, path, confirmed=True, save_confirmed=True)
    monkeypatch.setattr(cache_io, "MAX_CACHE_BYTES", 20)
    with pytest.raises(ui.ReplayReadError):
        await ui.import_replay_view(selection, path, confirmed=True, trusted=True)
    output = tmp_path / "oversized.json"
    with pytest.raises(ui.ReplayReadError):
        ui.export_replay_view(view, output, confirmed=True, save_confirmed=True)
    assert not output.exists()


class PanelApp(App):
    def __init__(self, workspace):
        super().__init__()
        self.panel = ui.ReplayPanel(workspace)

    def compose(self):
        yield self.panel


@pytest.mark.asyncio
@pytest.mark.parametrize("export", [False, True])
async def test_panel_consumes_cache_confirmations_and_rejects_before_io(tmp_path, monkeypatch, export):
    def forbidden(*args, **kwargs):
        pytest.fail("unconfirmed cache action executed")
    monkeypatch.setattr(ui, "import_replay_view", forbidden)
    monkeypatch.setattr(ui, "export_replay_view", forbidden)
    app = PanelApp(tmp_path)
    async with app.run_test():
        panel = app.panel
        panel.query_one("#replay-cache-path").value = "unread.json"
        panel.query_one("#replay-cache-confirm").value = "SAVE CACHE" if export else "TRUST CACHE"
        panel.start_cache(export=export)
        assert not panel._busy and panel._worker is None
        assert panel.query_one("#replay-cache-confirm").value == ""
        assert "VIEW CONTENT" in str(panel.query_one("#replay-status").content)


@pytest.mark.asyncio
async def test_panel_cache_roundtrip_and_failed_import_preserve_view(tmp_path):
    await seed(tmp_path)
    app = PanelApp(tmp_path)
    async with app.run_test(size=(45, 30)) as pilot:
        panel = app.panel
        panel.query_one("#replay-id").value = "first"
        await pilot.pause()
        panel.start_read()
        await panel._worker.wait()
        original = panel._view
        panel.query_one("#replay-cache-path").value = "saved.json"
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.query_one("#replay-cache-confirm").value = "SAVE CACHE"
        panel.start_cache(export=True)
        assert panel.query_one("#replay-import").disabled
        await panel._worker.wait()
        assert (tmp_path / "saved.json").is_file() and panel._view is original
        panel.clear_view()
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.query_one("#replay-cache-confirm").value = "TRUST CACHE"
        panel.start_cache(export=False)
        await panel._worker.wait()
        assert panel._view.snapshot == original.snapshot
        imported = panel._view
        panel.query_one("#replay-cache-path").value = "missing.json"
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.query_one("#replay-cache-confirm").value = "TRUST CACHE"
        panel.start_cache(export=False)
        await panel._worker.wait()
        assert panel._view is imported and not panel._busy


@pytest.mark.asyncio
async def test_clear_during_export_discards_delivery_without_claiming_rollback(tmp_path, monkeypatch):
    await seed(tmp_path)
    entered, release = Event(), Event()
    original = ui.export_replay_view
    calls = []
    def delayed(*args, **kwargs):
        calls.append(args[1])
        entered.set()
        release.wait(5)
        original(*args, **kwargs)
    monkeypatch.setattr(ui, "export_replay_view", delayed)
    app = PanelApp(tmp_path)
    async with app.run_test() as pilot:
        panel = app.panel
        panel.query_one("#replay-id").value = "first"
        await pilot.pause()
        panel.start_read()
        await panel._worker.wait()
        panel.query_one("#replay-cache-path").value = "captured.json"
        panel.query_one("#replay-confirm").value = "VIEW CONTENT"
        panel.query_one("#replay-cache-confirm").value = "SAVE CACHE"
        panel.start_cache(export=True)
        worker = panel._worker
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            panel.start_cache(export=True)
            panel.start_read()
            assert panel._worker is worker
            panel.clear_view()
        finally:
            release.set()
            await worker.wait()
        assert panel._view is None and len(calls) == 1
        assert (tmp_path / "captured.json").is_file()
        assert "may finish" in str(panel.query_one("#replay-status").content)
        assert not panel.query_one("#replay-export").disabled
