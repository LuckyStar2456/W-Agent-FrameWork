import asyncio
import subprocess
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from w_agent.models import (
    BlockEnd, BlockStart, CancellationToken, FinishEvent, HttpStreamFrame,
    InvocationPolicy, MessageRole, ModelCapability, ModelError, ModelExecutor, ModelMessage,
    ModelRegistry, ModelRequest, ModelRouter, ModelStreamProtocolError,
    NativeCursorRecovery, OpenAIResponsesResumableProvider,
    ResponsesCheckpoint, SqliteResponsesCheckpointStore, TextDelta, ToolCallContent,
    ToolCallDelta, WeightedRoutingPolicy,
)


def frame(sequence, event_type, **data):
    return HttpStreamFrame({"type": event_type, "sequence_number": sequence, **data})


CREATED = frame(0, "response.created", response={"id": "resp_original"})
DELTA = frame(1, "response.output_text.delta", output_index=0, content_index=0, delta="hello")
END = frame(2, "response.completed", response={
    "id": "resp_original", "status": "completed", "output": [{
        "type": "message", "content": [{"type": "output_text", "text": "hello world"}],
    }], "usage": {"input_tokens": 4, "output_tokens": 2},
})


class Transport:
    def __init__(self, *batches):
        self.batches = list(batches)
        self.calls = []

    async def stream(self, url, *, request, timeout):
        self.calls.append((url, request))
        for item in self.batches.pop(0):
            yield item

    async def aclose(self):
        pass

    async def request_json(self, url, *, request, timeout):
        return {"data": [{"id": "model"}]}


def request(**kwargs):
    return ModelRequest(
        messages=(ModelMessage.text(MessageRole.USER, "hello"),), model="model",
        extensions={"openai_responses.body": {"background": True, "store": True}}, **kwargs,
    )


def provider(path, transport, **overrides):
    options = dict(name="responses", base_url="https://example.test/v1", default_model="model",
                   headers={"Authorization": "Bearer test-secret"}, transport=transport)
    options.update(overrides)
    return OpenAIResponsesResumableProvider(
        checkpoint_store=SqliteResponsesCheckpointStore(path), **options,
    )


@pytest.mark.asyncio
async def test_reconstructed_provider_resumes_middle_of_frame_without_replaying(tmp_path):
    path = tmp_path / "cursors.db"
    initial = provider(path, Transport([CREATED, DELTA]))
    stream = initial.stream_with_cursor(request())
    start = await anext(stream)
    assert isinstance(start.event, BlockStart)
    await stream.aclose()
    transport = Transport([END])
    resumed = provider(path, transport)
    events = [item.event async for item in resumed.resume_stream(request(), start.cursor)]
    assert events[0] == TextDelta(0, "hello")
    assert events[1] == TextDelta(0, " world")
    assert sum(isinstance(e, BlockStart) for e in events) == 0
    assert isinstance(events[-1], FinishEvent)
    assert transport.calls[0][1].method == "GET"
    assert transport.calls[0][1].body is None
    assert transport.calls[0][0].endswith("/responses/resp_original?stream=true&starting_after=1")
    assert b"test-secret" not in path.read_bytes()


@pytest.mark.asyncio
async def test_terminal_frame_suffix_and_finished_cursor_need_no_network(tmp_path):
    path = tmp_path / "cursors.db"
    initial = provider(path, Transport([CREATED, END]))
    stream = initial.stream_with_cursor(request())
    start = await anext(stream)
    await stream.aclose()
    transport = Transport()
    resumed = provider(path, transport)
    items = [item async for item in resumed.resume_stream(request(), start.cursor)]
    assert isinstance(items[-1].event, FinishEvent)
    assert not transport.calls
    assert [item async for item in resumed.resume_stream(request(), items[-1].cursor)] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["prompt", "model", "temperature", "credential", "endpoint", "provider"])
async def test_binding_rejects_different_context_before_network(tmp_path, change):
    path = tmp_path / "cursors.db"
    source = provider(path, Transport([CREATED, DELTA]))
    stream = source.stream_with_cursor(request())
    item = await anext(stream)
    await stream.aclose()
    candidate = request()
    options = {}
    if change == "prompt":
        candidate = replace(candidate, messages=(ModelMessage.text(MessageRole.USER, "different"),))
    elif change == "model":
        candidate = replace(candidate, model="other")
    elif change == "temperature":
        candidate = replace(candidate, temperature=0.4)
    elif change == "credential":
        options["headers"] = {"Authorization": "Bearer another-secret"}
    elif change == "endpoint":
        options["base_url"] = "https://other.test/v1"
    else:
        options["name"] = "other"
    transport = Transport()
    target = provider(path, transport, **options)
    with pytest.raises(ModelStreamProtocolError, match="binding mismatch"):
        _ = [item async for item in target.resume_stream(candidate, item.cursor)]
    assert not transport.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"background": True}, {"background": True, "store": False}])
