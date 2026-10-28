# Sync entries and cross-service accounting acceptance — 2026-10-01

English | [简体中文](./acceptance-2026-10-01-sync-usage.md)

This increment follows the [previous focused batch](./acceptance-2026-10-01-followup.en.md) and does not inherit the first 1811-test full-suite result. The user authorized related tests, compilation and static checks only. No dependency installation, live service calls, build, commit, push or publication occurred. Metadata remains `2.0.0a9`; additions are unreleased `Experimental` source.

## Delivered

- [Sync management and CLI](./knowledge-sync-entries.en.md): UTF-8 preview/digest-locked trace save, named-host exact vector-plan preparation/persistence, safe inspection, separate upsert/delete approval/execution, definite-not-sent retry and host-evidence completion reconciliation. Known target conflicts fail before embedding; durable staging still checks races.
- [Sync TUI](./knowledge-sync-tui.en.md): the same service's complete import-to-approved-execution main path, independent one-shot consent, frozen requests, background cancellation and safe paging. Large-character branding remains. Retry/reconciliation use the explicit CLI, not TUI buttons.
- [Cross-service usage](./service-usage.en.md): model/embedding/retrieval/rerank observation protocol, memory/SQLite stores and explicit decorators. Existing shared budgets still own admission without duplicate reservations. Currency/version groups and unknown/not-applicable dimensions remain separate. Read-only `wagent service-usage` exposes input/output tokens, costs and completeness.
- `examples/knowledge_sync_host.py`: editable local Ollama/Qdrant factory without import-time requests, model pulls or collection creation. Configure actual models and a dedicated collection first.

## Validation scope

Existing isolated Python 3.11.9 environment; the final frozen-code focused group returned **282 passed, 0 failed, 0 skipped, 51.72 seconds**. JUnit: `reports/sync-service-integration-final.xml` inside the acceptance virtual environment. Related compileall, public exports and Git whitespace checks passed. All 787 public exports exist without duplicates; core import does not load Pillow/Textual. No repository-wide type checker or additional lint tool ran.

The merged group selects 18 files: new sync management/CLI/TUI, service usage, two root integration files, and affected shared budgets, embedding budgets, session usage, CLI/TUI, package APIs and existing cross-chain acceptance. It is not the full suite; agent/earlier counts overlap and must not be added.

Key evidence uses real temporary SQLite and offline services:

1. Registered CLI import/preview/save through prepare/execute; changed second-version files produce exact upserts/deletes. Missing deletion approval fails before host import. Executing completed plans never re-embeds or resends.
2. Definite-not-sent inspection and approved retry start at generation 0; exhausted 64-retry plans remain inspectable. Unknown/ack outcomes never replay; cancellation/cleanup failures preserve state boundaries.
3. All four service kinds share durable observations while model/embedding retain the original SQLite budget. Reopen yields 9 known tokens and 0.03 USD under host fixture prices; another over-budget model call is rejected. These are offline fixture values, not invoices.
4. No query/document text enters the ledger; missing prices do not become zero. `1E28 + 1E-28` remains exact under a low-precision host Decimal context.

## Remaining

The six groups remain partly open; this batch closes their sync entries and explicit unified observation portions:

1. Knowledge: other-format trace entries, binary archival, semantic chunking, partial-preparation checkpoints, unknown/not-applied or abandonment recovery and cross-store coordination.
2. Accounting: automatic run-chain association/UI assembly, retrieval/rerank service-budget wiring, real vendor billing maps and native-cursor metering. The new ledger does not automatically rewrite Run/Session/evaluate statistics.
3. Models/recovery: further native media templates and complete application/cross-process Agent continuation.
4. MCP: persistent HTTP subscriptions, legacy HTTP server requests, Tasks and Sandbox binding.
5. Plugins: online discovery/locking/upgrades, execution leases and state migration.
6. Isolation/acceptance: network policies/generic Wasm, live services, Docker/nsjail/Wasmer and manual terminal UX.

This batch does not prove live billing, retrieval quality, remote state, cross-store atomicity or manual TUI usability. The [roadmap](./roadmap.en.md) remains authoritative; the overall goal remains incomplete.
