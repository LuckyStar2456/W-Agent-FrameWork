# Named cross-service usage observation in Runtime

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](service-usage-runtime.md)

Status: worktree Experimental. Configuration selects a host-supplied observation binding; JSON never imports Python, opens databases, creates budgets or guesses prices. Observation and admission control are separate concerns.

## Assembly API

```python
from w_agent.local_runtime import assemble_local_runtime, local_runtime_config_from_mapping
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding

ledger = InMemoryServiceUsageLedger()
binding = LocalServiceUsageBinding(
    ledger, operation_id="local-development-operation",
    model_source_ref="main-model", meter_version="host-v1",
    # None (default) does not observe retrieval; this opts into the whole call.
    retrieval_source_ref="knowledge-search",
    retrieval_token_scope="not-applicable",  # only if the host confirms no token accounting
)
config = local_runtime_config_from_mapping({
    "provider": {"template": "ollama", "model": "host-selected-model"},
    "service_usage": {"binding": "usage"},
})
runtime = assemble_local_runtime(config, service_usage_bindings={"usage": binding})
```

This shows assembly, not a request. Retrieval still needs the existing `knowledge.binding`, borrowed `knowledge_bindings`, and independent per-call query consent. `assemble_local_provider` also accepts `service_usage_bindings` for real probes/evaluation, without requiring manual controller decoration.

Bindings borrow a replaceable `ServiceUsageLedger`. Runtime never initializes, closes or reconciles the host ledger. SQLite directory/creation/lifecycle remain explicit host responsibilities. An optional `retrieval_measurement(result)` returns `ServiceUsageMeasurement` with independently reported cost/units. Missing measurements are unknown, not zero.

## Correlation and visibility

`operation_id` is a bounded, host-selected local label, not a tenant, credential, query, endpoint or automatically a Run ID. One binding may span Runs. `run`, `run_messages` and `resume` return `LocalRuntimeRun.service_usage_operation_id`. Optional `LocalServiceUsageBinding.links` persists Run/Session correlation before preparation and rejects missing/conflicting links during resume; it is disabled by default. See [links and reopened queries](service-usage-links.en.md). Correlation does not turn operation totals into per-Run accounting.

`await runtime.service_usage_summary()`, or `_service_usage_ui.service_usage_summary(binding)` before factory cleanup, returns a safe `scope=host-operation-not-this-run` report: observed calls, service counts, known token subtotals, costs separated by currency/price-table version, and incomplete/unresolved counts. It exposes no record IDs, source labels, evidence references or bodies. Read failure returns `status=unavailable`, without invalidating a completed Run or authorizing replay.

Existing model-only `RunResult.usage` / `cost` semantics are unchanged; retrieval tokens are not merged into them. Completeness covers supplied observation records, not arbitrary host code, tool-internal services, compression models or unwrapped children. `runtime_observers` describes configured model and optional whole-retrieval observation, not system-wide coverage.

## Model and shared-budget combination

- Without shared budgets, `ObservedModelProvider` creates an independent attempt per actual `stream`. It persists started before entering the provider, validates the complete stream/EOF, closes the inner stream and records completion before delivering Finish. Repeated Usage events use the final cumulative report, not their sum.
- A successful stream without Usage has unknown tokens, never a known zero. Interruptions, invalid streams, failures and early close record unknown. Cancellation definitely before provider entry may record not-incurred. Failed physical attempts and subsequent normal retries are separate. Observation adds no retry policy.
- No shared budget means no automatic pricing or assumption that image/audio/other billable units are complete; costs and additional units remain unknown.
- With `shared_budget.binding`, Runtime decorates the **same** controller using `ObservedSharedBudgetController`, preserving reservation ID and actual settle/unknown/release instead of adding another model observer. There is one reservation, existing meter costs/admission are preserved, and `runtime.shared_budget` still exposes the original pool-level binding/snapshot.
- Known duplicate decorators (already-observed controller/retriever or wrapped provider) are rejected. Arbitrary nested host wrappers cannot be generally detected. Do not count a composite retriever and the same-cost child services twice.

Runtime closes its original Provider once; ledger, meter and retriever remain host-owned. Combining `service_usage` with native cursor recovery is explicitly rejected for now, never silently bypassing observation. Observation-write failures are non-retryable. Budget and usage stores are not atomically joined and may need separate inspection.

## CLI/TUI factory protocol

`ServiceUsageOptions(entry, confirm_code, confirm_record)` performs pure preflight. Import requires independent `LOAD USAGE` / `RECORD USAGE` authorization and a configured `service_usage.binding`.

```python
from contextlib import asynccontextmanager
from w_agent.service_usage import InMemoryServiceUsageLedger
from w_agent.service_usage_runtime import LocalServiceUsageBinding

@asynccontextmanager
async def usage_factory():
    yield {"usage": LocalServiceUsageBinding(InMemoryServiceUsageLedger(), "explicit-operation")}
```

Frontends borrow the catalog through `service_usage_binding_scope(entry, selected=..., confirmed=True, confirm_record=True)`. Hosts are explicitly authorized unsandboxed Python, not isolated code. Factory exit cannot suppress Runtime errors. Cleanup failures warn that work may have completed and must not be replayed.

CLI `run`, `run-resume`, `evaluate` and `provider-probe` accept `--usage-entry host_module:usage_factory --confirm-usage-code --confirm-usage-recording`, with `service_usage.binding` selected in configuration. The corresponding TUI Run, Resume, Evaluation and Provider probe areas each provide a factory entry and single-action `LOAD USAGE` / `RECORD USAGE` confirmations. Observation does not replace other model/retrieval/tool/live-probe authority. A factory operation may aggregate multiple evaluation cases; it is not per-case usage.

## Verification and reserved work

Focused tests use real reopened SQLite ledgers and deterministic providers/retrievers: configuration preflight, no-I/O assembly, two Runs sharing an operation, one shared reservation, independent retrieval, missing/repeated Usage, retry attempts, early close, observation failure withholding Finish, safe reports and factory consent/cleanup. No paid models or external services are called.

Reserved: per-attempt Run attribution, native-cursor observation/recovery, automatic coverage of arbitrary tool internals/composite children, vendor auto-pricing and cross-database atomic budget/usage writes. None is claimed implemented or completely covered.
