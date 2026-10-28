# Shared admission budgets for summaries and main Agents

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./shared-budget.md)

Status: `2.0.0a9 Experimental`. See [a9 release notes](./releases/2.0.0a9.en.md) for scoped validation and limitations. No live paid models were called; this does not establish final vendor billing or cross-platform guarantees.

## Purpose and assembly

`SharedBudgetController` is a replaceable reservation/settlement protocol; `InMemorySharedBudget` is a single-event-loop template and `SQLiteSharedBudget` is an explicitly initialized local durable template. `SharedBudgetModelProvider` decorates a standard streaming Provider and reserves before each attempt. Summary and main-Agent Loops using wrappers bound to the same budget share input/output/total token and optional monetary limits without replacing Agent templates.

```python
from w_agent import (
    InMemorySharedBudget, SharedBudgetLimits, SharedBudgetAmount,
    SharedBudgetModelProvider, ModelRegistry, TokenUsage,
)

ledger = InMemorySharedBudget(SharedBudgetLimits(max_total_tokens=20000))

class HostMeter:
    async def bound(self, request):
        # Host function covering all billable input of the routed request.
        upper = await application_input_upper_bound(request)
        return SharedBudgetAmount(TokenUsage(upper, request.max_output_tokens))

    async def actual(self, request, usage):
        return SharedBudgetAmount(usage)  # Preserve Provider-reported tokens.

models = ModelRegistry()
models.register("provider", SharedBudgetModelProvider(provider, ledger, HostMeter()))
# Assemble summary/main ModelExecutors with models; wrap every fallback route too.
# The host implements/authorizes the upper-bound function and owns the Provider lifecycle.
view = await ledger.snapshot()
```

This is not a bundled vendor tokenizer. Hosts explicitly supply `SharedBudgetMeter.bound(request)` and `actual(request, usage)`. Requests require a strictly positive integer output cap, covered by the output reservation. Meters must not recursively invoke paid models. Input bounds must cover applicable system prompts, tools, media, protocol overhead, hidden reasoning and other billable units. Character approximations are not automatically reliable upper bounds. An absolute spending guarantee cannot be claimed when a Provider offers no reliable boundary.

Monetary control uses `SharedBudgetLimits(max_cost="1.00", currency="USD", price_table_version="rates-v1")`, optionally combined with token limits. Every bound/actual amount must then include a matching `ModelCost`; hosts may reuse `PricingResolver`. Token-only controllers require cost to be `None`, not an implied zero. Hosts own correct rates; currencies/table versions are never silently converted.

## Reservation and settlement

- Admission requires known consumption plus pending/unknown reservations plus the new bound to fit every configured limit. Equality is allowed; insufficient capacity fails without queuing, shrinking requests or automatic retry.
- One async-lock critical section checks capacity and inserts each reservation. The memory template retains 10000 tickets by default, configurable from 1–100000. Terminal tombstones count toward capacity to preserve deduplication; no automatic eviction is provided.
- Complete successful streams must report Usage, and meters may not change those token counts. The wrapper forwards `FinishEvent` only after EOF, protocol validation, source closure and settlement. Content still streams and cannot be retracted.
- Known actual consumption replaces the reservation. Equal settlement is idempotent; conflicting settlement fails. Exceeding any reservation component preserves actual usage, latches a breach, rejects normal completion and blocks future admissions. It cannot retroactively erase charges.
- Failure, missing Usage, cancellation, early closure or pricing failure attempts an unknown settlement, retains the whole reservation and blocks new admissions. No refund is inferred without evidence, even when a failed call might have been free. Already-admitted calls are not forcibly cancelled and still need settlement.
- `release()` is for calls known never to have entered the Provider; the wrapper uses it only for cancellation before that boundary. Direct host calls to release are trusted operations, not model-granted authority.
- Provider errors become prompt-free, non-retryable shared-budget errors. Built-in ModelExecutor respects that marker instead of replaying unknown-charge calls. Hosts still govern custom retry policies and bypasses.

Immutable snapshots expose entries, `known_usage`, `held_usage`, optional `known_cost`/`held_cost`, limits and breached. Cached input is an input subset, not added twice. `blocked` means unknown accounting or a breached bound, not available balance: a non-blocked ledger may still reject due to budget/ticket capacity. The ledger stores random tickets, counts, prices and optional reconciliation references, never prompts, responses, request objects or Provider keys. Hosts must not place sensitive bodies or keys in references either.

## SQLite persistence and reopening

Replace the ledger above in the host's async entry point; its parent directory must already exist:

