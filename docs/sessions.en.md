# Session lifecycle and cross-run context

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./sessions.md)

The framework provides a [Qdrant history selector](./vector-retrieval.en.md): the existing async retrieval protocol selects only local candidates using namespace/Run/text-bound IDs, without adopting remote bodies or uploading history. Hosts prebuild the index and supply embedding. Included in 2.0.0, with local regressions passing and not part of a9.

a9 adds `SQLiteSessionSummaryObserver` as a replacement for the summary adapter's memory observer, explicitly persisting/reopening summary Run reports. It does not persist main-Run aggregation or alter Session statistics automatically. 2.0.0a9 Experimental; see a9 release notes for validation; see [durable accounting](./context-accounting.en.md).

a8/a9 additions on this page are Experimental; see [a9 release notes](./releases/2.0.0a9.en.md) for validation scope.

Status: local Session lifecycle, JSON persistence, text history and approval recovery are `Implemented` (a1); cross-Session usage/cost summaries are `Experimental` (a4). a7 adds cross-Run rich read-only views, CLI/TUI Replay, optional schema 2 input recording, standard decoding and replaceable history policies, all `Experimental`. Focused regressions passed; see [a7 release notes](./releases/2.0.0a7.en.md) for validation scope.

## Public APIs

- `SessionManager`: coordinates lifecycle, text history, and ordinary `AgentLoop` values.
- `SessionRecord`: immutable session snapshot with messages, run summaries, and metadata.
- `SessionRunRecord`: stores stop reason, output, step/tool counts, and token usage.
- `AgentUsageSummary`: prompt/output-free cross-session usage, cost, and completeness for one agent.
- `InMemorySessionStore`: tests and short-lived local development.
- `JsonSessionStore`: atomic JSON storage for one local lifecycle owner.
- `RunEventCallback`: optional synchronous/asynchronous application projection invoked in public stream order; the built-in ReAct loop appends each event to its run store before exposing it.

```python
from w_agent import (
    AgentDefinition,
    JsonSessionStore,
    MessageRole,
    ModelMessage,
    SessionManager,
)

sessions = SessionManager(JsonSessionStore(".wagent/sessions"))
session = await sessions.create("Support case")

result = await sessions.run_agent(
    react_loop,
    AgentDefinition("support"),
    session.session_id,
    (ModelMessage.text(MessageRole.USER, "Where is my order?"),),
)
```

## CLI and TUI

```text
wagent session create "Support case" --id case-1 --json
wagent session list --include-archived --json
wagent session show case-1 --json
wagent session usage --agent support --include-archived --json
wagent session archive case-1
wagent session unarchive case-1
```

The CLI and TUI use the same public `SessionManager`/`JsonSessionStore`, defaulting to `.wagent/sessions`. `show` returns messages, run summaries, model-attempt/usage/pricing counts, input/output/cached tokens, versioned cost, and completeness without starting a model or incurring cost. `SessionManager.agent_usage()` and `wagent session usage` aggregate multiple sessions by exact agent name; archived sessions are excluded by default and can be included explicitly. The summary never reads or emits prompts, messages, model output, or tool results. Unreported usage remains incomplete, while missing cost or mixed price-table/currency identities leave cost unavailable instead of treating it as zero or silently combining it. The TUI Sessions screen shows the same safe summary and continues to support create, refresh, archive, and unarchive; its Run screen supports separately confirmed tool-code loading, authority input, and privacy-safe live events. Both CLI and TUI can resume approval with known session/run/call IDs.

The next `run_agent()` prepends previously projected text messages by default. Set `include_history=False` to disable automatic context assembly; the current input and result are still recorded.

## Approval resume

When a run stops with `NEEDS_APPROVAL`, call `resume_agent()` with the same loop/run store and approval granted by the local application. The manager verifies that the run belongs to the session, updates its existing summary instead of creating a duplicate, and does not store user input twice.

