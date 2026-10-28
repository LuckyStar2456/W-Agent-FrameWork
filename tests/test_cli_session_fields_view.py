"""Read-only field-disclosure regression source."""

import asyncio
import json

import pytest
from typer.testing import CliRunner

from w_agent import (
    ImageContent, JsonlRunStore, JsonSessionStore, MessageFieldsSessionInputRecorder,
    MessageRole, ModelMessage, RecordedSessionMessageProjector, RunEvent, RunEventType, SessionMessage, SessionRecord,
    SessionRunRecord, TextContent, TextSessionMessageProjector, TokenUsage,
    build_session_message_projector,
)
from w_agent import _cli_replay as views
from w_agent.cli import app


@pytest.fixture
def records(tmp_path):
    async def seed():
        runs = JsonlRunStore(tmp_path)
        await runs.append(RunEvent(1, RunEventType.TOKEN_USAGE, "run", session_id="session",
                                  data={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}))
        message = ModelMessage(MessageRole.USER, (TextContent("PRIVATE_TEXT"),
            ImageContent(url="https://example.test/PRIVATE_IMAGE")),
            name="PRIVATE_NAME\x1b[2J", metadata={"label": "PRIVATE_METADATA\u202e[red]"})
        recorded = MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True).record(message)
        await JsonSessionStore(tmp_path / "sessions").save(SessionRecord(
            "session", "title", schema_version=2,
            messages=(SessionMessage(MessageRole.USER, "PRIVATE_TEXT", "run", recorded_input=recorded),),
            runs=(SessionRunRecord("run", "agent", "completed", "answer", TokenUsage(1, 1), True, 1, 0),),
        ))
    asyncio.run(seed())
    return tmp_path


def _view(root, *args):
    return CliRunner().invoke(app, ["session", "view", "session", "--state-root", str(root),
                                  "--root", str(root / "sessions"), *args])


def _message(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["cache"]["snapshot"]["runs"][0]["messages"][0]


def test_factory_preserves_default_identity_and_separates_field_modes():
    assert build_session_message_projector().identity == TextSessionMessageProjector().identity
    assert build_session_message_projector(include_text=True).identity == TextSessionMessageProjector(True).identity
    identities = {build_session_message_projector(**options).identity for options in (
        {"input_media": "metadata"}, {"include_name": True}, {"include_metadata": True},
        {"include_name": True, "include_metadata": True},
    )}
    assert len(identities) == 4
    assert build_session_message_projector(input_media="metadata").identity != RecordedSessionMessageProjector().identity


def test_default_and_wrapped_input_media_metadata_hide_fields(records):
    before = {path: path.read_bytes() for path in records.rglob("*") if path.is_file()}
    plain = _view(records)
    blocks = _view(records, "--input-media", "metadata")
    assert plain.exit_code == blocks.exit_code == 0
    assert "PRIVATE" not in plain.stdout and "PRIVATE" not in blocks.stdout
    assert "input_blocks" not in _message(plain)
    assert _message(blocks)["input_blocks"][1]["kind"] == "image"
    assert {path: path.read_bytes() for path in records.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("flag", ["--include-input-name", "--include-input-metadata"])
def test_fields_need_consent_before_filesystem_access(tmp_path, monkeypatch, flag):
    monkeypatch.setattr(views, "_directory", lambda *args: pytest.fail("unauthorized source read"))
    result = _view(tmp_path, flag)
    assert result.exit_code == 2 and "--confirm-sensitive-content" in result.output


def test_field_name_metadata_text_and_media_are_independent(records):
    name = _view(records, "--include-input-name", "--confirm-sensitive-content")
    assert set(_message(name)["input_fields"]) == {"name"}
    assert "PRIVATE_NAME" in name.stdout and "PRIVATE_METADATA" not in name.stdout
    assert "PRIVATE_TEXT" not in name.stdout and "PRIVATE_IMAGE" not in name.stdout
    assert "\x1b" not in name.stdout and r"\u001b" in name.stdout
    metadata = _view(records, "--include-input-metadata", "--confirm-sensitive-content")
    assert set(_message(metadata)["input_fields"]) == {"metadata"}
    assert "PRIVATE_METADATA" in metadata.stdout and "PRIVATE_NAME" not in metadata.stdout
    assert "\u202e" not in metadata.stdout and r"\u202e" in metadata.stdout
    media = _view(records, "--input-media", "references", "--confirm-sensitive-content")
    assert "PRIVATE_IMAGE" in media.stdout and "PRIVATE_NAME" not in media.stdout
    assert "input_fields" not in _message(media)


def test_cache_cannot_cross_field_disclosure_configuration(records, tmp_path):
    first = _view(records, "--include-input-name", "--confirm-sensitive-content")
    _message(first)
    cache = tmp_path / "view.json"
    cache.write_text(first.stdout, encoding="utf-8")
    rejected = _view(records, "--snapshot", str(cache), "--confirm-sensitive-content", "--trust-snapshot")
    assert rejected.exit_code == 2 and "PRIVATE" not in rejected.stdout
    matching = _view(records, "--include-input-name", "--snapshot", str(cache),
                     "--confirm-sensitive-content", "--trust-snapshot")
    assert _message(matching)["input_fields"] == _message(first)["input_fields"]


@pytest.mark.asyncio
async def test_run_view_rejects_session_only_fields_before_io(tmp_path, monkeypatch):
    monkeypatch.setattr(views, "_directory", lambda *args: pytest.fail("wrong-mode source read"))
    with pytest.raises(views.ReplayViewError, match="Session view"):
        await views.run_view("run", tmp_path,
            options=views.ViewOptions(include_input_name=True, confirm_sensitive=True))
