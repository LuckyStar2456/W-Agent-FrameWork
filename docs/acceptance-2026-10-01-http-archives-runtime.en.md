# 2026-10-01 HTTP, raw archives and Runtime accounting acceptance

English | [简体中文](./acceptance-2026-10-01-http-archives-runtime.md)

This is a separate increment after the [previous batch](./acceptance-2026-10-01-sync-usage.en.md). The user authorized related tests, compilation, static checks and temporary loopback-only HTTP servers. No full suite, dependency installation, live vendor calls, build, commit, push or release. Package metadata remains `2.0.0a9`; these source changes are unreleased Experimental.

## Delivered

- [MCP HTTP](./mcp-http-interactions.en.md): 2026 POST subscriptions; 2025-11-25 sessions, HTTP server-request replies and explicit GET notifications. Explicit protocol selection, bounded reads/cancellation/close, no automatic reconnect or replay. Existing buffered transports are unchanged.
- [Knowledge sync](./knowledge-sync-entries.en.md): CLI `--document-formats` and explicit TUI four-format selection, defaulting to UTF-8. Parser selection, key/limits/suffixes participate in preview locking.
- [Raw archives](./knowledge-archives.en.md): replaceable protocol and SQLite content-addressed original bytes with exact trace associations. Independent read/create/write consent, validation of every source before saving, batch transactions and capacity limits. No automatic archival, overwrite restore or cross-store transaction.
- [Runtime usage observation](./service-usage-runtime.en.md): named host catalogs, actual model attempts and optional whole-retriever observation. Shared-budget observations reuse the same ticket without reserving twice. Run, approval resume, evaluation and probe CLI/TUI entries independently authorize host code and ledger recording.
- Eleven new root exports; bilingual README, API, developer, TUI and roadmap updates. The large-character welcome screen is preserved.

Summaries explicitly use `host-operation-not-this-run`: a host-chosen operation may span Runs and is not a tenant. Run model usage is unchanged; saved evaluation JSON reports retain their model scope, and the supplemental ledger is not automatically per-case accounting. Missing usage/cost is not zero. Summary-read failure only warns and never repeats calls.

## Merged focused verification

Existing isolated Python 3.11.9 environment: **375 passed, 0 failed, 0 skipped in 81.49 seconds**, from these 24 selected files. No additional tools were installed. Agent groups of 58/62/88, frontend groups of 29/3 and the earlier 82 overlap with this group and must not be added together.

```text
python -m pytest -q
  tests/test_mcp_http_duplex.py
  tests/test_mcp_client.py
  tests/test_mcp_interactions.py
  tests/test_knowledge_archives.py
  tests/test_knowledge_sync_formats.py
  tests/test_knowledge_sync_management.py
  tests/test_knowledge_sync_cli.py
  tests/test_tui_knowledge_sync.py
  tests/test_knowledge_sync.py
  tests/test_knowledge_sync_acceptance.py
  tests/test_service_usage_runtime.py
  tests/test_service_usage_host.py
  tests/test_service_usage_frontends.py
  tests/test_service_usage_resume_frontends.py
  tests/test_service_usage.py
  tests/test_service_usage_cli.py
  tests/test_service_usage_acceptance.py
  tests/test_local_runtime.py
  tests/test_runtime_shared_budget.py
  tests/test_knowledge_runtime.py
  tests/test_cli.py
  tests/test_tui.py
  tests/test_budget_evaluation_probe.py
  tests/test_knowledge_evaluation_ui.py
```

This is a readable argument list; combine it into one command when executing. Compilation passed for 12 related source files and seven new test files. All 798 root exports exist without duplicates; core import does not force Pillow/Textual imports. Git diff whitespace checks passed. Ruff is absent and was neither installed nor run; no repository-wide type check was performed.

Evidence:

1. Real temporary `127.0.0.1` HTTP: subscription acknowledgement before connection completion plus a parallel ordinary request; legacy initialize/session → SSE callback → independent POST 202 → tool response, plus explicit GET notifications. Listeners/connection tasks are cleaned up.
2. Real offline PDF/DOCX/XLSX/PPTX → persisted trace → byte-identical archive; CLI/TUI DOCX selection; fail-closed source drift, capacity, schema and association corruption checks without partial batches.
3. Real Runtime/SQLite with two Runs sharing an operation, shared-ticket deduplication, distinct failed attempts/retries, unknown cancellation/early close, and no successful Finish after a failed completion observation.
4. CLI/TUI host scopes open/close once. Safe catalog probes do not generate; active probes record actual calls. Either missing usage consent rejects before loading. Unavailable summary reads never retry the model.
5. CLI/TUI resume of real persisted approval checkpoints: first call uses 5 tokens, resume adds 4, ledger totals 9 rather than 14. Original observations are not duplicated; tools execute once and providers close correctly. Numbers are offline fixtures, not invoices.

## Remaining modules

Six groups still have open work. This increment closes subitems in knowledge, accounting and MCP, not the entire framework:

1. **Knowledge:** archive CLI/restore/GC, semantic/overlapping splitting, per-document preparation checkpoints, unknown/not-applied/abandon recovery, cross-store coordination and other backends.
2. **Accounting:** durable Run/Session → operation association, preparation linkage, full coverage of tool-internal/composite services, retrieval/rerank budgets, real vendor pricing and native-cursor metering.
3. **Models/recovery:** additional native media templates and complete application-level/cross-process Agent continuation. Combining service_usage with native cursors is currently rejected explicitly.
4. **MCP:** Tasks, full sandbox binding, OAuth, session DELETE, 2024 dual endpoints and automatic recovery; external-server interoperability is unaccepted.
5. **Plugins:** online discovery, lock generation, package updates, execution leases/draining, consumer rebuilding and state migration.
6. **Isolation/experience acceptance:** network allowlists, generic hard-resource Wasm, real Docker/nsjail/Wasmer, vendor/retrieval quality and manual TUI acceptance.

Multi-agent, distributed workflows and signed trust networks remain [Reserved in the roadmap](./roadmap.en.md). Later verification, installation, builds and releases require fresh batch-specific permission; this approval does not authorize them.
