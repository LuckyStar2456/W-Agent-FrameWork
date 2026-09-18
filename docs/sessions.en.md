# Session lifecycle and cross-run context

English | [简体中文](./sessions.md)

Status: local session create/list/archive/unarchive, JSON persistence, cross-run text projection, and agent run start/approval resume are `Implemented` in Phase 3 / `2.0.0a1`. Per-agent cross-session usage/cost summaries are `Experimental` on current main. General replay for multimodal content, tool events, and arbitrary RunEvents remains `Planned`.

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

## Data and boundaries

- An archived session is read-only until explicitly unarchived.
- Current conversation projection stores text blocks and final agent output only. Tool arguments/results, multimodal content, and arbitrary internal events are not injected across runs.
- JSON storage may contain user text and model output and is not encrypted; filesystem access control belongs to the local application.
- Metadata must contain finite JSON values and is recursively frozen in each record.
- The store uses safe session IDs and atomic file replacement but is not a distributed or multi-primary database.