Configured applications can call `LocalAgentRuntime.resume()`; the CLI equivalent is `wagent run-resume`. Both require authority and a non-empty exact call-ID set to be supplied again at runtime. Neither session nor checkpoint restores authority.

`run_agent()`, `resume_agent()`, `LocalAgentRuntime.run()`, and `resume()` accept an optional `event_callback`. A synchronous or asynchronous callback receives `RunEvent` values in execution order; the built-in `ReactAgentLoop` persists each event before the callback can observe it. Third-party loops need `resume_stream()` only when a resume event callback is requested; existing callback-free `resume()` implementations remain compatible. Callback exceptions stop the host call instead of being silently swallowed. The TUI projects only allowlisted fields and omits model text, tool arguments, and tool results.

## Retrieval and summary context templates (a8; 2.0.0a8 Experimental with focused regressions passing)

This section describes post-a7 source additions, not PyPI a7. `TextSessionHistoryPolicy` remains the default. Applications can pass a policy per call to `SessionManager.conversation()` / `run_agent()` or `LocalAgentRuntime.run()` / `run_messages()`.

```python
from w_agent import (
    RetrievedSessionHistoryPolicy, SummarizedSessionHistoryPolicy,
    ExtractiveSessionHistorySummarizer, SessionHistoryLimits,
)

limits = SessionHistoryLimits(max_messages=512, max_output_bytes=32 * 1024)
retrieved = RetrievedSessionHistoryPolicy(
    query="refund invoice", max_retrieved_turns=4, recent_turns=2, limits=limits,
)
history = await manager.conversation(session_id, history_policy=retrieved)

summarized = SummarizedSessionHistoryPolicy(
    summarizer=ExtractiveSessionHistorySummarizer(max_chars=4096, chars_per_message=256),
    recent_turns=2, limits=limits,
)
# Execution needs separate application authorization; this only builds history.
history = await manager.conversation(session_id, history_policy=summarized)
```

- `SessionHistoryTurn` is a contiguous same-Run-ID message segment, not necessarily a complete conversation turn. Reappearance after another Run forms a separate segment. Selection retains complete segments, original roles and message order.
- `RetrievedSessionHistoryPolicy` retrieves from older segments, then adds a preserved recent tail in chronological order. The host explicitly supplies this invocation's `query`; it is never guessed from old records. `recent_turns=0` preserves no tail; no matches returns only the tail.
- `KeywordSessionHistoryRetriever` matches casefolded whitespace-separated query terms as substrings, ranks by matched-term count and prefers recent segments on ties. Chinese terms can be separated with spaces. This is not semantic search or a vector database. Custom `SessionHistoryRetriever.select(query, turns, *, limit)` returns a tuple of unique in-range integer indices, not new messages or changed roles; original chronology is restored.
- `SummarizedSessionHistoryPolicy` passes older segments to `SessionHistorySummarizer.summarize(turns)` and retains the tail unchanged. The built-in extractive summarizer keeps message prefixes and role labels within character limits, without inferred facts. The summary is a USER data message labelled as potentially incomplete, never a SYSTEM instruction. Labelling cannot prevent prompt injection, and summaries may omit important facts.
- Templates use existing Session text only, without decoding media, sending or downloading URLs. Media-only records are ignored; text accompanying media can participate. SYSTEM/TOOL roles are rejected rather than silently dropped; replace the whole policy for those needs. Custom callbacks receive text segments, not raw Session metadata or media records.
- Defaults bound raw messages to 1,024, input text to 1 MiB, output text to 64 KiB and queries to 4 KiB, measured in UTF-8 bytes. The summarizer separately limits characters. Oversized input fails before callbacks; oversized output never returns partial history. These are not token budgets, total I/O/memory sandboxes or limits on callback-internal work.
- The synchronous policies above do not write stores or implicitly invoke models, tools or networks. Callbacks are explicitly injected synchronous trusted Python and should be side-effect free; see the async adapters below. Model-generated summaries need separate authorization and metering, whether precomputed by the host or supplied through an async callback. Callbacks are not retried automatically. Errors omit raw content; `include_history=False` skips the policy and approval recovery still uses its checkpoint.

