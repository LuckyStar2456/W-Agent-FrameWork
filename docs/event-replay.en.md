# Event replay and display-state reconstruction

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./event-replay.md)

a8 additions on this page are Experimental and covered by focused regressions; see [a8 release notes](./releases/2.0.0a8.en.md) for the complete validation scope.

a8 TUI Replay adds explicit trusted-cache import/continuation and new-file export, reusing this page's CLI JSON envelope, source binding and snapshot validation. Import requires `VIEW CONTENT` + `TRUST CACHE`; export requires `VIEW CONTENT` + `SAVE CACHE`. No overwrites or automatic saving. This addition is 2.0.0a8 Experimental; focused regressions passed; see [TUI cache actions](./tui.en.md) for path, cancellation, partial-file and cache-trust boundaries.

Status: `Experimental`. a6 introduced single-Run read-only accumulated snapshots; a7 adds optional tool-result bodies, Session projection and CLI/TUI accumulated views, with focused regressions passing. See [a7 release notes](./releases/2.0.0a7.en.md) for validation boundaries.

## Accumulated-view CLI (2.0.0a7; focused regressions passed)

### a8: input-message field disclosure (2.0.0a8 Experimental; focused regressions passed)

`wagent session view` adds `--include-input-name` and `--include-input-metadata`, exposing only previously recorded input-message fields, not top-level Session metadata or missing assistant fields. Both default off; either requires `--confirm-sensitive-content`. Text, input-media and output-media disclosure remain independent.

```text
wagent session view existing-session --include-input-name --confirm-sensitive-content
wagent session view existing-session --include-input-metadata --confirm-sensitive-content
wagent session view existing-session --input-media metadata
```

Shared `build_session_message_projector()` assembly retains the old text projector/identity when neither fields nor input media are selected. Selecting input media or fields uses a wrapper-aware projector that recognizes new field envelopes but returns only explicitly selected `input_fields`. Consequently `--input-media metadata` can read wrapped block metadata without exposing name/metadata. Corrupt or oversized wrappers fail instead of silently losing fields.

The wrapper projector has a different identity from a7's direct input-block projection: regenerate old input-media caches. Changed field/media choices also reject old-cache continuation. Full caches still require sensitive-content confirmation and `--trust-snapshot`; source binding is not authenticity proof. Text-only Session projection retains its identity. Run-only views do not support field switches. Output remains escaped JSON without interpreting ANSI/Rich controls, invoking models/tools or changing stores. Focused regressions passed.

```text
wagent run-view selected-run --state-root .wagent --limit 100
wagent run-view selected-run --state-root .wagent --include-text --include-tool-results --confirm-sensitive-content
wagent session view selected-session --root .wagent/sessions --state-root .wagent --run-limit 10 --event-limit 100
```

Both new commands always emit JSON, without `--json`. They do not invoke models, tools or Workflows, fetch media, or write caches. Existing `run-events` and safe TUI paging remain unchanged. Content is hidden by default: `--include-text` exposes model text, `--include-tools` exposes tool identities/arguments, and `--include-tool-results` independently exposes recorded results. `--media metadata|references|content` defaults to metadata. Session `--include-session-text` is independent of model text. Any content selection requires `--confirm-sensitive-content`, checked before cache access or Store directory preflight.

