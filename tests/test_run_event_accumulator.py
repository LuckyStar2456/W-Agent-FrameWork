"""Pure replay accumulation regressions."""

import json

import pytest

from w_agent import (
    ImageContent, JsonlRunStore, MediaProjectionMode, RunEvent, RunEventAccumulator,
    RunEventCursor, RunEventReplay, RunEventType, RunReplaySnapshot, RunStoreError,
    StandardMultimodalEventEncoder, TranscriptRunEventReducer,
)


class Pages:
    def __init__(self, events):
        self.events = tuple(events)
        self.reads = []

    async def events_page(self, run_id, after_sequence, limit):
        self.reads.append((run_id, after_sequence, limit))
        return self.events[after_sequence:after_sequence + limit], after_sequence + limit < len(self.events)


def _events():
    media = StandardMultimodalEventEncoder().encode(ImageContent(data=b"PRIVATE_BYTES", media_type="image/png"), index=2)
    values = [
        (RunEventType.MODEL_TEXT_DELTA, {"step": 1, "block_index": 0, "text": "PRIVATE_"}),
        (RunEventType.MODEL_TEXT_DELTA, {"step": 1, "block_index": 0, "text": "TEXT"}),
        (RunEventType.MODEL_TOOL_CALL_DELTA, {"step": 1, "block_index": 1, "call_id": "call", "name": "tool", "arguments_delta": '{"value":'}),
        (RunEventType.MODEL_TOOL_CALL_DELTA, {"step": 1, "block_index": 1, "call_id": "", "name": "", "arguments_delta": '"PRIVATE_ARGUMENT"}'}),
        (RunEventType.MODEL_OUTPUT_BLOCK, {"step": 1, "block_index": 2, "block": media}),
        (RunEventType.MODEL_COMPLETED, {"step": 1, "text": "PRIVATE_TEXT", "finish_reason": "tool-calls"}),
        (RunEventType.TOOL_REQUESTED, {"step": 1, "call_id": "call", "name": "tool", "arguments": {"value": "PRIVATE_ARGUMENT"}}),
        (RunEventType.TOOL_COMPLETED, {"step": 1, "call_id": "call", "name": "tool", "outcome": "needs-approval"}),
        (RunEventType.TOKEN_USAGE, {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}),
        (RunEventType.RUN_COMPLETED, {"stop_reason": "needs-approval"}),
        (RunEventType.RUN_RESUMED, {}),
        (RunEventType.TOOL_COMPLETED, {"step": 1, "call_id": "call", "name": "tool", "outcome": "succeeded"}),
        (RunEventType.TOKEN_USAGE, {"input_tokens": 20, "output_tokens": 6, "total_tokens": 26}),
        (RunEventType.RUN_COMPLETED, {"stop_reason": "completed"}),
    ]
    return tuple(RunEvent(i, kind, "run", data) for i, (kind, data) in enumerate(values, 1))


async def test_default_is_content_free_and_accumulates_counters_without_double_counting():
    source = Pages(_events())
    reader = RunEventAccumulator(RunEventReplay(source), TranscriptRunEventReducer())
    first = await reader.page("run", limit=10)
    assert first.snapshot.state["stop_reason"] == "needs-approval"
    resumed = await reader.page("run", snapshot=first.snapshot, limit=1)
    assert resumed.snapshot.state["stop_reason"] is None
    last = await reader.page("run", snapshot=resumed.snapshot)
    state = last.snapshot.to_dict()["state"]
    serialized = json.dumps(state)
    assert "PRIVATE" not in serialized and "data_base64" not in serialized
    assert "call_id" not in serialized and "arguments" not in serialized
    assert state["usage"]["total_tokens"] == 26 and state["stop_reason"] == "completed"
    assert [item.get("outcome") for item in state["tool_events"]] == [None, "needs-approval", "succeeded"]
    assert source.reads == [("run", 0, 10), ("run", 10, 1), ("run", 11, 100)]


async def test_content_opt_in_page_split_and_rebuild_match_whole_log(tmp_path):
    store = JsonlRunStore(tmp_path)
    for event in _events():
        await store.append(event)
    reducer = TranscriptRunEventReducer(include_text=True, include_tools=True, media_mode="content")
    reader = RunEventAccumulator(RunEventReplay(store), reducer)
    whole = await reader.page("run")
    first = await reader.page("run", limit=3)
    saved = json.loads(json.dumps(first.snapshot.to_dict()))
    restarted = RunEventAccumulator(RunEventReplay(JsonlRunStore(tmp_path)), reducer)
    second = await restarted.page("run", snapshot=RunReplaySnapshot.from_dict(saved))
    assert second.snapshot == whole.snapshot
    state = whole.snapshot.to_dict()["state"]
    assert state["blocks"][0]["text"] == "PRIVATE_TEXT"
    assert state["models"][0]["text"] == "PRIVATE_TEXT"  # Final is separate, not appended to deltas.
    assert json.loads(state["blocks"][1]["arguments_delta"]) == {"value": "PRIVATE_ARGUMENT"}
    assert state["tool_events"][0]["arguments"] == {"value": "PRIVATE_ARGUMENT"}
    assert state["blocks"][2]["media"]["data_base64"]
    empty = await restarted.page("run", snapshot=second.snapshot)
    assert empty.events_applied == 0 and empty.snapshot == second.snapshot