a8 also connects built-in templates to CLI/TUI through `BuiltinSessionHistoryOptions` (likewise 2.0.0a8 Experimental with focused regressions passing): `retrieved` requires an explicit query, `summarized` uses local extraction, and both require independent context-transformation consent. The options object constructs built-ins without custom-code loading or permission grants; whole-policy Python injection remains available. See [run entry points](./local-runtime.en.md) and [TUI](./tui.en.md). Focused regressions passed; an injectable Qdrant adapter is available; live backend acceptance remains outstanding; see the model-summary Python adapter below.

### Async history preparation (2.0.0a8; focused regressions passed)

`AsyncSessionHistoryPolicy.project(session)` coexists with the synchronous protocol. `conversation()`, `run_agent()` and both Runtime run methods accept it, await an awaitable result and then validate the returned message tuple. Injection is explicit through Python; JSON configuration and built-in CLI/TUI selections never load async plugins or implicitly contact external services.

`AsyncRetrievedSessionHistoryPolicy` requires an injected `AsyncSessionHistoryRetriever.select(query, turns, *, limit)`; `AsyncSummarizedSessionHistoryPolicy` requires an injected `AsyncSessionHistorySummarizer.summarize(turns)`. No external client is provided by default. Both reuse text limits, recent-segment retention and role restrictions, validating input before the callback. Only older text segments are passed, not Session titles, metadata or media records. Retrieval accepts unique in-range indices and restores chronology; summaries are untrusted USER data, never SYSTEM authority. No older segments means no callback.

```python
from w_agent import AsyncRetrievedSessionHistoryPolicy, CancellationToken

class HostRetriever:
    async def select(self, query, turns, *, limit):
        # The host provides and authorizes host_search, including client lifecycle,
        # I/O timeouts and separate usage accounting.
        indices = await host_search(query, turns, limit=limit)
        return tuple(indices)

policy = AsyncRetrievedSessionHistoryPolicy(
    query="refund invoice", retriever=HostRetriever(), recent_turns=2, timeout=20,
)
token = CancellationToken()
history = await manager.conversation(session_id, history_policy=policy, cancellation=token)
# The same policy/token can be passed per call to runtime.run(...,
# history_policy=policy, cancellation=token).
```

Template `timeout` defaults to 30 seconds, must be finite and positive, and bounds one callback wait without automatic retries. Cancelling the token or caller task cancels the pending projection and drains cleanup; `CancelledError` is not converted to an ordinary failure. Timeouts/cancellation are cooperative: they cannot forcibly stop blocking synchronous code or undo network calls. Clients still need their own I/O timeouts. Callbacks are not automatically offloaded to threads and host-owned clients are not closed. Arbitrary custom async policies must supply their own timeouts.

After async projection the Manager rereads the Session and refuses Agent execution if content/status changed, without retrying the callback. This is not a cross-process transaction or lock. Additional input-recording preflight runs before history callbacks. Preparation failure/cancellation appends no Run, but a newly created empty Session may remain and external callback side effects are not rolled back.

**Accounting boundary: async preparation precedes the main Agent Run. Retrieval, embedding and summary-model costs are not automatically included in its token/cost budgets, events or Session totals.** Hosts must obtain separate sending consent and meter these operations independently. The next section provides a model-summary adapter with its own Run, not a shared main-Run budget. a8 now offers [explicit summary/main-Run usage aggregation](./context-accounting.en.md); local vector retrieval and separate shared-budget wrappers are available; unified preparation/main-Run accounting and live backends remain outstanding. Cancellation, timeout, bounds, Session-change and Runtime wiring tests passed.

### Metered model summaries (a8 addition; 2.0.0a8 Experimental; focused regressions passed)

