# Follow-up development and focused acceptance — 2026-10-01

English | [简体中文](./acceptance-2026-10-01-followup.md)

This page preserves its batch's evidence. Sync entries and cross-service observations were subsequently developed; consult the [next acceptance batch](./acceptance-2026-10-01-sync-usage.en.md) and roadmap instead of treating historical remaining items below as current status.

This page records changes after the [first seven-module unified acceptance](./acceptance-2026-10-01.en.md). Its 1811 passed result does not cover these later edits. The user separately authorized related tests, compilation and static checks, but no full suite, dependency installation, external services or release. Additions remain unreleased worktree `Experimental`; the package version is unchanged.

## Additions

| Module | Usable entry | Boundary |
|---|---|---|
| Incremental knowledge sync | Replaceable SQLite trace/vector-cache persistence, source-bound stable IDs, differential upsert/delete and receipt recovery | Python API implemented with focused acceptance; no automatic snapshot-index migration or guaranteed old-version remote retrieval after deletion |
| Plugin replacement entries | Persistent `wagent plugin session`; TUI Plugins exact approval and current-manager replacement | Current process only, not online upgrades/cross-process hot updates; consumers are not restarted |
| TUI media display | Replay independently confirmed image character preview, WAV metadata and new-file raw-byte export; replaceable renderer | No network/playback/opening; decoding is not sandboxed and export directories require trusted host ownership |
| Knowledge evaluation entries | `evaluate --knowledge-entry ... --confirm-knowledge-code --confirm-knowledge-queries`; equivalent TUI Evaluation confirmations | Fresh Session/Run per case, batch preflight; retrieval costs excluded from model totals |

## Validation status

Uses the existing clean Python 3.11.9 environment without global site packages:

| Focused group | Result | Coverage |
|---|---|---|
| UI and entry integration | 227 passed, 54.89 seconds | Plugin replacement/loading/installation regression, CLI/TUI, media display/replay, knowledge evaluation and reporting scope |
| Knowledge and cross-module integration | 115 passed / 2 skipped, 117 collected, 4.78 seconds | 31 sync cases, 15 real-format parser cases, file/vector Writer, framework integration and public exports |

The two skips are Windows symlink/FIFO limitations, not missing parser dependencies. Groups share four package checks and must not be summed. JUnit files are `reports/followup-ui.xml` and `reports/followup-knowledge.xml` inside the acceptance environment. No full suite was rerun; the earlier 1811 passed result covers only that earlier revision.

After final export integration, all four package-integrity tests passed again. All 760 public exports exist without duplicates; core import does not load Pillow/Textual. Related implementation/tests/setup.py passed compileall and `git diff --check`; no repository-wide type checker or additional lint tool ran. Durations above use pytest terminal totals; internal JUnit durations may be slightly shorter.

Sync review added canonical endpoint validation and independently approved definite `not-sent` retries with immutable prior generations. Unknown/pending outcomes still cannot replay. Retrieval, embedding and Qdrant used offline doubles/injected transports: no live connectivity, quality or billing acceptance. TUI checks were headless, not manual terminal UX acceptance.

The new `media-preview` extra is declaration-only; image tests use existing Pillow 12.3.0 without reinstalling. Standalone installation of that extra remains unaccepted. No build, push or release occurred; the version remains `2.0.0a9`.

## Remaining

The four concrete capabilities above are closed for this batch. Remaining work is grouped into six areas, not equal effort estimates:

1. Knowledge: dedicated incremental-sync CLI/TUI, original binary archival, semantic chunking, unknown/not-applied recovery or abandonment, and cross-database coordination.
2. Accounting: a unified model/retrieval/embedding/rerank ledger and budget lifecycle; existing model token/cost controls remain available.
3. Models and recovery: more native media templates and application-level/cross-process stream continuation.
4. MCP: persistent HTTP subscriptions, legacy HTTP server requests, Tasks and Sandbox binding.
5. Plugins: online discovery/locking/upgrades, execution leases and state migration; current replacement affects only the current manager.
6. Isolation and delivery acceptance: network policies/generic Wasm, live services, Docker/nsjail/Wasmer and manual TUI acceptance.

See the [roadmap](./roadmap.en.md) and [knowledge sync boundaries](./knowledge-sync.en.md). Reserved high-resolution color previews/audio playback are not additional first-release requirements, and reserved designs are not presented as delivered capabilities.