async def test_requires_explicit_data_retention_opt_in(tmp_path, body):
    transport = Transport()
    target = provider(tmp_path / "c.db", transport)
    candidate = replace(request(), extensions={"openai_responses.body": body})
    with pytest.raises(ValueError, match="explicit"):
        _ = [item async for item in target.stream_with_cursor(candidate)]
    assert not transport.calls


@pytest.mark.asyncio
async def test_executor_uses_native_get_after_interrupted_eof(tmp_path):
    transport = Transport([CREATED, DELTA], [END])
    target = provider(tmp_path / "c.db", transport)
    registry = ModelRegistry()
    registry.register("responses", target)
    executor = ModelExecutor(registry, ModelRouter(registry, WeightedRoutingPolicy()),
                             InvocationPolicy(initial_backoff=0))
    execution = executor.stream(request(), stream_recovery=NativeCursorRecovery())
    events = [event async for event in execution]
    assert "".join(event.text for event in events if isinstance(event, TextDelta)) == "hello world"
    assert len(execution.attempts) == 2
    assert [call[1].method for call in transport.calls] == ["POST", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    frame(1, "response.output_text.delta", output_index=0, content_index=0, delta="duplicate"),
    frame(2, "response.completed", response={"id": "resp_other", "status": "completed"}),
    frame(True, "response.in_progress", response={"id": "resp_original"}),
])
async def test_resume_rejects_repeated_sequence_and_wrong_generation(tmp_path, bad):
    path = tmp_path / "c.db"
    target = provider(path, Transport([CREATED, DELTA]))
    stream = target.stream_with_cursor(request())
    await anext(stream)
    item = await anext(stream)
    await stream.aclose()
    resumed = provider(path, Transport([bad]))
    with pytest.raises(ModelStreamProtocolError):
        _ = [item async for item in resumed.resume_stream(request(), item.cursor)]


@pytest.mark.asyncio
async def test_cancelled_resume_does_not_deliver_pending_suffix(tmp_path):
    target = provider(tmp_path / "c.db", Transport([CREATED, DELTA]))
    stream = target.stream_with_cursor(request())
    item = await anext(stream)
    await stream.aclose()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        _ = [event async for event in target.resume_stream(request(), item.cursor, cancellation=token)]


@pytest.mark.asyncio
async def test_delete_invalidates_all_generation_cursors(tmp_path):
    target = provider(tmp_path / "c.db", Transport([CREATED, END]))
    items = [item async for item in target.stream_with_cursor(request())]
    assert target.checkpoint_store.delete(items[0].cursor)
    assert not target.checkpoint_store.delete(items[-1].cursor)
    with pytest.raises(ModelStreamProtocolError, match="unknown cursor"):
        _ = [item async for item in target.resume_stream(request(), items[-1].cursor)]