`InMemorySessionSummaryObserver` can directly replace the custom in-memory list observer below. Its `snapshot(main_result)` explicitly combines known summary/main-Run tokens and grouped costs; see the [aggregation guide](./context-accounting.en.md). This is likewise 2.0.0a8 Experimental with focused regressions passing, without a unified hard budget or automatic changes to Session statistics.

`AgentSessionHistorySummarizer` implements the async summary callback using a host-injected `AgentLoop` and required `SessionSummaryObserver`, directly composable with `AsyncSummarizedSessionHistoryPolicy`. Each invocation creates an independent `summary-...` Run ID, inheriting no main Session ID, tool authority or history policy and never rewriting the Session. Hosts separately authorize sending older text to the selected model.

```python
from w_agent import (
    AgentDefinition, AgentSessionHistorySummarizer,
    AsyncSummarizedSessionHistoryPolicy, ReactAgentLoop,
    ToolRegistry, ToolExecutor, TokenBudget,
)

class Accounting:
    def __init__(self):
        self.reports = []  # In-memory example; production hosts own durable accounting.

    async def record(self, report):
        self.reports.append(report.to_dict())

tools = ToolRegistry()  # Dedicated empty catalog; do not expose business-tool definitions.
summary_loop = ReactAgentLoop(model_executor, tools, ToolExecutor(tools), store=summary_store)
accounting = Accounting()
summarizer = AgentSessionHistorySummarizer(
    summary_loop, accounting,
    definition=AgentDefinition(
        "history-summary", max_steps=1, max_tool_calls=0, max_output_tokens=1024,
        token_budget=TokenBudget(max_total_tokens=12000, require_usage=True),
    ),
)
policy = AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=2, timeout=30)
# After host authorization: await runtime.run(prompt, history_policy=policy)
```

The default Definition permits one step, zero tool calls and at most 1,024 output tokens per request, and requires reported Usage. Replace its model, system prompt, budgets and other settings freely; this template requires `max_tool_calls=0`, while other behavior can replace the entire summarizer. A zero tool-call budget does not hide registered tool definitions, so use a dedicated empty ToolRegistry. Custom Loops are trusted code, not a sandbox.

Older messages are serialized as role/text JSON in one USER request, excluding original Run IDs, name/metadata and media. An untrusted-data label is not a prompt-injection defense. `SessionHistoryLimits` bounds message count, synthesized USER-prompt UTF-8 bytes and summary-output bytes, excluding host-owned Definition system prompts/extensions and not replacing token estimation. Empty/oversized summaries, non-completed outcomes and tool-call/approval results are rejected.

`SessionSummaryRunReport` includes only Run ID, status, stop reason, input/output/cached tokens, call counts, cost and completeness: no prompt, summary, exception body or attempt details. It emits `started` before invocation and `completed` or `rejected` after a valid result; rejected summaries still retain reported consumption. Failure/cancellation without a valid result emits `failed` / `cancelled`, with usage and counts set to `None`, never invented zeros. Reconcile by Run ID; do not double-count started/terminal observations.

If the initial observer write fails, no model Run starts. If the terminal write fails, no summary returns and no automatic retry occurs. Cancellation propagates; its terminal notification is best-effort. Observer failure or process exit may leave only a started record, requiring reconciliation against the independent Store/Provider by Run ID. The built-in ReAct Loop retains its existing event, budget, retry and routing behavior; the adapter itself does not retry or close host clients. Raw Loop events may contain sensitive content: prompt-free observer reports do not redact the Store.

`CostBudget` requires a corresponding `PricingResolver` on the summary Loop. Budgets are independent from the main Run and restart per summary invocation. Defaults cap request output but impose no total-token or monetary hard limit unless configured. Main-Agent totals are not automatically combined; shared limits across summaries and CLI/TUI entry points remain planned. Network-free scripted Provider/ReAct integration, budget rejection, observer failure, cancellation and unknown-usage tests passed; no real model validation was performed.

