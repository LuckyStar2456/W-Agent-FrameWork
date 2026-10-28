"""Draft read-only Session replay tests; execution awaits user authorization."""

import json
from dataclasses import replace

import pytest

from w_agent import (
    ImageContent, InMemoryRunStore, InMemorySessionStore, JsonlRunStore, JsonSessionStore,
    MessageRole, RunEvent, RunEventReplay, RunEventType, SessionEventReplay,
    SessionMessage, SessionRecord, SessionReplayError, SessionReplaySnapshot,
    SessionRunRecord, SessionStatus, StandardMultimodalEventEncoder,
    TextSessionMessageProjector, TokenUsage, TranscriptRunEventReducer,
)


def _run(run_id):
    return SessionRunRecord(run_id, "agent", "completed", "PRIVATE_OUTPUT", TokenUsage(3, 2), True, 1, 1, 1, 1)


def _session(*ids, status=SessionStatus.ACTIVE):
    return SessionRecord(
        "session", "PRIVATE_TITLE", status,
        tuple(SessionMessage(MessageRole.USER, "PRIVATE_INPUT", key) for key in ids),
        tuple(_run(key) for key in ids), metadata={"PRIVATE_METADATA": "secret"},
    )


def _events(run_id, session_id="session"):
    media = StandardMultimodalEventEncoder().encode(ImageContent(data=b"PRIVATE_IMAGE", media_type="image/png"), index=1)
    values = [
        (RunEventType.MODEL_TEXT_DELTA, {"step": 1, "block_index": 0, "text": "PRIVATE_MODEL"}),
        (RunEventType.MODEL_OUTPUT_BLOCK, {"step": 1, "block_index": 1, "block": media}),
        (RunEventType.TOOL_COMPLETED, {"step": 1, "call_id": "call", "name": "tool", "outcome": "succeeded",
                                       "result_recording": "recorded", "result": {"kind": "text", "text": "PRIVATE_RESULT"}}),
        (RunEventType.TOKEN_USAGE, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
        (RunEventType.RUN_COMPLETED, {"stop_reason": "completed"}),
    ]
    return tuple(RunEvent(i, kind, run_id, data, session_id=session_id) for i, (kind, data) in enumerate(values, 1))


async def _stores(*ids):
    sessions, runs = InMemorySessionStore(), InMemoryRunStore()
    await sessions.save(_session(*ids))
    for key in ids:
        for event in _events(key):
            await runs.append(event)
    return sessions, runs


async def test_default_hides_content_and_preserves_separate_run_counters():
    sessions, runs = await _stores("first", "second")
    before = await sessions.get("session")
    page = await SessionEventReplay(sessions, RunEventReplay(runs)).page("session")
    assert "PRIVATE" not in json.dumps(page.snapshot.to_dict())
    assert page.events_applied == 10 and page.runs_read == ("first", "second")
    assert page.next_run_offset is None and page.snapshot.pending_run_ids == ()
    assert [view.replay.state["usage"]["total_tokens"] for view in page.snapshot.runs] == [5, 5]
    assert await sessions.get("session") == before
    assert len(await runs.events("first")) == 5


async def test_rich_json_snapshot_restart_matches_single_page_and_keeps_inputs_separate(tmp_path):
    sessions, runs = JsonSessionStore(tmp_path / "sessions"), JsonlRunStore(tmp_path)
    await sessions.save(_session("first", "second"))
    for key in ("first", "second"):
        for event in _events(key):
            await runs.append(event)
    reducer = TranscriptRunEventReducer(include_text=True, include_tools=True, include_tool_results=True, media_mode="content")
    projector = TextSessionMessageProjector(include_text=True)
    reader = SessionEventReplay(sessions, RunEventReplay(runs), reducer=reducer, message_projector=projector)
    whole = await reader.page("session")
    first = await reader.page("session", run_limit=1, event_limit=2)
    assert first.next_run_offset == 1 and first.snapshot.pending_run_ids == ("first", "second")
    restored = SessionReplaySnapshot.from_dict(json.loads(json.dumps(first.snapshot.to_dict())))
    reopened = SessionEventReplay(JsonSessionStore(tmp_path / "sessions"), RunEventReplay(JsonlRunStore(tmp_path)),
                                  reducer=reducer, message_projector=projector)
    second = await reopened.page("session", snapshot=restored, run_offset=1, run_limit=1)
    final = await reopened.page("session", snapshot=second.snapshot, run_offset=0, run_limit=1)
    assert final.snapshot == whole.snapshot
    view = final.snapshot.runs[0]
    assert view.messages[0]["text"] == "PRIVATE_INPUT"
    assert view.replay.state["blocks"][0]["text"] == "PRIVATE_MODEL"
    assert view.replay.state["blocks"][1]["media"]["data_base64"]
    assert view.replay.state["tool_events"][0]["result"]["text"] == "PRIVATE_RESULT"
    assert "PRIVATE_TITLE" not in json.dumps(final.snapshot.to_dict())
    with pytest.raises(TypeError):
        view.messages[0]["text"] = "changed"
    detached = final.snapshot.to_dict()
    detached["runs"][0]["messages"][0]["text"] = "changed"
    assert view.messages[0]["text"] == "PRIVATE_INPUT"


async def test_old_run_updates_and_new_members_are_seen_without_duplicate_events():
    sessions, runs = await _stores("first", "second")
    reader = SessionEventReplay(sessions, RunEventReplay(runs))
    first = await reader.page("session")
    await runs.append(RunEvent(6, RunEventType.RUN_RESUMED, "first", session_id="session"))
    await sessions.save(_session("first", "second", "third"))
    for event in _events("third"):
        await runs.append(event)
    newest = await reader.page("session", snapshot=first.snapshot, run_offset=2)
    assert newest.runs_read == ("third",) and newest.events_applied == 5
    # A completed sweep is not a permanent end-of-log acknowledgement.
    refreshed = await reader.page("session", snapshot=newest.snapshot, run_offset=0)
    assert refreshed.events_applied == 1
    assert refreshed.snapshot.runs[0].replay.state["stop_reason"] is None
    assert refreshed.snapshot.runs[0].replay.state["usage"]["total_tokens"] == 5


@pytest.mark.parametrize("event_session", [None, "other"])
async def test_session_event_ownership_fails_closed_except_explicit_unscoped_mode(event_session):
    sessions, runs = await _stores()
    await sessions.save(_session("first"))
    for event in _events("first", event_session):
        await runs.append(event)
    with pytest.raises(SessionReplayError):
        await SessionEventReplay(sessions, RunEventReplay(runs)).page("session")
    compatible = SessionEventReplay(sessions, RunEventReplay(runs), allow_unscoped_events=True)
    if event_session is None:
        assert (await compatible.page("session")).events_applied == 5
    else:
        with pytest.raises(SessionReplayError):
            await compatible.page("session")


async def test_archived_and_empty_sessions_are_readable_but_missing_is_not():
    sessions, runs = await _stores()
    await sessions.save(_session(status=SessionStatus.ARCHIVED))
    reader = SessionEventReplay(sessions, RunEventReplay(runs))
    page = await reader.page("session")
    assert page.snapshot.runs == () and page.events_applied == 0
    assert page.next_run_offset is None
    assert (await sessions.get("session")).status is SessionStatus.ARCHIVED
    with pytest.raises(SessionReplayError):
        await reader.page("missing")


async def test_membership_reorder_or_orphan_messages_reject_existing_snapshot():
    sessions, runs = await _stores("first", "second")
    reader = SessionEventReplay(sessions, RunEventReplay(runs))
    first = await reader.page("session", run_limit=1)
    await sessions.save(_session("second", "first"))
    with pytest.raises(SessionReplayError):
        await reader.page("session", snapshot=first.snapshot)
    await sessions.save(replace(_session("first"), messages=(SessionMessage(MessageRole.USER, "secret", "other"),)))
    with pytest.raises(SessionReplayError):
        await reader.page("session")


async def test_projection_options_bind_snapshots_and_custom_projector_can_omit():
    sessions, runs = await _stores("first")
    replay = RunEventReplay(runs)
    first = await SessionEventReplay(sessions, replay).page("session")
    rich = SessionEventReplay(sessions, replay, message_projector=TextSessionMessageProjector(True))
    with pytest.raises(ValueError):
        await rich.page("session", snapshot=first.snapshot)
    with pytest.raises(ValueError):
        await rich.page("other", snapshot=first.snapshot)
    class Omit:
        identity = "application.omit/1"
        def project(self, message):
            return None
    omitted = await SessionEventReplay(sessions, replay, message_projector=Omit()).page("session")
    assert omitted.snapshot.runs[0].messages == ()


async def test_custom_run_reducer_and_message_projection_failures_are_isolated():
    sessions, runs = await _stores("first")
    class Counter:
        identity = "application.counter/1"
        def initial_state(self):
            return {"count": 0}
        def reduce(self, state, event):
            return {"count": state["count"] + 1}
    page = await SessionEventReplay(sessions, RunEventReplay(runs), reducer=Counter()).page("session")
    assert page.snapshot.runs[0].replay.state["count"] == 5
    class BrokenProjector:
        identity = "application.broken/1"
        def project(self, message):
            raise ValueError("PRIVATE_PROJECTION_ERROR")
    with pytest.raises(SessionReplayError) as caught:
        await SessionEventReplay(sessions, RunEventReplay(runs), message_projector=BrokenProjector()).page("session")
    assert "PRIVATE" not in str(caught.value)


async def test_message_count_and_text_limits_reject_without_truncation():
    sessions, runs = await _stores("first")
    original = await sessions.get("session")
    await sessions.save(replace(original, messages=original.messages * 2))
    with pytest.raises(SessionReplayError):
        await SessionEventReplay(sessions, RunEventReplay(runs), max_messages_per_run=1).page("session")
    with pytest.raises(SessionReplayError):
        await SessionEventReplay(sessions, RunEventReplay(runs), message_projector=TextSessionMessageProjector(max_text_chars=2)).page("session")


async def test_source_change_or_late_failure_never_mutates_input_snapshot():
    sessions, runs = await _stores("first", "second")
    first = await SessionEventReplay(sessions, RunEventReplay(runs)).page("session", run_limit=1, event_limit=1)
    saved = first.snapshot.to_dict()
    class BrokenReplay:
        async def page(self, run_id, **kwargs):
            if run_id == "second":
                raise RuntimeError("PRIVATE_SOURCE_ERROR")
            return await RunEventReplay(runs).page(run_id, **kwargs)
    with pytest.raises(SessionReplayError) as caught:
        await SessionEventReplay(sessions, BrokenReplay()).page("session", snapshot=first.snapshot)
    assert "PRIVATE" not in str(caught.value) and caught.value.__cause__ is None
    assert first.snapshot.to_dict() == saved
    class ChangingReplay:
        async def page(self, run_id, **kwargs):
            await sessions.save(_session("first", "second", "third"))
            return await RunEventReplay(runs).page(run_id, **kwargs)
    with pytest.raises(SessionReplayError):
        await SessionEventReplay(sessions, ChangingReplay()).page("session", snapshot=first.snapshot)
    assert first.snapshot.to_dict() == saved


@pytest.mark.parametrize("options", [{"max_runs": 1}, {"max_snapshot_bytes": 80}, {"max_run_snapshot_bytes": 80}])
async def test_snapshot_and_membership_limits_fail_without_truncation(options):
    sessions, runs = await _stores("first", "second")
    with pytest.raises(SessionReplayError):
        await SessionEventReplay(sessions, RunEventReplay(runs), **options).page("session")


async def test_strict_envelopes_and_request_limits():
    sessions, runs = await _stores("first")
    reader = SessionEventReplay(sessions, RunEventReplay(runs))
    first = await reader.page("session")
    data = first.snapshot.to_dict()
    with pytest.raises(ValueError):
        SessionReplaySnapshot.from_dict({**data, "schema_version": True})
    with pytest.raises(ValueError):
        SessionReplaySnapshot.from_dict({**data, "unknown": 1})
    for options in ({"run_limit": True}, {"event_limit": 1001}, {"run_offset": -1}):
        with pytest.raises(ValueError):
            await reader.page("session", **options)
