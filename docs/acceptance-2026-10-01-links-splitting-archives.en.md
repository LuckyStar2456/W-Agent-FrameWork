# 2026-10-01 Durable links, splitting and archive entry acceptance

English | [简体中文](./acceptance-2026-10-01-links-splitting-archives.md)

A separate increment after the [previous batch](./acceptance-2026-10-01-http-archives-runtime.en.md). The user authorized related tests, compilation and static checks. No full suite, dependency installation, external services, builds, commits, pushes or releases. Metadata remains `2.0.0a9`; additions are unreleased Experimental.

## Delivered

- [Usage links](./service-usage-links.en.md): replaceable protocol, memory/SQLite templates and immutable Run/Session→operation mappings. Save before history/knowledge preparation; validate identity before resume. Link failure prevents model/tool calls. Failed preparation can leave a preassociation, not a completed Run.
- Read-only `service-usage-link` selection by Run, Session or operation; `service-usage --run ... --links-database ...` resolves an association and shows the entire operation. Explicit `host-operation-not-this-run` scope means shared-operation Run summaries must not be added twice. New editable [host example](../examples/service_usage_host.py) performs no automatic I/O.
- [Structural/overlapping splitting](./knowledge-splitting.en.md): exact Unicode/UTF-8 spans, paragraph/sentence preferences, hard byte bounds and bounded character overlap. Explicit sync API/CLI/TUI options and preview locks. Default v1 serialization/point IDs remain compatible; structural mode uses strictly reconstructable v2, not model semantic inference.
- [Archive entries](./knowledge-archive-entries.en.md): `knowledge-archive preview/save/inspect/export`. Independently approved digest and complete source validation before saving; export only creates a selected new single file, rejects overwrites/links and never executes content.
- Fifteen new root exports; bilingual README, API, developer/TUI, roadmap and affected older documentation updates. The large-character TUI welcome remains unchanged.

## Focused verification

Existing isolated Python 3.11.9 environment. Final merged result: **485 passed, 0 failed, 0 skipped in 127.48 seconds**. The 31 selected files are below. Agent groups of 137/42/79 and root groups of 48/16 overlap and cannot be summed as independent evidence.

```text
python -m pytest -q
  tests/test_service_usage_links.py
  tests/test_service_usage_link_cli.py
  tests/test_service_usage_runtime.py
  tests/test_service_usage_host.py
  tests/test_service_usage_frontends.py
  tests/test_service_usage_resume_frontends.py
  tests/test_service_usage_cli.py
  tests/test_service_usage.py
  tests/test_service_usage_acceptance.py
  tests/test_local_runtime.py
  tests/test_runtime_shared_budget.py
  tests/test_knowledge_runtime.py
  tests/test_sessions.py
  tests/test_knowledge_splitting.py
  tests/test_knowledge_splitting_tui.py
  tests/test_knowledge_split_archive_acceptance.py
  tests/test_knowledge_archive_entries.py
  tests/test_knowledge_archives.py
  tests/test_knowledge_import_extensions.py
  tests/test_knowledge_sync.py
  tests/test_knowledge_sync_management.py
  tests/test_knowledge_sync_cli.py
  tests/test_knowledge_sync_formats.py
  tests/test_knowledge_sync_acceptance.py
  tests/test_tui_knowledge_sync.py
  tests/test_knowledge_ingestion.py
  tests/test_knowledge_management.py
  tests/test_cli.py
  tests/test_tui.py
  tests/test_budget_evaluation_probe.py
  tests/test_knowledge_evaluation_ui.py
```

This readable argument list should be combined into one command. Compilation passed for 15 related source files, six new test files and one example. All 813 root exports exist without duplicates; core import does not load Pillow/Textual. Git diff whitespace checks passed. No extra lint installation/execution or repository-wide type check.

Evidence:

1. Real SQLite reopen, idempotence/capacity/conflict checks; cancellation drains the started worker and never enters the model. Pre-preparation association survives a retrieval failure and resolves its observed operation costs.
2. Real approval checkpoint: wrong operation/Session or absent association rejects before checkpoint claim/tool calls; the correct association can still resume once. Existing SessionManager protocol is unchanged.
3. Legacy v1 canonical JSON/digest/stable-vector-ID reference compatibility; v2 repeated text, Chinese, emoji, overlap, configuration drift, tampering, zero-repeat embedding, cancel-without-save and actual headless TUI.
4. Registered main CLI path: structural overlap preview→approved v2 trace save→archive preview/save/inspect→single-blob export. Original bytes match exactly; a repeat export rejects without changing files/stores.
5. Actual temporary Windows junction/hard-link rejection, no filesystem access without consent, no archive creation on digest/source drift, corrupted-data rejection, fsync cleanup, fixed errors if cleanup fails, and preservation of replacement files.
6. Several Runs sharing an operation resolve to one operation total rather than per-Run billing; the example factory neither creates directories nor opens SQLite.

## Remaining

The framework goal stays active, with open work across six groups:

1. Knowledge: model-semantic splitting, custom persistent splitter codecs, per-document preparation checkpoints, unknown/not-applied/abandon recovery, cross-store coordination and other backends; archive directory restore, GC/encryption and a dedicated TUI entry.
2. Accounting: per-observation Run attribution for services/preparation, complete automatic coverage, retrieval/rerank budgets, real vendor pricing and native-cursor accounting. Links do not alter Run model usage or provide cross-store atomicity.
3. Models/recovery: more native media templates and complete application-level/cross-process Agent continuation.
4. MCP: Tasks, full sandbox binding, OAuth, session DELETE, older dual endpoints, automatic recovery and external interoperability.
5. Plugins: online discovery, lock generation, package updates, execution leases/draining, consumer rebuilding and state migration.
6. Sandbox/live acceptance: network allowlists, generic hard-resource Wasm, actual Docker/nsjail/Wasmer isolation, vendor/retrieval quality and manual TUI.

Passing results only cover the named scope, not live services or the entire framework. Reserved items remain in the [roadmap](./roadmap.en.md). Later verification, installation, builds and releases still require separate permission.