## Optional input-media recording (2.0.0a7; focused regressions passed)

### a8: optional name/metadata (2.0.0a8 Experimental; focused regressions passed)

`MessageFieldsSessionInputRecorder` wraps an existing input recorder; `include_name` / `include_metadata` both default off. When selected fields are present, it uses a `w-agent.session-message/1` envelope containing the original `content` codec and separate `fields`; the Session stays schema 2. Unselected/empty fields retain the original format. A delegate returning None omits the entire additional record, without inventing fields.

```python
from w_agent import (
    SessionManager, JsonSessionStore, MessageFieldsSessionInputRecorder,
    MessageFieldsSessionInputDecoder, RecordedSessionHistoryPolicy,
    MessageFieldsSessionMessageProjector,
)

# 1. Select fields to preserve; recording still needs record_inputs=True per run.
manager = SessionManager(JsonSessionStore(".wagent/sessions"), input_recorder=
    MessageFieldsSessionInputRecorder(include_name=True, include_metadata=True))
# await manager.run_agent(loop, definition, session_id, messages, record_inputs=True)

# 2. Content decoding alone never resends fields; fields_decoder separately opts in.
decoder = MessageFieldsSessionInputDecoder(include_name=True, include_metadata=True)
content_only = RecordedSessionHistoryPolicy(decoder=decoder)
with_fields = RecordedSessionHistoryPolicy(decoder=decoder, fields_decoder=decoder)
history = await manager.conversation(session_id, history_policy=with_fields)

# 3. Independent display selection, not send authority; inner projector controls content.
projector = MessageFieldsSessionMessageProjector(include_name=True)
```

Field JSON UTF-8 size defaults to at most 64 KiB. Name must be a nonempty string of at most 256 characters. Metadata must be a finite JSON object with string keys, excluding arbitrary objects, NaN/Infinity and excessive nesting. The full wrapped record remains subject to the 16 MiB record limit and Session batch budget. Selected fields are detached and deeply frozen with the Session, then copied when reconstructed into model messages without sharing persisted nested objects. Ignored metadata receives no additional validation when field recording is off.

The decoder can wrap custom content decoders; unwrapped legacy records delegate to the underlying decoder. `SessionMessageFieldsDecoder.decode_fields()` is independently replaceable. History policies validate that results contain only name/metadata and count field JSON against their total content budget; `max_message_field_bytes` defaults to 64 KiB. Returned fields cannot override roles or grant tool permissions. Permission-like metadata keys remain data; hosts must review sensitive values and their selected Provider/extension's handling of these fields.

`MessageFieldsSessionMessageProjector` hides fields by default. Independent `include_name` / `include_metadata` selections expose values under `input_fields`. Its identity includes inner-projector identity, flags and limits; changing disclosure settings requires a fresh snapshot. Corrupt/oversized fields, malformed envelopes and nested wrappers fail even when fields are hidden. Recorders, content decoders and inner projectors remain replaceable, with no Python imports selected by codecs.

Compatibility: a7 can store unknown schema 2 records, but its standard content decoder does not recognize this wrapper codec. Use the new a8 decoder/projector for wrapped content; legacy text projection is unchanged. a8 CLI/TUI Replay supports field disclosure and wrapped content; see [Replay](./event-replay.en.md). Run input manifests reject name/metadata by default, with explicit field sending, recording and history reuse now available; see [run options](./local-runtime.en.md). Focused a8 regressions passed; this does not expand historical a7 acceptance. This switch does not disable existing checkpoints, RunEvents or Provider logs, and does not automatically record final assistant-message name/metadata.

### Display, decoding and model-history policies (2.0.0a7; focused regressions passed)

New APIs are `SessionInputDecoder` / `StandardSessionInputDecoder`, `SessionHistoryPolicy`, `TextSessionHistoryPolicy` and `RecordedSessionHistoryPolicy`. Recording, display and resending content to a model are separate choices; neither recording nor opening replay enables media history.