async def test_run_and_disclosure_configuration_cannot_change_with_existing_snapshot():
    replay = RunEventReplay(Pages(_events()))
    initial = await RunEventAccumulator(replay, TranscriptRunEventReducer()).page("run", limit=1)
    with pytest.raises(ValueError):
        await RunEventAccumulator(replay, TranscriptRunEventReducer(include_text=True)).page("run", snapshot=initial.snapshot)
    with pytest.raises(ValueError):
        await RunEventAccumulator(replay, TranscriptRunEventReducer()).page("other", snapshot=initial.snapshot)


async def test_failed_page_never_mutates_original_snapshot_or_exposes_reducer_exception():
    class Failing:
        identity = "application/1"
        def initial_state(self):
            return {"count": 0}
        def reduce(self, state, event):
            state["count"] += 1
            if event.sequence == 3:
                raise ValueError("PRIVATE_ERROR")
            return state
    reader = RunEventAccumulator(RunEventReplay(Pages(_events())), Failing())
    first = await reader.page("run", limit=1)
    before = first.snapshot.to_dict()
    with pytest.raises(RunStoreError) as caught:
        await reader.page("run", snapshot=first.snapshot, limit=3)
    assert "PRIVATE" not in str(caught.value) and caught.value.__cause__ is None
    assert first.snapshot.to_dict() == before
    with pytest.raises(TypeError):
        first.snapshot.state["count"] = 99


@pytest.mark.parametrize("kind", ["text", "block", "size", "media"])
async def test_bounded_or_invalid_events_reject_page(kind):
    events = list(_events())
    reducer = TranscriptRunEventReducer(max_text_chars=2) if kind == "text" else TranscriptRunEventReducer()
    if kind == "block":
        events[1] = RunEvent(2, RunEventType.MODEL_TOOL_CALL_DELTA, "run", {"step": 1, "block_index": 0, "arguments_delta": "{}"})
    if kind == "media":
        events[4] = RunEvent(5, RunEventType.MODEL_OUTPUT_BLOCK, "run", {"step": 1, "block_index": 2,
                             "block": {**events[4].data["block"], "sha256": "0" * 64}})
    reader = RunEventAccumulator(RunEventReplay(Pages(events)), reducer,
                                max_snapshot_bytes=400 if kind == "size" else 8 * 1024 * 1024)
    with pytest.raises(RunStoreError):
        await reader.page("run")


async def test_reference_mode_does_not_fetch_media():
    event = RunEvent(1, RunEventType.MODEL_OUTPUT_BLOCK, "run", {"step": 1, "block_index": 0,
                     "block": {"kind": "image", "source": "url", "media_type": "image/png", "url": "https://example.invalid/PRIVATE"}})
    replay = RunEventReplay(Pages([event]))
    safe = await RunEventAccumulator(replay, TranscriptRunEventReducer()).page("run")
    assert "url" not in safe.snapshot.state["blocks"][0]["media"]
    refs = await RunEventAccumulator(replay, TranscriptRunEventReducer(media_mode=MediaProjectionMode.REFERENCES)).page("run")
    assert refs.snapshot.state["blocks"][0]["media"]["url"].endswith("PRIVATE")


def test_snapshot_envelope_and_deep_immutability():
    snapshot = RunReplaySnapshot(RunEventCursor("run"), "application/1", {"items": [{"value": 1}]})
    with pytest.raises(TypeError):
        snapshot.state["items"][0]["value"] = 2
    data = snapshot.to_dict()
    data["state"]["items"][0]["value"] = 3
    assert snapshot.state["items"][0]["value"] == 1
    with pytest.raises(ValueError):
        RunReplaySnapshot.from_dict({**data, "schema_version": True})


