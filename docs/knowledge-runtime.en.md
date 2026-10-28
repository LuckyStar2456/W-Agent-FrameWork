# Named knowledge assembly and CLI/TUI queries

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./knowledge-runtime.md)

Status: 2.0.0 `Experimental`, included in 2.0.0 and outside `2.0.0a9`. All 11 offline regressions in `tests/test_knowledge_runtime.py` pass. UI/live-service acceptance and publication have not been performed.

## Configuration selects, never authorizes

Local Runtime configuration accepts `"knowledge": {"binding": "manual"}`. `LocalKnowledgeConfig` stores only a 1–128-character `[A-Za-z0-9][A-Za-z0-9_.:-]*` name, not paths, credentials, factory references or queries. It selects a host `LocalKnowledgeBinding`, not a tenant, hosted resource or ACL.

`LocalKnowledgeBinding(retriever, limit=4, limits=SessionHistoryLimits(), timeout=30)` borrows a `KnowledgeRetriever`. Hosts choose keyword memory, pinned snapshot vectors or custom retrieval; embedding/budget/backend configuration remains host-owned. Constructing bindings or Runtime performs no retrieval/database initialization and never closes borrowed retrievers automatically.

```python
from w_agent import LocalKnowledgeBinding, assemble_local_runtime

# config.knowledge selects manual; the host has constructed retriever.
runtime = assemble_local_runtime(
    config, ".wagent", knowledge_bindings={"manual": LocalKnowledgeBinding(retriever)},
)
async with runtime:
    run = await runtime.run(
        "Explain the returns process using the references.",
        knowledge_query="returns process", confirm_knowledge_query=True,
        include_history=False,  # No history, but the explicit query still runs.
    )
```

Unexecuted example. `run_messages()` supports the same arguments; media input never implicitly becomes a query. Without knowledge_query, no retrieval occurs even if configuration selects a binding. Blank/oversized queries (4096 UTF-8 bytes), missing confirmation or missing bindings fail before Session creation/loading. Confirmation must be literal True, not integer 1.

Supplying a Python catalog validates names, at most 64 typed entries and the selected binding. Omitting the catalog still allows assembly for ordinary runs/checkpoint resume; only explicit queries require the binding. JSON never imports code, reads knowledge directories or grants external access.

## Context and history

Each query builds a fresh `AsyncKnowledgeContextPolicy`: selected history policy → cited untrusted USER knowledge data → current input. Default history behavior is retained and custom policies are composed, without promoting knowledge to SYSTEM instructions. Empty Sessions can retrieve too.

At this explicit knowledge entry, `include_history=False` / CLI `--history none` means no history projection/disclosure while still retrieving knowledge. Runtime internally supplies an empty history policy, not renewed history authorization. The existing knowledge policy still bounds raw Session history size; overflow fails rather than silently dropping it. Ordinary runs without knowledge retain previous include_history semantics.

This knowledge template supports text history; recorded nontext blocks fail without OCR or silent downgrade. Document count, byte and output-context limits remain enforced. Retrieval failure prevents Agent Loop startup, partial context and automatic retry, though a Session may already exist and external retrieval may already have incurred charges. `run-resume`/TUI checkpoint resume use saved requests without reopening the current knowledge factory or retrieving again.

Direct lower-level Session use of `AsyncKnowledgeContextPolicy` retains its original include_history switch. Knowledge-only composition belongs to this new explicit Runtime path and does not change that protocol.

## CLI

An explicit `module:factory` is called without arguments and returns an async context manager whose entry yields `{name: LocalKnowledgeBinding}`. It is unsandboxed trusted Python: hosts may load pinned snapshots, borrow/create clients and clean up on exit. This is not automatic plugin installation, and shared project configuration cannot grant execution permission.

The repository supplies `examples.knowledge_runtime:knowledge_catalog`, an in-memory demonstration with no network/file reads and sample text only. Add the knowledge selection above, then use this unexecuted command:

```powershell
py -3.11 -m w_agent run "Explain the sample returns guidance" --config .wagent/config.json --knowledge-entry examples.knowledge_runtime:knowledge_catalog --knowledge-query returns --confirm-knowledge-code --confirm-knowledge-query --confirm-model-call --history none
```

- `--confirm-knowledge-code` authorizes factory import/setup/cleanup, which may have side effects and requires host review.
- `--confirm-knowledge-query` authorizes query disclosure, potentially billable query embedding/retrieval and sending retrieved bodies to the configured model. It does not authorize bulk document embedding, index writes or saving originals.
- `--confirm-model-call` remains separately required. Input recording, tools and budget code retain their own permissions.
- Factory and query must be supplied together with independent confirmations. Basic validation precedes input-file/tool/factory loading. Missing knowledge.binding prevents knowledge-factory import.
- Only `run` is wired currently. Provider probe, evaluate, Workflow and checkpoint resume never automatically load this factory; dedicated assembly for those paths remains separate work.

## TUI

Run adds Knowledge host and Explicit knowledge query inputs. Enter `LOAD KNOWLEDGE`, `QUERY KNOWLEDGE` and the existing `RUN` each time. history=none permits knowledge-only context. Confirmation words are consumed at capture, fields lock with other run parameters, and in-flight work uses captured values rather than later edits. Missing consent blocks input-file/factory loading.

Run provides factory/query fields. A separate [Knowledge management tab](./knowledge-management.en.md) has locally regression-tested import preview/save, catalog and pinned search; it never automatically selects a Run version. [Index journal review/reconciliation](./knowledge-index-management.en.md) and [plan preparation/approved execution](./knowledge-plan-actions.en.md) are separate entries. Headless TUI regressions pass; manual layout and production interaction acceptance has not been performed.

## Lifecycle, costs and data

After successful factory entry, invalid catalogs, failure and cancellation attempt cleanup. A True return from factory exit cannot suppress Runtime errors. Trusted setup/cleanup can block, fail or have prior side effects; the factory owns cleanup during incomplete entry, and repeated cancellation can interrupt it. Cleanup failure is not evidence that generation never ran: inspect persisted state instead of replaying blindly.

Configuration/bindings grant no file/network/model-tool authority. Hosts supply OS sandboxing where required. Context retrieval is not a ToolExecutor invocation and receives no per-tool-call approval; callers own query confirmation and retrievers enforce resource permissions.

Queries are never inferred from prompts/history/files or additionally stored in a dedicated query log. Retrieved text does become model input and may enter existing Run/checkpoint persistence; apply those storage policies to sensitive content. Citation labels do not prevent prompt injection. Hosts may explicitly wrap embeddings with [shared budgets](./embeddings.en.md); unwrapped retrieval does not automatically enter Run/Session or pool totals.

## Progress and remaining work

Named bindings, per-call Runtime queries, and knowledge-only mode pass local regressions. [Workflow/evaluation assembly](./knowledge-workflow-evaluation.en.md) supplies dedicated APIs and offline end-to-end tests. Consult component documentation and the [roadmap](./roadmap.en.md) for CLI/TUI interaction, live-service acceptance, and other modules.

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