```python
from w_agent import RecordedSessionHistoryPolicy, RecordedSessionMessageProjector

# This is the host's explicit per-call choice to use recorded inputs as model history.
policy = RecordedSessionHistoryPolicy(max_messages=128, max_content_bytes=16 * 1024 * 1024)
history = await manager.conversation(session_id, history_policy=policy)  # No model invocation.
result = await manager.run_agent(
    loop, definition, session_id, current_messages, history_policy=policy,
)

# Independent read-only display policy for SessionEventReplay.
projector = RecordedSessionMessageProjector(include_text=False, media_mode="metadata")
```

The default remains `TextSessionHistoryPolicy`, ignoring additional media records. The recorded policy replaces each recorded message's text projection with decoded blocks, preserving role/order. Legacy messages without records use text; unknown codecs, corrupt fields or oversized records fail without silent fallback. Each `run_agent` call must select its policy again; `include_history=False` skips it. Policies do not write Stores, fetch URLs or replay tools. Providers may later fetch URLs, so hosts still control destinations, capabilities, costs and sending consent. Approval resume uses its existing checkpoint without reapplying history policy.

The standard decoder accepts only strict `w-agent.session-input/1` text/image/audio envelopes and checks Base64, size and SHA-256. A digest is not a signature or source-authenticity proof. Defaults allow 256 blocks per message, 1,000,000 characters per text block, 8 MiB per media item and 16,384 characters per reference; record format remains capped at 16 MiB. Recorded history defaults to 1,024 messages and 32 MiB of content (UTF-8 text/URLs, raw inline bytes and MIME strings), without silent truncation. This is not a token, request-JSON or whole-process memory budget. Inject custom decoders through `RecordedSessionHistoryPolicy(decoder=...)`; codec values never cause imports. Replace `SessionHistoryPolicy.project(session)` for additional block categories or retrieval, summarization and selection rules. Custom components are trusted Python and must remain side-effect-free themselves.

`RecordedSessionMessageProjector` independently projects ordered input blocks, hiding text, URLs and inline bodies by default. `references` / `content` select media disclosure; `include_text` is separate. Unknown codecs fail the page; replace the message projector for custom encodings. Configuration/limits form the projection identity, so changing them requires rebuilding snapshots. Message failures return no partial new Session snapshot. Existing `TextSessionMessageProjector` is unchanged. `text` and `input_blocks` are parallel views of the same message, not two inputs to concatenate.

CLI: `wagent session view <id> --input-media metadata` shows input-block metadata. References/content additionally require `--confirm-sensitive-content`, independently of output `--media`. `--include-session-text` controls Session text and defaults off. TUI Replay has a separate `Session input media` field, default `off`; references/content require per-read `VIEW CONTENT`, and changes clear old snapshots. Neither UI changes model-context policy, fetches or renders media. TUI media input and history selection are available in the Run form; focused a7 entry-point regressions passed. Retrieval/summary templates are the a8 Experimental additions with focused regressions passing described above.

### Saving inputs

`SessionManager.run_agent(..., record_inputs=True)` explicitly records current input; the default `False` preserves legacy text behavior. Hosts must obtain consent for raw-input persistence first. This example assumes an assembled `loop` and `definition`:

```python
from w_agent import (
    SessionManager, JsonSessionStore, ModelMessage, MessageRole,
    TextContent, ImageContent, StandardSessionInputRecorder, session_input_to_dict,
)

manager = SessionManager(
    JsonSessionStore(".wagent/sessions"),
    input_recorder=StandardSessionInputRecorder(max_inline_bytes=4 * 1024 * 1024),
)
session = await manager.create("Inspect an image")
await manager.run_agent(
    loop, definition, session.session_id,
    (ModelMessage(MessageRole.USER, (
        TextContent("Describe this image"),
        ImageContent(url="https://example.test/private-image.png"),
    )),), record_inputs=True,
)
stored = await manager.get(session.session_id)
payload = session_input_to_dict(stored.messages[0].recorded_input)
```