Responses contain `cache` (version, kind, canonical absolute source directories and full snapshot) and `page` (this read's information). To continue, save the entire successful response yourself as **UTF-8 JSON**, such as `page-1.json`, then run:

```text
wagent run-view selected-run --state-root .wagent --snapshot page-1.json --trust-snapshot --confirm-sensitive-content
wagent session view selected-session --root .wagent/sessions --state-root .wagent --snapshot session-page-1.json --run-offset 10 --trust-snapshot --confirm-sensitive-content
```

Repeat the same disclosure options on every continuation; changed configuration requires rebuilding. Only page sizes and Session membership offsets may change. Save each response to a different file, never redirect output onto the input cache: the shell truncates it first. Windows PowerShell requires explicit UTF-8 output, not its default UTF-16; a UTF-8 BOM is accepted. Loading any cache requires both confirmations because existing cached state is not automatically redacted again. Do not load another person's or a modified cache. Source, Run/Session ID and projection mismatches are rejected; directory binding is not a signature, historical-log verification or filesystem sandbox.

Run pages accept 1–500 events; Session pages accept 1–32 registered Runs with 1–500 events each. `next_run_offset` traverses membership only. To discover appended events in older Runs, keep the latest snapshot and sweep again from offset zero. `pending_run_ids` denotes unvisited Runs or those with more events at their last read; emptiness does not establish execution completion. Missing Session IDs are rejected by default; `--allow-unscoped-events` permits legacy events without an ID, never events naming another Session.

Only existing directories are accepted; Run commands require an existing log. API limits remain 8 MiB per Run / 32 MiB per Session snapshot; CLI input files and complete escaped output additionally have a 64 MiB cap. JSON escapes controls and non-ASCII text, without rendering bodies through Rich; parsing restores original text and media. Errors omit raw logs/exception bodies and emit no partial new snapshot. Cache files are read-only, never overwritten automatically. Session stores still load full records and event stores scan prefixes: limits are not whole-log I/O or memory sandboxes. [TUI Replay](./tui.en.md) now provides read-only in-memory views (available in 2.0.0a7 with focused regressions passing); input recording is separately available in a7 [Session schema 2](./sessions.en.md), with explicit input-block projection and CLI/TUI disclosure described there. Focused a7 regressions passed.

## Three distinct capabilities

- `RunEventReplay.page()` reads recorded raw events, potentially containing sensitive content, with contiguous run-bound cursors.
- `projected_page()` projects individual events, hiding content by default and allowing application-owned projectors.
- New `RunEventAccumulator` uses replaceable `RunEventReducer` to fold pages into `RunReplaySnapshot`, restoring a client's display state, not Agent execution.

None of these APIs invokes models, executes tools, downloads media, or approves checkpoints. Provider stream recovery, Agent approval recovery, and model recording/replay are separate modules; their cursors and authority are not interchangeable.

## Content-hidden defaults

```python
from w_agent import (
    JsonlRunStore, RunEventReplay, RunEventAccumulator,
    RunReplaySnapshot, TranscriptRunEventReducer,
)

replay = RunEventReplay(JsonlRunStore(".wagent"))
reader = RunEventAccumulator(replay, TranscriptRunEventReducer())
page = await reader.page("selected-run", limit=100)
payload = page.snapshot.to_dict()  # Host chooses whether/how to persist it.

# After loading the host's saved JSON, continue with the same run and reducer configuration.
restored = RunReplaySnapshot.from_dict(payload)
next_page = await reader.page("selected-run", snapshot=restored, limit=100)
```

`has_more` only indicates additional records at read time, not Run completion. Applications may later read new events after the same snapshot; this API does not poll or subscribe. Persist state and cursor together. A failed page returns no partial snapshot and leaves the input unchanged; successful pages return `events_applied` and a new snapshot. Never advance the cursor while discarding its corresponding state.

Snapshot schema 1 strictly stores `cursor`, `reducer`, and JSON state, deeply read-only in memory. `to_dict()` returns a detached serializable copy. Another Run or reducer identity is rejected. Built-in identity includes version, disclosure switches and limits; configuration changes require rebuilding from the beginning, not editing the identity to bypass checks.

## Bundled transcript template

`TranscriptRunEventReducer` defaults to `include_text=False`, `include_tools=False`, and `media_mode="metadata"`:

- `blocks` accumulates text/tool-argument deltas and image/audio blocks by `(step, block_index)`. Defaults retain type, position, character counts and media metadata only.
- `models` records model completion information; only explicit `include_text=True` retains final text. Final text stays separate from delta blocks and is never appended twice.
- `tool_events` retains request/outcome history, including repeated `needs-approval` and later results. Only `include_tools=True` retains Call IDs, tool names, argument fragments and recorded complete request arguments. These are neither executed nor parsed automatically.
- Media `references` mode permits recorded URLs; `content` also permits inline Base64. Standard inline data is checked against length and SHA-256. Only recorded values are returned; no URLs or files are read.
- `usage` and `cost` replace the latest cumulative snapshots instead of adding them repeatedly. `RUN_RESUMED` clears the previous `stop_reason`; `RUN_COMPLETED` records that stop, so `needs-approval` does not imply permanent termination.

Hosts must authorize raw-log access before disclosing text, tools or media content. Rich snapshots may contain credentials, private arguments, images or audio and require the same protection as raw logs. Default CLI/TUI still uses existing safe event projections; it does not automatically display rich accumulated snapshots.

## Extension and limits

Custom reducers provide `identity`, `initial_state()`, and `reduce(state, event)`. Identity must change with state schema/options. Input state is a detached JSON copy; output must be a finite JSON object. Replace the reducer for new media encodings or application-specific state without changing the paging protocol. Reducers are trusted Python, not a plugin sandbox, and should remain side-effect-free.

Defaults allow 1,024 blocks/model completion records, 4,096 tool events, 1,000,000 characters per block, 8 MiB per inline media item and 16,384 reference characters. The accumulator additionally limits the complete serialized snapshot to 8 MiB, including Base64 expansion and other fields; larger snapshots require explicit limits. Oversize state, conflicting block types, changing tool-delta identities or invalid media reject the page without silent truncation.

Snapshots are trusted display caches, not cryptographic proofs or execution ownership. They do not identify the backing store or detect external edits to earlier records. Hosts must pin the store source and protect caches. Replayed old pages, missing records, or middle-of-log cursors without corresponding state cannot be repaired automatically.

Text/tool deltas and media exist only if their recording options were enabled; final model text and tool requests can be rebuilt from existing RunEvents. a6 `TOOL_COMPLETED` events omit result bodies; a7 provides optional recording below and [cross-Run read-only Session views](./sessions.en.md) (2.0.0a7, focused regressions passed). Outcome status cannot recover unrecorded bodies. CLI wiring is described below; TUI now connects read-only in-memory accumulation (available in 2.0.0a7 with focused regressions passing); input recording is available in a7 (see [Sessions](./sessions.en.md)), with independently selectable input-block display. Arbitrary execution-stack recovery is outside this feature.

a8 `RunEventAccumulator` accepts `RunEventPageSource.page()`, preserving compatibility with `RunEventReplay`. Custom readers return contiguous `RunEventPage` values. The accumulator additionally validates returned cursors and request limits, rejecting wrong-Run/position and oversized pages before applying them to a snapshot.

## Tool-result bodies (2.0.0a7; focused regressions passed)

Recording and display require separate opt-ins. `include_tools=True` does not expose result bodies:

```python
from w_agent import AgentDefinition, RunEventAccumulator, RunEventReplay, TranscriptRunEventReducer

definition = AgentDefinition(
    "assistant", emit_tool_results=True, max_tool_result_event_bytes=65536,
)
# Pass definition to your assembled loop; store is that loop's actual RunStore.
reader = RunEventAccumulator(
    RunEventReplay(store),
    TranscriptRunEventReducer(include_tool_results=True, max_tool_result_bytes=65536),
)
page = await reader.page("selected-run")
```

Only after producing an actual model-visible `ToolResultContent` does ReAct add `result_recording` to the same `TOOL_COMPLETED`: `recorded` includes a `result` object, `omitted` means the application encoder deliberately returned `None`, and `failed` covers encoding exceptions, invalid JSON or limits. Recording off adds neither field; approval boundaries, including continuation tickets, carry neither bodies nor markers.

Default `TextToolResultEventEncoder` emits `{"kind":"text","text":"…","is_error":false}` without truncation, redaction or file/URL access. Failed tools record the standard error content already sent to the model, not raw executor exceptions or `data`. Limits apply separately to UTF-8 text bytes and the complete `result` JSON UTF-8 bytes (including keys, escaping and separators), both defaulting to 64 KiB. Text just below 64 KiB can therefore still exceed the outer cap. Custom objects must also be finite JSON of depth at most 32 and fit the outer limit.

Inject `ToolResultEventEncoder.encode(result, *, name)` through `ReactAgentLoop(..., tool_result_event_encoder=encoder)` or `assemble_local_runtime(..., tool_result_event_encoder=encoder)`. It receives the immutable model-visible result and tool name and may redact, return application-defined JSON or omit with `None`. It grants no tool authority and cannot alter model-visible content. Encoders are trusted synchronous Python; hosts enforce purity. This is not a sandbox. Configuration files select only recording and limits, never import encoders implicitly. Checkpoints do not persist Python encoders; hosts must re-inject required redaction after restart, otherwise the default plaintext encoder is used.

Encoding failures emit only a fixed status without exception text or partial bodies and continue the existing loop, never turning completed effects into retries. Process-level interruption and event-persistence failures are not swallowed. Existing recovery retains uncertain state on storage failure without replay or new cross-store atomic guarantees. Disabling event-body recording does not imply other messages, checkpoints or raw logs contain no sensitive data.

The accumulator reads `result` only with `include_tool_results=True`, checking body/status agreement and limits. Custom JSON stays display data, never commands or fetched references. Invalid pages fail without advancing snapshots. Missing bodies in older logs are not invented. Safe projection exposes only the fixed `result_recording` status. Result disclosure is independent of `include_tools` (identities/arguments).

When result disclosure is off, the a6 reducer identity is preserved for existing snapshots. Enabling it selects a new `/2/` identity bound to the result limit and requires rebuilding from the beginning instead of reusing another configuration's snapshot. Snapshot envelope schema remains 1. Only previously recorded bodies can be replayed; missing history is not backfilled.