```python
from w_agent import SQLiteSharedBudget, SharedBudgetLimits

limits = SharedBudgetLimits(max_total_tokens=20000)
ledger = SQLiteSharedBudget("./shared-budget.db", "development-v1", limits)
await ledger.initialize()
# Supply ledger to the same group of SharedBudgetModelProvider wrappers.
# Another host process can assemble the same file/budget_id and identical limits/capacity.
reopened = SQLiteSharedBudget("./shared-budget.db", "development-v1", limits)
view = await reopened.snapshot()
```

- Construction performs no database I/O. Explicit `initialize()` creates a dedicated database and binds budget configuration. Other operations never create a missing file or budget. Different `budget_id` values identify independent local ledgers, not tenants, authentication or access isolation; a new ID does not inherit an old ID's consumption.
- Admission, settlement and release read/check/write within worker-thread `BEGIN IMMEDIATE` transactions. Instances/processes using the same file coordinate through SQLite file locks. Transactions do not span model execution: this is neither a task lease nor cross-Store atomicity. Bypassing calls are not controlled, and real multi-process environment acceptance remains outstanding.
- Reopening requires identical limits, currency, price version and ticket capacity, including the monetary configuration's decimal-string representation. Lock `timeout` defaults to 1 second, must be greater than 0 and at most 60, and is not part of budget identity. Configuration/ticket versions are checked without implicit migration, limit reduction or memory fallback. Do not reuse the SQLite summary observer's database file.
- Pending/unknown reservations, settled actuals and released deduplication tombstones persist. Reads recompute totals and breaches from tickets; restarting cannot clear unknown or breached states. Ordinary settle/release cannot correct unknown entries; use explicit reconciliation below. There is no clear-and-retry shortcut.
- Each ticket JSON is bounded to 16 KiB and each budget's combined ticket JSON to 32 MiB. Default capacity is 10000 tickets, configurable from 1–100000, including terminal records. Each operation reads the entire bounded budget: this is a local development template, not a high-throughput billing system. Limits bound loaded/stored tickets and configuration, not total database disk space, database count or query scan work. No cleanup/rotation is provided.
- Invalid types, extra fields, duplicate JSON keys, price identities, ticket IDs, database identities and versions fail closed instead of turning missing/corrupt data into zero. Use trusted local files with working SQLite file locks; this is not a tamper-proof ledger or a security guarantee for network filesystems/malicious databases.
- Cancellation stops waiting for a worker, not an already-started transaction. A reservation may commit without its caller receiving the ticket ID. Reopen the snapshot and inspect pending entries; no automatic refund, expiration or model replay occurs. Storage failure does not report successful settlement and may leave the previous reservation. Fixed, prompt-free, non-retryable errors do not prove that no commit occurred.

Memory and durable backends share admission/settlement transitions. a9 focused regressions cover reopening, concurrent instances, price/config binding, unknown state, corrupt data, cancellation and Provider assembly. They do not establish cross-process crash or cross-platform acceptance.

## Explicit reconciliation: host confirmation, not automatic repair

`SharedBudgetReconciler` is an independent optional protocol. Ordinary `SharedBudgetController` gains no mandatory methods, and Provider wrappers never invoke reconciliation. Memory and SQLite templates both support:

```python
from w_agent import SharedBudgetReconciliation, SharedBudgetAmount, TokenUsage

# First stop/drain the target call and every writer; independently verify ownership and usage.
# confirmed_ticket_id comes from host verification, not guessing the first unknown ticket.
entry = next(item for item in (await ledger.snapshot()).entries
             if item.reservation.reservation_id == confirmed_ticket_id)
decision = SharedBudgetReconciliation(
    reconciliation_id="fix-001", reservation=entry.reservation,
    expected_status=entry.status, outcome="settled",
    evidence_ref="billing-record-001", actor_ref="local-developer",
    actual=SharedBudgetAmount(TokenUsage(120, 30)),  # Example: replace with evidence-backed actuals.
)
updated = await ledger.reconcile(decision, confirm_inactive=True)
assert updated.reconciliation == decision
```

