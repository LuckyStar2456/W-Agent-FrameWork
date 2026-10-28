# Context preparation and main-Run usage aggregation

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./context-accounting.md)

Status: `2.0.0a9 Experimental`, with focused regressions passing. See [a9 release notes](./releases/2.0.0a9.en.md) for validation scope; this is not evidence of real-model or billing acceptance.

a9 additionally provides `SQLiteSessionSummaryObserver` (2.0.0a9 Experimental; see a9 validation), described below. See a9 release notes for this addition's validation.

## Durable SQLite summary reports (a9 addition)

Uses the existing `SessionSummaryObserver.record()` protocol and replaces the memory observer without changing models, Agent Loops or summary policies. Persists prompt-free summary Run reports only, not main results, prompts, summaries, exception bodies or Provider credentials.

```python
from w_agent import SQLiteSessionSummaryObserver, AgentSessionHistorySummarizer

# Parent directory must exist; the host explicitly authorizes local writes.
accounting = SQLiteSessionSummaryObserver(
    "summary-usage.sqlite3", "support-refund-20260928", max_runs=128,
)
await accounting.initialize()
summarizer = AgentSessionHistorySummarizer(summary_loop, accounting)
# summary_loop is a host-authorized dedicated Loop with an empty tool catalog.
# Inject summarizer into AsyncSummarizedSessionHistoryPolicy, then run the main Agent.
usage = await accounting.snapshot(run.result)

# After restart, reopen the same file, operation identity and capacity settings.
reopened = SQLiteSessionSummaryObserver(
    "summary-usage.sqlite3", "support-refund-20260928", max_runs=128,
)
reports = await reopened.reports()
```

`operation_id` is a host-selected association key for a local development task, not a tenant, authorization domain, automatic Session association or model-execution lock. It allows at most 128 ASCII letters/digits/`_.:-`, starting with a letter/digit. Do not embed secrets; Run IDs, operation identities and pricing versions remain local data. Several operations may share a database without establishing access isolation.

- Construction performs no database I/O. Explicit `initialize()` creates/opens a dedicated file and registers the operation, requiring an existing parent directory. Unknown database identities/versions are rejected without migration or overwriting business tables. Failed initialization may leave an empty file.
- Configuration is immutable. Per-operation `max_runs` (default 1024, range 1–10000) and `max_report_bytes` (default 16384, range 512–65536) are persisted and must match on reopening. Another client cannot bypass capacity by selecting a larger local limit.
- `record()` checks prior reports, conflicts and capacity and writes within one SQLite transaction. Equal reports are idempotent; started may become terminal, including at capacity. Conflicting terminal reports fail, including corrections of unknown terminal usage. A terminal-first report may be stored but proves no actual model execution.
- `reports()` uses a read-only connection and read transaction, returning latest reports in first-registration order. Missing files or unregistered operations fail without creating files or pretending the ledger is empty. Row count and payload sizes are bounded; oversized records, duplicate JSON keys, unsupported versions and inconsistent identities/totals/completeness are rejected, never silently skipped.
- Database work runs in worker threads with per-operation connections closed afterward. Write transactions coordinate instances/processes using the same local file, not Agent execution ownership. Lock timeout defaults to 1 second, configurable in `(0, 60]`; lock failures never retry, fall back to memory or replay models.
- Cancellation stops waiting but an already-started thread/transaction may still commit. Failure does not prove no write occurred. Reopen reports to reconcile; never blindly rerun a model. Model execution and report storage are not one transaction: a crash may leave only started, with unknown charges.
- `snapshot(main_result)` reuses existing aggregation. Main results are not persisted here; after restart the host must supply the corresponding cumulative result again. No main result still means an incomplete known summary subtotal.

Use trusted host-managed local SQLite files only. Database identity and JSON validation are not signatures and do not protect against other writers with filesystem access. No automatic cleanup, retention policy, stranger-ledger import or cross-file transaction is provided. Per-operation bounds do not cap operation count, SQLite internal scans, journals or total disk usage; hosts own backups, directory permissions and disk capacity. See a9 release notes for focused validation; this is not cross-process crash or real fault-recovery acceptance.

## Assembly and usage

`InMemorySessionSummaryObserver` implements `SessionSummaryObserver` and plugs directly into [AgentSessionHistorySummarizer](./sessions.en.md). The host creates one observer for a deliberately associated operation, then calls `snapshot(main_result)` to combine its summary reports with one cumulative main-Run result. This reads no raw Session, log or model body and never modifies `RunResult`, Session totals or existing billing records automatically.