The bundled template preserves ordered text/image/audio blocks, stores URLs verbatim without fetching, and encodes inline media as Base64 with size and SHA-256. The default StandardSessionInputRecorder excludes message name/metadata; explicit wrapper recording is the a8 Experimental addition described above. Other blocks, including tool calls/results, fail instead of disappearing silently. Replace `SessionInputRecorder.record(message)` to return finite JSON with a non-empty versioned `codec`, or `None` to omit the additional record. Recorders are trusted Python; codecs are never auto-imported, blobs fetched or records executed. Recorders control only the extra field: original `SessionMessage.text` still contains original text, so this alone cannot redact an entire Session.

All current inputs are encoded, size-checked and deeply frozen before Agent execution; failures reject startup without sensitive diagnostics. Manager defaults allow 256 messages / 32 MiB per batch including duplicated text, with configurable batch limits. The record format caps each message at 16 MiB and JSON depth 32. Standard-template defaults allow 256 blocks per message, 1,000,000 characters per text block, 8 MiB per inline item and 16,384 characters per reference; limits can be lowered. Whole historical Sessions are excluded from these bounds; hosts still govern Store file/read-memory limits.

`SessionMessage.recorded_input` is deeply immutable; `session_input_to_dict()` returns a detached copy. Saving an actual record upgrades the Session to schema 2; later text-only runs/archive do not downgrade it. Disabled recording or all-`None` results keep existing Sessions on schema 1. New readers accept schemas 1/2 and reject unknown versions or new fields in schema 1. Older readers such as a6 cannot read schema 2. Keep backups; never edit version tags to conceal incompatibility.

Inputs and summaries are still saved only after an invocation returns, not as a pre-execution durable log. Crashes, cancellation or model failures do not guarantee an input record. Store failures can occur after real actions, without automatic reruns. Approval resume does not duplicate inputs. `conversation()` and default history remain text-only; media-only messages do not become invented empty text. Persistence grants no authority to resend media to a Provider.

Default Session projection and CLI/TUI do not expose the additional field; raw Python Store access can retrieve it and must be protected. Independent input-media display and history policies are described above; TUI media entry and history selection are available; optional name/metadata preservation is available as an a8 Experimental wrapper, with CLI/TUI recording/sending wiring and read-only field disclosure available in a8. Focused a7 regressions passed.

## Cross-Run rich display (2.0.0a7; focused regressions passed)

`SessionEventReplay` reads registered Run order through `SessionRecordSource.get()` and independently accumulates logs through `SessionRunReplaySource.page()`. Pass an existing Session store (or `SessionManager`) and `RunEventReplay`, or replace either source, `RunEventReducer`, or `SessionMessageProjector`. This does not extend persisted Session schema, change `conversation()`/automatic context injection, start Agents/Workflows or grant authority.

```python
from w_agent import (
    JsonSessionStore, JsonlRunStore, RunEventReplay, SessionEventReplay,
    SessionReplaySnapshot, TextSessionMessageProjector, TranscriptRunEventReducer,
)

reader = SessionEventReplay(
    JsonSessionStore(".wagent/sessions"),
    RunEventReplay(JsonlRunStore(".wagent")),
)
page = await reader.page("case-1", run_limit=10, event_limit=100)
saved = page.snapshot.to_dict()  # Host-protected cache, never saved back to SessionStore.
restored = SessionReplaySnapshot.from_dict(saved)
if page.next_run_offset is not None:
    page = await reader.page("case-1", snapshot=restored, run_offset=page.next_run_offset)
```

Snapshots contain `session_id`, projection configuration identity, membership-ordered `run_ids` and visited `SessionRunView` entries. Each separates Session `messages`, accumulated Run `replay`, and last-observed `has_more`. The Session's final assistant text and Run model blocks are not separate generations; display clients should select a view instead of concatenating duplicates. Token/cost values remain per-Run cumulative values without repeated summation or inference from content.