@pytest.mark.asyncio
async def test_separate_python_process_reconstructs_cursor(tmp_path):
    path = tmp_path / "c.db"
    target = provider(path, Transport([CREATED, DELTA]))
    stream = target.stream_with_cursor(request())
    item = await anext(stream)
    await stream.aclose()
    script = """
import asyncio, runpy, sys
ns = runpy.run_path('tests/test_responses_resume.py')
async def main():
    transport = ns['Transport']([ns['END']])
    target = ns['provider'](sys.argv[1], transport)
    events = [item.event async for item in target.resume_stream(ns['request'](), sys.argv[2])]
    assert ''.join(event.text for event in events if isinstance(event, ns['TextDelta'])) == 'hello world'
    assert transport.calls[0][1].method == 'GET'
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), item.cursor],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_tool_arguments_resume_from_frame_middle(tmp_path):
    path = tmp_path / "c.db"
    added = frame(1, "response.output_item.added", output_index=0,
                  item={"type": "function_call", "call_id": "call_one", "name": "search", "arguments": ""})
    delta = frame(2, "response.function_call_arguments.delta", output_index=0, delta='{"q":')
    tail = frame(3, "response.function_call_arguments.delta", output_index=0, delta='"hello"}')
    end = frame(4, "response.completed", response={"id": "resp_original", "status": "completed", "output": [
        {"type": "function_call", "call_id": "call_one", "name": "search", "arguments": '{"q":"hello"}'},
    ]})
    target = provider(path, Transport([CREATED, added, delta]), default_capabilities=frozenset(ModelCapability))
    stream = target.stream_with_cursor(request())
    prefix = [await anext(stream), await anext(stream), await anext(stream)]
    await stream.aclose()
    target = provider(path, Transport([tail, end]), default_capabilities=frozenset(ModelCapability))
    suffix = [item async for item in target.resume_stream(request(), prefix[-1].cursor)]
    events = [item.event for item in prefix + suffix]
    assert ''.join(event.arguments_delta for event in events if isinstance(event, ToolCallDelta)) == '{"q":"hello"}'
    assert [event.block for event in events if isinstance(event, BlockEnd)] == [ToolCallContent("call_one", "search", '{"q":"hello"}')]


@pytest.mark.asyncio
async def test_completed_image_pending_block_survives_restart(tmp_path):
    path = tmp_path / "c.db"
    image = frame(1, "response.output_item.done", output_index=0, item={
        "type": "image_generation_call", "id": "ig_1", "status": "completed", "result": "aGVsbG8=",
    })
    target = provider(path, Transport([CREATED, image]))
    stream = target.stream_with_cursor(request())
    item = await anext(stream)
    assert item.event.block_type == "image"
    await stream.aclose()
    end = frame(2, "response.completed", response={"id": "resp_original", "status": "completed", "output": [dict(image.data["item"])]})
    resumed = provider(path, Transport([end]))
    events = [item.event async for item in resumed.resume_stream(request(), item.cursor)]
    assert sum(isinstance(event, BlockEnd) for event in events) == 1
    assert events[0].block.data == b"hello"


@pytest.mark.asyncio
async def test_provider_accepts_host_owned_checkpoint_store_without_files():
    class MemoryStore:
        def __init__(self):
            self.frames = {}
            self.cursors = {}

        def create(self, binding, response_id):
            self.binding, self.response_id = binding, response_id
            return "generation-one"

        def append(self, stream_id, sequence, frame):
            previous = self.frames.setdefault(sequence, frame)
            assert previous == frame

        def cursor(self, stream_id, sequence, event_offset):
            cursor = f"{stream_id}:{sequence}:{event_offset}"
            self.cursors[cursor] = (sequence, event_offset)
            return cursor

        def load(self, cursor, binding):
            assert binding == self.binding
            sequence, offset = self.cursors[cursor]
            frames = tuple(frame for seq, frame in sorted(self.frames.items()) if seq <= sequence)
            return ResponsesCheckpoint("generation-one", self.response_id, sequence, offset, frames)

    store = MemoryStore()
    target = OpenAIResponsesResumableProvider(
        name="responses", base_url="https://example.test/v1", default_model="model",
        checkpoint_store=store, transport=Transport([CREATED, DELTA], [END]),
    )
    stream = target.stream_with_cursor(request())
    item = await anext(stream)
    await stream.aclose()
    events = [item.event async for item in target.resume_stream(request(), item.cursor)]
    assert ''.join(event.text for event in events if isinstance(event, TextDelta)) == "hello world"


def test_checkpoint_database_rejects_foreign_and_damaged_schemas(tmp_path):
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="checkpoint database"):
        SqliteResponsesCheckpointStore(path)
    assert path.read_bytes() == before

    path = tmp_path / "owned.db"
    SqliteResponsesCheckpointStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE responses_frames ADD COLUMN surprise TEXT")
    with pytest.raises(ValueError, match="incompatible columns"):
        SqliteResponsesCheckpointStore(path)


@pytest.mark.parametrize("limits", [
    {"max_frames_per_stream": 1},
    {"max_frame_bytes": 1},
    {"max_stream_bytes": 1},
])
def test_checkpoint_storage_limits_fail_before_extra_write(tmp_path, limits):
    path = tmp_path / "limits.db"
    store = SqliteResponsesCheckpointStore(path, **limits)
    generation = store.create("binding", "resp_one")
    if "max_frames_per_stream" in limits:
        store.append(generation, 0, CREATED)
        # Identical replay does not consume another frame allowance.
        store.append(generation, 0, CREATED)
    with pytest.raises(ModelStreamProtocolError, match="limit"):
        store.append(generation, 1, DELTA)
    with sqlite3.connect(path) as connection:
        count = connection.execute("SELECT count(*) FROM responses_frames").fetchone()[0]
        assert count == (1 if "max_frames_per_stream" in limits else 0)


def test_missing_checkpoint_frame_is_not_a_valid_empty_prefix(tmp_path):
    path = tmp_path / "damaged.db"
    store = SqliteResponsesCheckpointStore(path)
    generation = store.create("binding", "resp_one")
    store.append(generation, 1, DELTA)
    cursor = store.cursor(generation, 1, 1)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM responses_frames")
    with pytest.raises(ModelStreamProtocolError, match="prefix is missing"):
        store.load(cursor, "binding")
