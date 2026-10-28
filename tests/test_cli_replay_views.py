"""Draft CLI view regressions; execution requires separate user authorization."""

import asyncio
import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from w_agent import (
    JsonlRunStore, JsonSessionStore, MessageRole, RunEvent, RunEventType,
    SessionMessage, SessionRecord, SessionRunRecord, TokenUsage,
    ImageContent, ModelMessage, StandardSessionInputRecorder,
)
from w_agent.cli import app
from w_agent import _cli_replay as views


runner = CliRunner()
CONFIRM = ["--confirm-sensitive-content", "--trust-snapshot"]


@pytest.fixture
def records(tmp_path):
    async def seed():
        runs = JsonlRunStore(tmp_path)
        for key in ("first", "second"):
            values = [
                (RunEventType.MODEL_TEXT_DELTA, {"step": 1, "block_index": 0,
                                                "text": "PRIVATE_MODEL\x1b[2J\u202e[red]"}),
                (RunEventType.TOOL_COMPLETED, {"step": 1, "name": "PRIVATE_TOOL", "call_id": "PRIVATE_CALL",
                                               "outcome": "succeeded", "result_recording": "recorded",
                                               "result": {"kind": "text", "text": "PRIVATE_RESULT"}}),
                (RunEventType.TOKEN_USAGE, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
            ]
            for index, (kind, data) in enumerate(values, 1):
                await runs.append(RunEvent(index, kind, key, session_id="session", data=data))
        await JsonSessionStore(tmp_path / "sessions").save(SessionRecord(
            "session", "PRIVATE_TITLE",
            messages=tuple(SessionMessage(MessageRole.USER, "PRIVATE_INPUT", key) for key in ("first", "second")),
            runs=tuple(SessionRunRecord(key, "agent", "completed", "PRIVATE_OUTPUT",
                                       TokenUsage(3, 2), True, 1, 1) for key in ("first", "second")),
        ))
    asyncio.run(seed())
    return tmp_path


def _run(root, *args, key="first"):
    return runner.invoke(app, ["run-view", key, "--state-root", str(root), *args])


def _session(root, *args):
    return runner.invoke(app, ["session", "view", "session", "--state-root", str(root),
                               "--root", str(root / "sessions"), *args])


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _save(root, payload, name="view.json"):
    path = root / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_safe_default_and_snapshot_paging(records):
    before = {p: p.read_bytes() for p in records.rglob("*") if p.is_file()}
    first = _json(_run(records, "--limit", "1"))
    assert "PRIVATE" not in json.dumps(first)
    assert first["page"] == {"events_applied": 1, "has_more": True}
    assert {p: p.read_bytes() for p in records.rglob("*") if p.is_file()} == before
    path = _save(records, first)
    final = _json(_run(records, "--snapshot", path, *CONFIRM))
    assert final["cache"] == _json(_run(records))["cache"]
    assert final["page"] == {"events_applied": 2, "has_more": False}
    final_path = _save(records, final, "next.json")
    again = _json(_run(records, "--snapshot", final_path, *CONFIRM))
    assert again["page"] == {"events_applied": 0, "has_more": False}
    assert again["cache"]["snapshot"]["state"]["usage"]["total_tokens"] == 5


@pytest.mark.parametrize("args", [
    ["--include-text"], ["--include-tools"], ["--include-tool-results"],
    ["--media", "references"], ["--media", "content"],
    ["--snapshot", "missing.json"],
    ["--snapshot", "missing.json", "--confirm-sensitive-content"],
])
def test_authorization_before_any_source_access(tmp_path, monkeypatch, args):
    def forbidden(*args, **kwargs):
        pytest.fail("filesystem preflight before authorization")
    monkeypatch.setattr(views, "_directory", forbidden)
    result = _run(tmp_path / "absent", *args)
    assert result.exit_code != 0
    assert "require" in result.output


def test_session_text_requires_independent_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(views, "_directory", lambda *a: pytest.fail("unauthorized access"))
    assert _session(tmp_path, "--include-session-text").exit_code != 0


def test_disclosures_are_independent_and_terminal_safe(records):
    results = _run(records, "--include-tool-results", "--confirm-sensitive-content")
    body = _json(results)
    assert "PRIVATE_RESULT" in results.stdout
    assert "PRIVATE_TOOL" not in results.stdout and "PRIVATE_MODEL" not in results.stdout
    assert body["cache"]["snapshot"]["state"]["tool_events"][0]["result"]["text"] == "PRIVATE_RESULT"
    model = _run(records, "--include-text", "--confirm-sensitive-content")
    _json(model)
    assert "PRIVATE_MODEL" in model.stdout and "PRIVATE_RESULT" not in model.stdout
    assert "\x1b" not in model.stdout and "\u202e" not in model.stdout
    assert r"\u001b" in model.stdout and r"\u202e" in model.stdout


def test_session_membership_paging_and_separate_text(records):
    first = _json(_session(records, "--run-limit", "1", "--event-limit", "1"))
    assert first["page"]["next_run_offset"] == 1
    assert first["page"]["pending_run_ids"] == ["first", "second"]
    path = _save(records, first)
    second = _json(_session(records, "--snapshot", path, *CONFIRM, "--run-offset", "1"))
    assert second["page"]["next_run_offset"] is None
    assert second["page"]["pending_run_ids"] == ["first"]
    path = _save(records, second, "second.json")
    final = _json(_session(records, "--snapshot", path, *CONFIRM))
    assert final["cache"] == _json(_session(records))["cache"]
    text = _session(records, "--include-session-text", "--confirm-sensitive-content")
    _json(text)
    assert "PRIVATE_INPUT" in text.stdout and "PRIVATE_MODEL" not in text.stdout
    assert "PRIVATE_TITLE" not in text.stdout and "PRIVATE_OUTPUT" not in text.stdout


@pytest.mark.parametrize("change", ["source", "kind", "schema", "extra", "run", "reducer"])
def test_cache_binding_rejects_mismatch(records, change):
    payload = _json(_run(records, "--limit", "1"))
    if change == "source":
        payload["cache"]["sources"]["runs"] += "-other"
    elif change == "kind":
        payload["cache"]["kind"] = "session"
    elif change == "schema":
        payload["cache"]["schema_version"] = True
    elif change == "extra":
        payload["cache"]["extra"] = "PRIVATE_BAD"
    elif change == "run":
        payload["cache"]["snapshot"]["cursor"]["run_id"] = "second"
    else:
        payload["cache"]["snapshot"]["reducer"] = "PRIVATE_BAD"
    path = _save(records, payload)
    result = _run(records, "--snapshot", path, *CONFIRM)
    assert result.exit_code != 0 and "PRIVATE_BAD" not in result.output
    assert json.loads((records / "view.json").read_text(encoding="utf-8")) == payload


def test_changed_disclosure_policy_requires_rebuild(records):
    path = _save(records, _json(_run(records)))
    assert _run(records, "--snapshot", path, *CONFIRM, "--include-text").exit_code != 0
    path = _save(records, _json(_session(records)))
    assert _session(records, "--snapshot", path, *CONFIRM, "--include-session-text").exit_code != 0


@pytest.mark.parametrize("content", ['{"cache": 1, "cache": 2, "page": {}}', '{"PRIVATE_BAD": NaN}', 'PRIVATE_BAD'])
def test_invalid_json_is_sanitized(records, content):
    path = records / "broken.json"
    path.write_text(content, encoding="utf-8")
    result = _run(records, "--snapshot", str(path), *CONFIRM)
    assert result.exit_code != 0 and "PRIVATE_BAD" not in result.output


def test_cache_byte_limits(records, monkeypatch):
    path = _save(records, _json(_run(records)))
    monkeypatch.setattr(views, "MAX_CACHE_BYTES", 20)
    result = _run(records, "--snapshot", path, *CONFIRM)
    assert result.exit_code != 0 and "64 MiB" in result.output
    assert _run(records).exit_code != 0


def test_missing_roots_and_invalid_limits_do_not_create_stores(tmp_path):
    absent = tmp_path / "absent"
    assert _run(absent).exit_code != 0
    assert _session(absent).exit_code != 0
    for value in ("0", "501", "-1"):
        assert _run(absent, "--limit", value).exit_code != 0
    assert _session(absent, "--run-limit", "33").exit_code != 0
    assert _session(absent, "--event-limit", "501").exit_code != 0
    assert not absent.exists()


def test_missing_run_is_not_empty_success(records):
    assert _run(records, key="missing").exit_code != 0
    assert _run(records, key="../escape").exit_code != 0


def test_session_input_media_is_separate_and_requires_confirmation(records):
    async def seed_input():
        store = JsonSessionStore(records / "sessions")
        record = await store.get("session")
        payload = StandardSessionInputRecorder().record(ModelMessage(MessageRole.USER, (
            ImageContent(url="https://example.test/PRIVATE_INPUT_IMAGE"),)))
        first = replace(record.messages[0], recorded_input=payload)
        await store.save(replace(record, messages=(first, *record.messages[1:]), schema_version=2))
    asyncio.run(seed_input())
    assert "PRIVATE_INPUT_IMAGE" not in _session(records).stdout
    safe = _json(_session(records, "--input-media", "metadata"))
    assert safe["cache"]["snapshot"]["runs"][0]["messages"][0]["input_blocks"][0]["kind"] == "image"
    assert "PRIVATE_INPUT_IMAGE" not in json.dumps(safe)
    assert _session(records, "--input-media", "references").exit_code != 0
    rich = _session(records, "--input-media", "references", "--confirm-sensitive-content")
    _json(rich)
    assert "PRIVATE_INPUT_IMAGE" in rich.stdout
    assert "PRIVATE_MODEL" not in rich.stdout and "PRIVATE_RESULT" not in rich.stdout
    path = _save(records, safe)
    assert _session(records, "--snapshot", path, *CONFIRM).exit_code != 0