```python
from w_agent import (
    AgentSessionHistorySummarizer, AsyncSummarizedSessionHistoryPolicy,
    InMemorySessionSummaryObserver,
)

# The host authorizes and assembles summary_loop with budgets/model and an empty
# tool catalog; see the Session guide.
accounting = InMemorySessionSummaryObserver(max_runs=128)
summarizer = AgentSessionHistorySummarizer(summary_loop, accounting)
policy = AsyncSummarizedSessionHistoryPolicy(summarizer, recent_turns=2)

# Obtain application-level authorization before actual model calls.
run = await runtime.run(prompt, session_id=session_id, history_policy=policy)
usage = await accounting.snapshot(run.result)
report = usage.to_dict()
print(report["known_usage"], report["usage_complete"], report["cost_totals"])
```

If the main call fails, is cancelled or returns no `RunResult`, `await accounting.snapshot()` exposes known summary consumption but sets `main_result_supplied=False` and both overall completeness flags to False. This does not imply that the main call was free or never happened: its consumption is simply absent from this report.

After approval recovery, supply the latest cumulative main result explicitly: `await accounting.snapshot(resumed.result)`. The observer does not store main results and never adds pre-resume and post-resume cumulative tokens together. Supply only one main result per snapshot; hosts separately organize aggregation across multiple main Runs.

## Fields and completeness

- `known_usage`: known input/output/cached-input tokens in the supplied report set. `total_tokens` adds input and output without double-counting the cached subset.
- `known_model_calls`, `known_reported_usage_calls`, `known_priced_usage_calls`: known counters. Entirely unknown calls are not invented as zero calls; read these together with incomplete-Run lists.
- `pending_summary_run_ids`: summary Runs with only a started observation and no terminal report.
- `incomplete_usage_run_ids` / `incomplete_cost_run_ids`: recorded summary/main Runs with missing or incomplete usage/pricing. An entirely missing main result is separately indicated by `main_result_supplied`.
- `cost_totals`: known amounts grouped by `(currency, price_table_version)`. Different currencies or price versions are neither converted nor forcibly combined. Complete pricing may still have multiple amount groups.
- `main_stop_reason`: the main result's stop reason. Complete Usage does not imply success or execution completion: a NEEDS_APPROVAL result can have complete current usage that increases after resumption.

`SessionPreparationUsage` is an immutable snapshot; `to_dict()` returns independent JSON-compatible data. Pending, cancelled, failed or usage-incomplete summaries do not erase other known consumption and are not treated as zero-cost. Adoption status does not control accounting: a rejected summary can still incur real charges.

## Deduplication, capacity and replacement

The observer retains at most 1,024 summary Runs by default, serializing updates with a process-local async lock. Identical reports are idempotent; started can transition to a terminal report. Conflicting terminal reports or another started report after terminal state are rejected without replacing existing consumption. At capacity, new Runs are rejected while existing Runs can still finish. Used by the summarizer, rejection of its started report prevents that model invocation. Capacity bounds record count, not shared tokens or money.

`reports()` returns the latest immutable report for each Run. Hosts may use the pure `aggregate_session_preparation_usage(reports, main_result)` function with their own observers; it requires a tuple and unique Run IDs, with no collision between main and summary IDs. Only validated identity, status, counts and cost are read from the main result; its input/output/events/attempt bodies are not retained.

An unknown terminal record is not silently corrected in place. Reconcile against independent Run Store/Provider evidence, then explicitly rebuild a report set or replace the observer. Never blindly retry generation to “repair” accounting.

## Boundaries and remaining work

a9 adds separate [shared admission budget](./shared-budget.en.md) protocols, memory/SQLite controllers and a Provider wrapper for explicit summary/main-call reservations, plus host-evidence-confirmed pending/unknown reconciliation. 2.0.0a9 Experimental; see a9 release notes for validation. Report observers do not enable it automatically; SQLite budgets use a separate database, and reconciliation does not rewrite this observer's reports or main-Run results.

Hosts own correct association. The framework cannot prove that reports belong to one operation, that no report is missing, or that reported cost equals final Provider billing. Do not mistake an observer shared by multiple concurrent tasks for a single-request ledger; main-Session relationships are not inferred. The a8 default observer is memory-only and lost on exit. a9 SQLite summary-report persistence is described above and is covered by a9 scoped checks; Provider billing reconciliation is not provided.

This module aggregates only. It reserves no tokens or money before model calls, does not block uninstrumented calls and supplies no cross-process execution lock or shared hard budget. Summary/main Runs still use their own `TokenBudget` / `CostBudget`. A unified preparation/main-Run ledger and automatic Runtime/CLI/TUI aggregation/display remain planned. Custom retrieval, embedding or other preparation calls count only if the host normalizes them into the corresponding reports and includes them; third-party network calls are not automatically monitored.
