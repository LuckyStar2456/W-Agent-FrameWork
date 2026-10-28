# Knowledge synchronization TUI

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](knowledge-sync-tui.md)

2.0.0 Experimental. The dedicated `Knowledge sync` page offers local plan inspection and explicitly authorized host operations. It reuses the CLI management service rather than implementing another state machine. The existing large-character welcome branding is unchanged.

## Complete local entry flow

1. Enter the trace database, namespace/version, trusted root, relative-path JSON array and chunk byte limit. Type `READ SYNC` and choose Preview trace import. This is read-only and creates no database. UTF-8 remains default; explicitly check the optional PDF/DOCX/XLSX/PPTX option to enable document extraction. Selection and parser configuration enter the preview lock, so changing them requires a new preview. Dependencies load on use and are never installed automatically; trusted files only, not a parser sandbox. `[]` means an explicit empty version, not default paths.
2. Review and **manually enter** the returned `preview_digest`. Type `READ SYNC` and `RECORD SYNC`, plus `CREATE SYNC` only when creating a database. Choose Save approved trace. Source/path/configuration changes invalidate the approved digest before database creation.
3. Enter the saved `trace_digest`, journal database, trusted `module:factory` and binding. Incremental versions also require the completed predecessor plan and separately approved cache digest. Type `READ SYNC`, `LOAD INDEX HOST`, `RECORD SYNC`, plus `EMBED SYNC` when new embeddings are needed and `CREATE SYNC` for a new journal. Prepare and stage may incur charges and persists exact vectors/plans while reserving the target, but sends no upsert/delete.
4. Enter the plan digest and use only `READ SYNC` to inspect. The safe summary includes batch states and definite not-sent retry candidates, with no host import, bodies, vectors, paths, endpoint or evidence references.
5. Independently enter the approved plan digest. For upsert/delete, enter the corresponding approval digest and `UPSERT SYNC` / `DELETE SYNC` separately. Add `READ SYNC`, `LOAD INDEX HOST` and `RECORD SYNC`, then Execute. Each action word must be paired with its digest; upsert authority cannot authorize deletion.

Actions reject unrelated confirmation words. Omitting `EMBED SYNC` during preparation is useful only when every required block is validly reusable and no new model calls are needed. See [synchronization semantics](knowledge-sync.en.md).

## Authority and usage boundaries

Nothing reads files, loads a host, or calls a model/index by default. Each action requires exact paths/identities and separate confirmation words. Capturing a request consumes all confirmation fields once, including invalid requests. Preview output never populates approval digests or authorizes execution.

The active request is captured independently and controls are locked, so subsequent edits cannot change the in-flight operation. Cancellation requests stopping, not rollback: embeddings may already be billed, SQLite may have committed, and remote writes may have been sent. Inspect the same plan journal after cancellation; an unknown result is not evidence that nothing was sent.

A host `module:factory` is explicitly authorized, unsandboxed local Python that can access files/network. Permission to load it does not mean the framework isolates it. Load only reviewed host code. Local inspection requiring no host must not import an entry merely because it remains in an input field.

Plan approval, upsert approval, deletion approval and recording are separate authority boundaries. Synchronization may remove prior-version points, invalidating historical remote retrieval; use a dedicated collection. This page exposes only the service's safe summary, with no body/vector/remote-target disclosure toggle. Review target configuration through the trusted host/API. Results use escaped JSON and display paging, never terminal control sequences or Rich markup; paging performs no I/O.

This page has no automatic retry, approval or polling. `pending`, `unknown` and `acknowledged` are never replayed automatically. Evidence-based reconciliation or independently approved not-sent retry uses the corresponding explicit management API/CLI, not repeated Execute clicks.

## Current verification status

The subsequent document-format round adds real DOCX opt-in → preview → digest-locked save → trace-reopen coverage. Raw binary archival is a [separate API](knowledge-archives.en.md); this panel never archives/restores originals automatically. Refer to the parent task's current merged targeted evidence for format/archive counts.

Focused panel tests verify real local preview → digest-locked save → reopened trace, and rejection after source changes. Other cases cover independent authority, captured requests, host-free inspection, paired upsert/delete approvals, cancellation/failure without automatic retries, control locking and escaped/paged results. Separate management tests cover actual host lifecycle and mocked index transport. See this round's final acceptance record for counts; old full-suite results are not evidence for this new panel. No paid embeddings, live Qdrant, dependency installation or release is performed.