Default `TextSessionMessageProjector()` shows only role and character count. Default `TranscriptRunEventReducer()` hides model text, tool arguments/results and media URLs/bodies. Title, metadata and Run output summaries are not copied. Session text and Run content require independent decisions:

```python
reader = SessionEventReplay(
    session_store, RunEventReplay(run_store),
    message_projector=TextSessionMessageProjector(include_text=True),
    reducer=TranscriptRunEventReducer(
        include_text=True, include_tools=True,
        include_tool_results=True, media_mode="content",
    ),
)
```

Hosts authorize raw storage access before choosing disclosure. Custom message projectors provide `identity` and `project(message)`, returning a finite JSON object or `None`; identity must change with configuration/output schema. Custom Run reducers may support additional block types. These are trusted Python, not isolation boundaries, and should remain side-effect-free. References remain data: no URL or media-file reads.

### Paging, refresh and consistency

- `run_offset` / `run_limit` select a membership slice. Each selected Run consumes one page of at most `event_limit` events from its independent snapshot cursor.
- `next_run_offset=None` ends only this membership sweep, not execution or all event tails. `pending_run_ids` contains unvisited Runs or last-observed nonempty tails; select those Runs again to drain them. To find new events from resumed approvals in older Runs, retain the snapshot and start another sweep at `run_offset=0`.
- New members may append after existing membership. Removal/reordering rejects old snapshots and requires explicit rebuilding. Orphan messages, duplicate Run IDs and events from another Session fail closed. Event `session_id` must match by default. Explicit `allow_unscoped_events=True` accepts missing legacy identifiers, never a different nonempty identifier.
- The complete Session record and projection identity are rechecked after reading. Changes reject the page. Source/projection failures return no partial advance, never mutate the input snapshot and hide exception bodies. Archived Sessions remain readable without unarchiving.
- Defaults: 1,024 Runs, 4,096 Session messages per Run, 32 Runs per page, 1,000 events per Run page, 8 MiB per Run snapshot and 32 MiB per complete snapshot. The default message projector allows one million characters per message. Limits reject rather than truncate. Existing `SessionStore.get()` still loads the complete record; these are not hard storage-I/O or trusted-custom-code memory isolation guarantees.
- Snapshots are deeply frozen and `to_dict()` returns detached JSON, using envelope schema 1. Cross-Session/configuration reuse is rejected. Caches do not prove historical log integrity or identify the actual backing store. Hosts pin sources and protect caches; rechecks provide neither cross-store transactions nor execution locks.

### Remaining boundaries

Only Session-registered Runs are included. `SessionManager` currently records a summary after an invocation returns; a first, still-running unregistered Run does not automatically appear. Sessions default to text-only persistence; optional schema 2 input recording is described above, the default message projector remains text-only, while explicit RecordedSessionMessageProjector selection exposes recorded input blocks without reconstructing missing media. Input blocks remain separate from Run output blocks. `wagent session view` now offers independent content confirmation, source-bound trusted JSON caches and membership/event paging; see [accumulated-view CLI](./event-replay.en.md). [TUI Replay](./tui.en.md) now connects in-memory snapshots and explicit content confirmation. Concrete external retrieval backends and automatic model-summary CLI/TUI wiring remain future work; message-field CLI/TUI recording/sending wiring is an a8 Experimental addition; local retrieval/extractive-summary templates are described above as a8 Experimental additions. TUI Run history selection is available; focused a7 regressions passed.

## Existing data boundaries

- An archived session is read-only until explicitly unarchived.
- Current conversation projection stores text blocks and final agent output only. Tool arguments/results, multimodal content, and arbitrary internal events are not injected across runs.
- JSON storage may contain user text and model output and is not encrypted; filesystem access control belongs to the local application.
- Metadata must contain finite JSON values and is recursively frozen in each record.
- The store uses safe session IDs and atomic file replacement but is not a distributed or multi-primary database.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