- Explicit `confirm_inactive=True` is required; integer 1 or strings cannot substitute. This is the host's assertion that the ticket has no active execution/future writers, not a framework-verified lease or proof of remote completion. Coordinate shutdown across host processes; timeout or lack of new output is not proof of inactivity.
- Decisions accept only `expected_status="pending"` or `"unknown"`. Status, ticket ID and reserved amount must match the current ledger at commit. If ordinary settlement wins first, reconciliation fails; if reconciliation wins, late ordinary settlement fails without overwriting the receipt.
- `outcome="settled"` requires explicit actual usage and, for monetary budgets, matching currency/price version. `outcome="not-incurred"` with `actual=None` asserts evidence of neither accounted tokens nor costs and marks the ticket released. **Free calls with token usage** must still be settled, with zero cost where appropriate. No charge does not imply no tokens.
- `reconciliation_id` is unique within its budget. It, `evidence_ref` and `actor_ref` are 1–128-character opaque references matching `[A-Za-z0-9][A-Za-z0-9_.:-]*`, not bodies, URLs, paths, authentication or permission grants. The framework neither fetches evidence nor verifies its truth. Hosts retain evidence and own actor identity and ticket association.
- Each ticket accepts at most one final decision, retaining the original reservation, expected state, outcome, actuals and evidence/actor references. Identical decisions are idempotent; changed contents under the same ID, cross-ticket ID reuse and replacing an existing decision fail. Ordinary settled/released tickets also cannot be rewritten. This is an immutable per-ticket receipt, not a complete chronological audit log or tamper-proof evidence.
- The memory lock/SQLite write transaction stores the receipt and outcome together; failure cannot refund only while losing its receipt. SQLite checks duplicate IDs within that transaction and again on reopening. Receipts count toward existing 16 KiB ticket, 32 MiB ledger and ticket-count limits, without eviction.
- Actuals above reservations remain recorded and latch breached. Reconciliation cannot clear an existing breach or raise limits. Resolving one unknown does not resolve others; even with no unknowns remaining, insufficient capacity can still reject admission.
- SQLite tables/configuration stay at version 1. Unreconciled tickets continue using version 1; reconciled tickets use strict version 2, and readers support both shapes. Initialization does not batch-migrate/rewrite old tickets. Old implementations cannot read version 2; do not mix old writers. a9 is the first release of these formats; a8 did not ship this module.
- Cancellation/storage errors may follow a committed transaction. Reopen and inspect `entry.reconciliation`, or resubmit the identical decision after again confirming inactivity. Do not generate another ID to overwrite the result. Reconciliation never replays models or changes historical Run/Session Usage or summary reports.

a9 focused regressions cover both backends, races/idempotency, reopening, cancellation, corrupt receipts and capacity rollback. CLI/TUI supplies no reconciliation button and the framework never exposes this capability as a model tool.

## Extension points and remaining work

The framework provides a [cross-service observation ledger](./service-usage.en.md): explicit controller decorators record model/embedding actuals, with separate retrieval/rerank observers and a read-only CLI. It does not change budget formats, automatically merge Run/Session statistics, grant additional admission or complete automatic full-chain wiring.

Version 2.0.0 also includes an [embedding budget wrapper](./embeddings.en.md) covered by local regressions: `SharedBudgetTextEmbedder` uses a separate `EmbeddingBudgetMeter` to explicitly share this controller for single-text embeddings, preserving reserved/known/unknown semantics. This is outside a9 and does not initialize databases, assemble embedding configuration or automatically update main-Run/Session totals.

Replace the controller, meter, Provider or Agent Loop independently. Wrappers do not close host-owned Provider clients, only each source stream. Hidden Provider retries must be fully covered by its bound and actual reporting. Listing/resolution is unmetered and must not hide paid generation.

The wrapper does not forward `stream_with_cursor`/`resume_stream`; built-in native-cursor recovery rejects this unsupported wrapper instead of bypassing accounting. Cursor calls need a separately metered adapter. All summary/main/fallback routes must be wrapped; unwrapped calls, retrieval, embeddings and tools are not automatically charged to this ledger.

Cancellation is cooperative and cannot undo remote calls. Repeated cancellation may interrupt cleanup, leaving pending reservations held. Controller reserve/settle failures may occur after commit; hosts must inspect the ledger instead of blindly repeating generation. The in-memory ledger is lost on exit and provides no cross-process coordination or crash recovery; the SQLite template persists state. Neither backend provides automatic task association, proof of billing authenticity or automatic synchronization with the SQLite summary observer. Explicit reconciliation is not automatic cross-ledger correction.

a9 adds [named Runtime bindings](./local-runtime.en.md): configuration `shared_budget.binding` selects a host-provided `LocalSharedBudgetBinding(controller, meter)`. Runtime/Provider assembly wraps the configured Provider while retaining ownership/closure of its original client; shared SQLite is not automatically initialized. `shared_budget_snapshot()` explicitly reads pool totals, returning None without a selection. Historical Run/Session totals are unchanged. This addition is also 2.0.0a9 Experimental; see a9 validation.

CLI run/run-resume/evaluate/provider-probe and TUI Run/approval-resume/evaluation/probes now support independently authorized host budget factories and pool summaries; see [Runtime factory integration](./local-runtime.en.md). Budget code is not discovered/imported automatically and no reconciliation button is provided. This increment is 2.0.0a9 Experimental; see a9 validation.

A unified preparation/main-Run ledger, metered native cursors, persistence/multi-process validation and live upper-bound/vendor acceptance remain planned. See [usage aggregation](./context-accounting.en.md) and the [roadmap](./roadmap.en.md).

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
