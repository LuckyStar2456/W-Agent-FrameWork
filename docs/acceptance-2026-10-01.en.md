# Parallel delivery and acceptance — 2026-10-01

English | [简体中文](./acceptance-2026-10-01.md)

This is the first batch's frozen acceptance record. See the [follow-up record](./acceptance-2026-10-01-followup.en.md) for later edits and separately authorized focused checks; this full-suite count does not validate later code.

At the user's request, seven modules were assigned to separate agents, with up to three running concurrently and the primary agent owning shared integration, review and unified acceptance. Existing worktree changes are preserved. No commit, push or release; the version remains `2.0.0a9`. This report describes later worktree changes, not retroactive a9 release contents. All new modules remain `Experimental`.

## Module delivery

| Module | Increment | Boundary |
|---|---|---|
| Ingestion | Optional PDF/DOCX/XLSX/PPTX parsing, incremental extraction reuse, extracted originals/chunk offsets, CLI/TUI preview-digest locking | OCR, raw binary archives, incremental vector synchronization and automatic trace/cache persistence remain |
| Retrieval/Workflow/evaluation | BM25, RRF hybrid retrieval, replaceable reranking, evidence nodes/messages and isolated per-case evaluation | Small-corpus in-memory baseline; real quality/backend acceptance and dedicated evaluation UI remain |
| Index lifecycle | Build/journal discovery, same-store atomic conflict coordination, explicit predecessor-bound retries, ready-vector checkpoint recovery | Not a cross-store lease; pending attempts never auto-replay; unified preparation/Run cost accounting remains |
| Models/media | Same-generation Responses background GET continuation, replaceable checkpoints/SQLite cross-process recovery, final image output | Explicit background/store required; not full Agent recovery; CLI/TUI configuration, shared-budget continuation and live acceptance remain |
| MCP | Explicit handlers, bounded 2026 MRTR, duplex stdio and modern/legacy resource subscriptions | Persistent HTTP SSE/GET, legacy HTTP server requests, Tasks and external interoperability remain |
| Sandbox | nsjail cgroup v2 provider, legacy skill bridge, resource/cleanup hardening and official argument-semantics review | Windows tests do not prove Linux isolation; generic Wasm hard-resource API and network allowlists remain |
| Plugins | Same-name instance replacement preview, quiescence approval, one-shot exact plans, dependent shutdown and stale-handle isolation | Not online package upgrades/hot migration; automatic draining, consumer rebuilding, replacement UI and durable audit remain |

## Integration defects fixed

- Four knowledge panels collided with Textual's message-loop `_task`, treating every action as busy. Dedicated `_operation_task` / `_panel_closing` fields fix this; 18 panel regressions passed.
- Updated the old TUI tab-set test for four new panels. Supplied explicit `max_tool_calls` in the tool-runtime fixture without weakening default budgets or permissions.
- Strengthened the real PDF fixture from a blank page to text extraction of `refund seven days`; XLSX/PPTX and DOCX also use real dependencies to generate and parse documents.
- Official nsjail source review found that CLI `--mount` does not interpret generic mount flags. A private temporary protobuf config now applies `nosuid/nodev/noexec` with guaranteed cleanup; the upstream CPU quota multiplication overflow boundary is also checked. No real Linux execution was performed.
- Added root-export integrity and cross-module acceptance: real text import/digest lock → SQLite reopen → BM25/RRF/reranking → Workflow → ReAct/offline provider → isolated evaluation, asserting USER-role evidence, token usage and cleanup.

## Final clean-environment acceptance

Windows / Python 3.11.9, after all agents stopped code edits and shared integration completed: **1,811 passed, 3 skipped, 0 failed; 1,814 collected in 168.10 seconds**. `pytest.ini` collects both `test_*.py` and `comprehensive_*.py`. No modules were excluded and no document parser dependency tests were skipped.

With user approval, final acceptance used a dedicated temporary venv **without global site-packages**, installing `pip install -e '.[models,tui,testing,knowledge-documents,fastapi]'`. `pip check` returned `No broken requirements found`. Key dependencies: Rich 14.3.4 (satisfying `<15`), Textual 8.2.8, pypdf 6.19.0, python-docx 1.2.0, openpyxl 3.1.5 and python-pptx 1.0.2. Global Python was not modified. The earlier inherited environment and 1,629-test baseline are not final acceptance evidence.

The three skips are:

1. Current Windows permissions cannot create symlinks (`test_symlink_selection_rejected_when_platform_allows_creation`).
2. Windows cannot create the FIFO fixture (`test_fifo_is_rejected_without_opening`).
3. Optional `google.protobuf` is absent from the clean environment, skipping independent nsjail config-schema QA. That test passed in the existing host environment, but does not represent real Linux/nsjail acceptance.

Additional checks: `compileall` passed; all 734 root exports exist without duplicates; installed `wagent --help` runs; headless TUI wide, narrow and resize-back checks pass. No manual terminal-layout/production-interaction acceptance was performed. The 15 real PDF/DOCX/XLSX/PPTX extension tests are included in the unified result; targeted module totals must not be added to 1,811.

Reproduction commands (`python` refers to the isolated environment):

```powershell
python -m pytest -q --tb=short --junitxml=<report-path>
python -m compileall -q w_agent
python -m pip check
python tests/integration_tui_smoke.py --output <tui-report-directory>
```

The temporary environment and artifacts are under `C:\Users\97554\AppData\Local\Temp\wagent-clean-20261001-9b85883185c44a94baaf28c3b662defa`; `reports/pytest.xml` is final JUnit output and `reports/tui/` contains automated TUI screenshots. They are not package contents or permanent archives.

No paid model/Embedding calls, external reranker or Qdrant writes were executed. Docker API discovery reported the missing Linux engine pipe. Real Wasmer/nsjail/other OS acceptance remains absent. Offline/mock tests do not prove vendor integration, sandbox isolation or model quality.

## Remaining

The seven delivery slices are complete, not the full framework roadmap. Remaining development is grouped into six areas:

1. **Knowledge/indexing:** raw binary/provenance-cache persistence, incremental vector synchronization/old-point cleanup, semantic splitting, per-document preparation checkpoints, cross-store leases, other backends and dedicated knowledge evaluation entries.
2. **Accounting/budgets:** a unified durable ledger and cost aggregation across preparation, retrieval, native continuation and the main Run; unknown costs must not become zero.
3. **Models/interactions:** more vendor media mappings, native-continuation CLI/TUI assembly, full Agent/tool recovery and dedicated TUI media display.
4. **MCP:** the HTTP interactions above, Tasks, automatic recovery and sandbox binding.
5. **Plugin engineering:** online discovery/lock generation/package upgrades, automatic draining/migration, consumer rebuilding, replacement CLI/TUI and audit.
6. **Sandbox:** a generic hard-resource Wasm protocol, real network allowlists and multi-platform validation.

Real vendor/Embedding/Qdrant services, retrieval quality, Docker/nsjail/Wasmer and manual TUI acceptance are separate outstanding checks, not completed by local regressions. See the [roadmap](./roadmap.en.md). Multi-agent/distributed Workflow, cross-store atomic transactions, hosted evaluation and signing/trust networks remain reserved, not delivered first-release features.
