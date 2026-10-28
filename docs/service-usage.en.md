# Cross-service usage observations

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./service-usage.md)

Status: `Experimental` in the current worktree. This is an opt-in accounting view, **not another budget controller or a billing guarantee**. Existing `SharedBudgetController` implementations still own admission, reservation, settlement, unknown holds and reconciliation. Existing session-summary stores and shared-budget schemas are unchanged.

## Boundaries and data

`ServiceUsageRecord` identifies an explicit host-defined `operation_id`, unique `record_id`, service (`model`, `embedding`, `retrieval`, `rerank`), opaque `source_ref`, and `meter_version`. Hosts supply labels, never queries, endpoint URLs, credentials, document text or result bodies. The ledger stores only these labels, state, counters, token usage, cost groups and an optional reconciliation reference. Labels are not authorization or proof of origin.

- `started` is recorded before entering a potentially billed call. It remains unresolved after a crash.
- `completed` means the call/report finished, not that usage or prices are complete. Missing values stay `None`; partial known totals have false completeness flags.
- `unknown` is not zero. `not-incurred` asserts that no counted consumption occurred, normally from an existing released reservation.
- `token_scope="expected"` is the default. A host may explicitly choose `"not-applicable"` for a non-token service. That excludes the token dimension, not its unknown monetary cost. Local BM25 is not automatically priced at zero.
- Non-token units are `ServiceUsageUnit(name, count)` with an explicit meter version. Aggregation isolates them by service/source/meter/unit. Monetary totals are isolated by currency and price-table version with no FX conversion.
- Costs reuse `ModelCost`; retrieval per-request charges may use a host-declared convention in its components. No built-in provider prices or automatic cost inference are added. Components are bounded to 28 digits and exponents within ±28; aggregation uses a bounded high-precision Decimal context.

Identical observations are idempotent. Changed identities and conflicting terminal reports fail. `started` may advance once to a terminal observation. Changing `unknown` to known requires an explicit `reconciliation_ref`; this must come from host-reviewed evidence, not a guessed retry result. The current-state ledger is not an immutable audit-history store.

## Reuse the existing budget

```python
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger
from w_agent.service_usage_adapters import ObservedSharedBudgetController
from w_agent.shared_budget_provider import SharedBudgetModelProvider
from w_agent.embedding_budget import SharedBudgetTextEmbedder

ledger = SQLiteServiceUsageLedger(".wagent/service-usage.sqlite")
await ledger.initialize(confirm_create=True)  # existing parent directory required
model_observer = ObservedSharedBudgetController(
    shared_budget, ledger, operation_id="run-chain-42", service="model",
    source_ref="model-route-a", meter_version="pricing-2026-10",
)
embedding_observer = ObservedSharedBudgetController(
    shared_budget, ledger, operation_id="run-chain-42", service="embedding",
    source_ref="embedding-a", meter_version="pricing-2026-10",
)
model = SharedBudgetModelProvider(model_provider, model_observer, model_meter)
embedder = SharedBudgetTextEmbedder(embedding_provider, embedding_observer, embedding_meter)
```

`shared_budget`, providers and trusted meters above are host-supplied existing components. Both observers share the **same underlying budget**. The reservation ID becomes the observation identity, and reservations are never counted as actual consumption. The observer does not own or close provider clients.

If the initial observation fails, the provider is not entered and reservation release is attempted. If the underlying settlement succeeds but the observation write fails, the in-process decorator retains the settled truth **before** attempting the write. Cleanup's subsequent `settle(None)` only reflushed that truth; it cannot downgrade it or settle the underlying budget twice. Errors are non-retryable accounting failures. After cancellation/crash, inspect both stores: they are not atomically committed together. A pending observation must never authorize repeating a paid call.

For recovery, read the underlying budget's authoritative snapshot and explicitly project the matching entry using `service_usage_from_budget_entry(...)`, preserving its recorded operation/service/source/meter association. An existing budget reconciliation carries its reconciliation ID into the observation. This operation records evidence; it makes no service call and does not reconcile the budget itself.

## Retrieval and reranking

`ObservedKnowledgeRetriever` and `ObservedKnowledgeReranker` implement the existing retrieve/rerank methods. Supply the underlying component, ledger, operation/source/meter labels, optional `measurement(result) -> ServiceUsageMeasurement`, and explicit token applicability. The result callback may supply actual provider reports, unit counts or host-known prices; it is trusted code and must not make hidden paid calls. Without a callback, usage/cost remain unknown. Query and returned documents never enter the record.

`observe_service_call()` provides the same started-before-call and terminal observation sequence for another explicit integration. It never reserves budget, invents rates, retries a call or persists input/output bodies. Existing budget wrappers can remain inside the observed service when applicable; do not also record their same consumption at another accounting boundary.

## Aggregation and avoiding duplicates

```python
from w_agent.service_usage import aggregate_service_usage

summary = aggregate_service_usage(await ledger.records("run-chain-42"))
```

The summary exposes known token totals, cost groups, isolated unit totals, incomplete record IDs and unresolved IDs. An empty ledger is not declared complete. Completeness covers **supplied records only**, never uninstrumented calls or an entire application.

Choose either model attempt observations **or** `service_usage_from_run(..., confirm_final=True)` for one operation. Mixing run/attempt granularity for the same service is rejected. Run import rejects `NEEDS_APPROVAL` and requires a host assertion that the result will not be resumed. It is a final cumulative result, not an increment; replay is idempotent and changed terminal totals conflict. Use attempt-level observation for active/resumable Runs. Do not record both a composite service's charge and its paid children; arbitrary overlapping host boundaries cannot be inferred automatically.

`ServiceUsageLedger` is replaceable; `InMemoryServiceUsageLedger` is process-local, while `SQLiteServiceUsageLedger` requires explicit initialization, rejects foreign schemas and mismatched capacity, serializes updates and capacity checks, and rejects conflicting concurrent terminal writes. SQLite stores plaintext observations, not encrypted/authenticated billing receipts. Cancellation drains started SQLite work and may follow a committed write. No migrations, pruning or parent-directory creation occur automatically.

The read-only CLI is:

```text
wagent service-usage --database .wagent/service-usage.sqlite --operation run-chain-42 --confirm-read
```

Use the same `--max-records` as initialization if it differs from the default 10000. This command does not initialize the database, execute plugin code or call a service.

## Evidence and remaining work

This iteration's 21 new service-usage cases and adjacent shared-budget, embedding-budget and session-usage tests passed together: **85 passed** in isolated Python 3.11. The root integration test additionally exercises four service types with reopened SQLite budget/usage stores; refer to the current acceptance report for its combined count. This is scoped evidence, not an external billing reconciliation or full-suite claim.

Later increments add [Runtime/CLI/TUI observation](./service-usage-runtime.en.md) and [optional durable links/read-only queries](./service-usage-links.en.md). `service-usage --run R --links-database ...` resolves the link but still aggregates the entire operation, never claiming exclusive per-Run usage. Remaining: attribution of individual service/preparation observations, complete automatic coverage, vendor retrieval/rerank billing, immutable audit history, correction workflows and invoice verification. There is no automatic global service budget, external price fetch or multi-tenant platform.