@pytest.mark.parametrize("include_tools", [False, True])
async def test_result_body_requires_its_own_disclosure_switch(include_tools):
    event = RunEvent(1, RunEventType.TOOL_COMPLETED, "run", {
        "step": 1, "call_id": "call", "name": "tool", "outcome": "succeeded",
        "result_recording": "recorded",
        "result": {"kind": "text", "text": "PRIVATE_RESULT", "is_error": False},
    })
    replay = RunEventReplay(Pages([event]))
    safe = await RunEventAccumulator(replay, TranscriptRunEventReducer(include_tools=include_tools)).page("run")
    assert "PRIVATE" not in json.dumps(safe.snapshot.to_dict())
    assert safe.snapshot.state["tool_events"][0]["result_recording"] == "recorded"
    rich = await RunEventAccumulator(replay, TranscriptRunEventReducer(
        include_tools=include_tools, include_tool_results=True,
    )).page("run")
    result = rich.snapshot.state["tool_events"][0]
    assert result["result"]["text"] == "PRIVATE_RESULT"
    assert ("call_id" in result) is include_tools
    with pytest.raises(ValueError):
        await RunEventAccumulator(replay, TranscriptRunEventReducer(include_tool_results=True)).page("run", snapshot=safe.snapshot)


@pytest.mark.parametrize("extra", [
    {"result_recording": "recorded"},
    {"result": {"text": "PRIVATE"}},
    {"result_recording": "omitted", "result": {}},
    {"result_recording": "failed", "result": {}},
    {"result_recording": "recorded", "result": {"text": "x" * 256}},
    {"outcome": "needs-approval", "result_recording": "recorded", "result": {}},
])
async def test_invalid_or_oversized_tool_result_does_not_advance_snapshot(extra):
    events = [
        RunEvent(1, RunEventType.RUN_RESUMED, "run", {}),
        RunEvent(2, RunEventType.TOOL_COMPLETED, "run", {"outcome": "succeeded", **extra}),
    ]
    reader = RunEventAccumulator(RunEventReplay(Pages(events)), TranscriptRunEventReducer(
        include_tool_results=True, max_tool_result_bytes=128,
    ))
    first = await reader.page("run", limit=1)
    saved = first.snapshot.to_dict()
    with pytest.raises(RunStoreError):
        await reader.page("run", snapshot=first.snapshot)
    assert first.snapshot.to_dict() == saved


async def test_legacy_omitted_and_failed_results_are_not_invented():
    events = [RunEvent(i, RunEventType.TOOL_COMPLETED, "run", extra) for i, extra in enumerate([
        {"outcome": "needs-approval"},
        {"outcome": "succeeded"},
        {"outcome": "succeeded", "result_recording": "omitted"},
        {"outcome": "succeeded", "result_recording": "failed"},
        {"outcome": "succeeded", "result_recording": "recorded", "result": {"kind": "application.ref", "ref": "local:1"}},
    ], 1)]
    reader = RunEventAccumulator(RunEventReplay(Pages(events)), TranscriptRunEventReducer(include_tool_results=True))
    first = await reader.page("run", limit=3)
    restored = RunReplaySnapshot.from_dict(json.loads(json.dumps(first.snapshot.to_dict())))
    last = await reader.page("run", snapshot=restored)
    whole = await reader.page("run")
    assert last.snapshot == whole.snapshot
    history = last.snapshot.state["tool_events"]
    assert all("result" not in tool for tool in history[:4])
    assert history[4]["result"]["ref"] == "local:1"


def test_disabled_result_projection_keeps_a6_reducer_identity():
    import hashlib
    settings = [False, False, "metadata", 1024, 4096, 1_000_000, 8 * 1024 * 1024, 16_384]
    expected = "w-agent.transcript/1/" + hashlib.sha256(json.dumps(settings).encode("utf-8")).hexdigest()
    assert TranscriptRunEventReducer().identity == expected
    assert TranscriptRunEventReducer(include_tool_results=True).identity != expected
    with pytest.raises(ValueError):
        TranscriptRunEventReducer(include_tool_results="true")
    with pytest.raises(ValueError):
        TranscriptRunEventReducer(max_tool_result_bytes=True)


@pytest.mark.parametrize("kind", ["wrong-run", "oversize", "not-page"])
async def test_replaceable_page_reader_must_preserve_cursor_and_limit(kind):
    from w_agent import RunEventPage
    class Reader:
        async def page(self, run_id, *, cursor, limit):
            if kind == "not-page":
                return None
            selected_run = "other" if kind == "wrong-run" else run_id
            count = 2 if kind == "oversize" else 1
            events = tuple(RunEvent(i, RunEventType.RUN_RESUMED, selected_run) for i in range(1, count + 1))
            return RunEventPage(RunEventCursor(selected_run), events, RunEventCursor(selected_run, count), False)
    with pytest.raises(RunStoreError):
        await RunEventAccumulator(Reader(), TranscriptRunEventReducer()).page("run", limit=1)
