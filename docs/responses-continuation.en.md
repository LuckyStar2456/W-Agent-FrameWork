# Native Responses continuation and media output

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

Status: implemented and tested locally, not separately released. No live credential or paid endpoint was used. This is a Python provider API; CLI/TUI configuration and Agent session recovery are not wired to it.

Storage is the public, replaceable `ResponsesCheckpointStore` protocol (`create/append/cursor/load`). The provider chooses no default store and creates no database. Explicitly constructing `SqliteResponsesCheckpointStore(path)` initializes the named database and opts into local retention of response content. A custom store can use encryption, memory or a host database while preserving binding checks, immutable frame history and exact event offsets.

The SQLite adapter checks a dedicated application ID, schema version and table structure, rejecting nonempty foreign databases. Defaults per generation are 100,000 frames, 32 MiB per frame and 256 MiB of cumulative frame JSON; configure `max_frames_per_stream`, `max_frame_bytes` and `max_stream_bytes` to adjust them. Exceeding a limit fails before appending the extra frame and never regenerates. Limits apply per generation; the host manages retention and cleanup of historical generations.

## Explicit background retention

`OpenAIResponsesResumableProvider` adds native cursors to the HTTP provider. Cursor methods require both `background=True` and `store=True` in `request.extensions['openai_responses.body']`, and otherwise fail before network traffic. Ordinary `stream()` keeps its existing behavior. Background generation changes server-side data retention and is not suitable for zero-data-retention requirements. Model, account, and compatible-endpoint support must be verified separately.

```python
from w_agent.models import (
    ModelMessage, ModelRequest, MessageRole,
    OpenAIResponsesResumableProvider, SqliteResponsesCheckpointStore,
)

store = SqliteResponsesCheckpointStore("responses-checkpoints.sqlite3")
provider = OpenAIResponsesResumableProvider(
    name="openai-resumable",
    base_url="https://api.openai.com/v1",
    default_model="your-supported-model",
    headers={"Authorization": f"Bearer {api_key}"},
    checkpoint_store=store,
)
request = ModelRequest(
    messages=(ModelMessage.text(MessageRole.USER, "Explain this design"),),
    extensions={"openai_responses.body": {"background": True, "store": True}},
)
async for item in provider.stream_with_cursor(request):
    await handle_event(item.event)
    await save_host_cursor(item.cursor)

# Reconstruct the same provider/request in a later process using the same DB.
async for item in provider.resume_stream(request, saved_cursor):
    await handle_event(item.event)
    await save_host_cursor(item.cursor)
```

The host supplies `handle_event` and `save_host_cursor`. Recovery rebuilds decoding state and delivers the pending local suffix of the current vendor frame, then sends only `GET /responses/{response_id}?stream=true&starting_after=N`. Every normalized event within one wire frame has a separate cursor. Tool arguments and completed media use the same mechanism. Pending events from a terminal frame require no network call; a fully consumed finish cursor yields an empty stream.

The binding is a SHA-256 digest of provider name, URL, actual request body, headers, decoder version and image limit. Changed prompts, models, parameters, endpoints, credentials or image limits fail before network access. Key rotation therefore invalidates old bindings. Raw authentication headers are not saved. The unencrypted database holds response frames, potentially including output, tool arguments, echoed instructions and images; protect it as application data. Each frame is stored once, and rebuilding takes time proportional to frame history. `store.delete(cursor)` removes all local frames and sibling cursors for that generation; it does not delete or cancel the remote response.

The host must coordinate event handling and its own saved cursor atomically. This API does not guarantee exactly-once tool side effects, persist Agent/tool state or a stream validator, or recover whole sessions automatically. Recovery requires a cursor from a visible event. Expiry, 404, authentication failures, decreasing sequence numbers and changed response IDs never fall back to new generation.

`ModelExecutor.stream(request, stream_recovery=NativeCursorRecovery(...))` supports automatic continuation within a process, but does not expose its cursor. Before the first visible event, explicitly configured `InvocationPolicy` retries still apply; the default is one attempt. Failed-attempt usage remains unknown unless reported, and the shared-budget wrapper still rejects native recovery. Closing a local iterator does not cancel the remote background task.

## Responses image results

Both ordinary and resumable providers use `OpenAIResponsesMapping`. Request extension `openai_responses.image_generation={"output_format": "png"}` explicitly adds the image generation tool alongside any function tools. Options are `model`, `size`, `quality`, `background`, `output_format`, `output_compression`, `partial_images` and `action`; the vendor validates model-specific values.

Completed `image_generation_call.result` becomes `ImageContent` with PNG/JPEG/WebP media type. Repeated completion in `response.output_item.done` and the terminal response emits the image only once; conflicting results fail. The default per-image limit is 20 MiB, configurable with `OpenAIResponsesMapping(max_image_bytes=...)`, checked before and after Base64 decoding. No URLs are fetched or files written. Partial previews are not promoted to final content; other hosted tools, audio and reasoning deltas remain unsupported. Model profiles and live image-generation support require application verification.

Official references: [background mode](https://developers.openai.com/api/docs/guides/background), [retrieve parameters](https://developers.openai.com/api/reference/python/resources/responses/methods/retrieve), [image generation tool](https://developers.openai.com/api/docs/guides/tools-image-generation).
