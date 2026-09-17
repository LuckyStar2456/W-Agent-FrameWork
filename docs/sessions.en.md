# Session lifecycle and cross-run context

English | [简体中文](./sessions.md)

Status: local session create/list/archive/unarchive, JSON persistence, cross-run text projection, and agent run start/approval resume are `Implemented` in Phase 3 / `2.0.0a1`. General replay for multimodal content, tool events, and arbitrary RunEvents remains `Planned`.

## Public APIs

- `SessionManager`: coordinates lifecycle, text history, and ordinary `AgentLoop` values.
- `SessionRecord`: immutable session snapshot with messages, run summaries, and metadata.
- `SessionRunRecord`: stores stop reason, output, step/tool counts, and token usage.
- `InMemorySessionStore`: tests and short-lived local development.
- `JsonSessionStore`: atomic JSON storage for one local lifecycle owner.

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

The next `run_agent()` prepends previously projected text messages by default. Set `include_history=False` to disable automatic context assembly; the current input and result are still recorded.

## Approval resume

When a run stops with `NEEDS_APPROVAL`, call `resume_agent()` with the same loop/run store and approval granted by the local application. The manager verifies that the run belongs to the session, updates its existing summary instead of creating a duplicate, and does not store user input twice.

## Data and boundaries

- An archived session is read-only until explicitly unarchived.
- Current conversation projection stores text blocks and final agent output only. Tool arguments/results, multimodal content, and arbitrary internal events are not injected across runs.
- JSON storage may contain user text and model output and is not encrypted; filesystem access control belongs to the local application.
- Metadata must contain finite JSON values and is recursively frozen in each record.
- The store uses safe session IDs and atomic file replacement but is not a distributed or multi-primary database.
