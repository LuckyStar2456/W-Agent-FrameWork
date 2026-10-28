# Run / Session service-usage links

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](service-usage-links.md)

This is optional local host correlation, not tenancy or per-Run billing. `ServiceUsageRunLink(session_id, run_id, operation_id)` stores three bounded identifiers only: no prompts, tool arguments, evidence, endpoints, prices or usage-record contents.

## Explicit assembly

```python
from pathlib import Path
from w_agent.service_usage_links import SQLiteServiceUsageLinkStore
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger

async def prepare_binding():
    # Initialize only after host authorization to create/write local databases.
    # Reopening an existing database does not require initialization.
    # The user creates the .wagent parent first. These are two independent creates.
    ledger = SQLiteServiceUsageLedger(Path(".wagent/service-usage.sqlite3"))
    links = SQLiteServiceUsageLinkStore(Path(".wagent/service-usage-links.sqlite3"))
    await ledger.initialize(confirm_create=True)
    await links.initialize(confirm_create=True)
    return LocalServiceUsageBinding(ledger, "my-operation-v1", links=links)

# Supply service_usage_bindings={"observations": binding} to Runtime assembly;
# configuration only selects service_usage.binding = "observations".
```

The compatible default `links=None` neither creates nor reads a links database. Configuration selects a named binding, not host code or database paths. Putting a store in an authorized binding authorizes Runtime to write new-Run associations; CLI/TUI still require separate code-loading and recording confirmations. Runtime borrows the store: it does not initialize, delete or close host resources.

Adapt [examples/service_usage_host.py](../examples/service_usage_host.py): it borrows the two already-initialized databases, without creating them on import/factory entry. Its binding name is `local-usage` and entry is `examples.service_usage_host:usage_factory`. Set required `WAGENT_USAGE_OPERATION` and optional `WAGENT_USAGE_ROOT` (default `.wagent`). Select `service_usage.binding = "local-usage"`, with separate `--confirm-usage-code` and `--confirm-usage-recording` approvals. Resume must reuse the original operation label and links database, not generate a fresh label.

## Lifecycle and failures

A new Run creates/loads the Session, generates its Run ID, and calls `bind(..., confirm_write=True)` before history projection, knowledge retrieval, or the model/tool loop. This makes preparation and retrieval failures discoverable. A failed link or task cancellation does not continue into the model. Already-started SQLite workers drain before cancellation propagates.

Preassociation can leave an orphan: it does not prove a Run started, completed, appeared in the Session Run list, or incurred costs. Session storage, links and usage ledger are not a cross-database atomic transaction. After cancellation, inspect storage rather than assuming the write did not happen.

When resuming a persisted approval checkpoint with links enabled, Runtime reads the original link before claiming the checkpoint or executing a tool/model. Run, Session and operation must match exactly. Missing/conflicting links or failed reads reject the resume; historical Runs are never silently adopted. Reopening the correct binding still permits resume. Calls with no links retain their previous behavior.

This check only constrains participating hosts using the same trusted store. It is not a sandbox against a host disabling observation, replacing a database, or modifying its contents. Historical migration/adoption requires separate host review and authorization; the framework does not infer ownership from prompts.

## Replaceable protocol and queries

`ServiceUsageLinkStore` defines asynchronous `bind(link, *, confirm_write=False)`, `get(run_id)`, `for_session(session_id)` and `for_operation(operation_id)`. `get` returns a link or `None`; list queries return a run_id-sorted tuple without silent truncation. `InMemoryServiceUsageLinkStore` and `SQLiteServiceUsageLinkStore` share semantics: identical bindings are idempotent; changing a Run's Session or operation is rejected. There is no overwrite/delete API.

`max_links` defaults to 10000 and accepts 1–100000. SQLite persists that capacity and reopening must use the same value. Capacity exhaustion rejects new links rather than silently evicting history. SQLite uses a dedicated database, strict schema/version checks, read-only query connections, bound parameters, bounded field reads and transactional writes. Reads/binds never auto-create. `initialize(confirm_create=True)` rejects existing foreign schemas. Database paths are trusted host input, not a filesystem sandbox.

```python
links = SQLiteServiceUsageLinkStore(Path("usage-links.db"))
link = await links.get("run-example")  # None when absent
related = await links.for_session("session-example")
```

Offline CLI queries require no Provider or host factory:

```text
w-agent service-usage-link --links-database usage-links.db --run run-example --confirm-read
w-agent service-usage-link --links-database usage-links.db --session session-example --confirm-read
w-agent service-usage-link --links-database usage-links.db --operation my-operation-v1 --confirm-read
```

Exactly one selector is required. A custom capacity needs `--max-links` matching initialization. `service-usage` can resolve a Run's operation before reading its aggregate:

```text
w-agent service-usage --database usage.db --run run-example --links-database usage-links.db --confirm-read
```

The result explicitly includes `resolved_link`, `association_only`, `run_state=not-inferred` and still uses `scope=host-operation-not-this-run`. For a nondefault ledger capacity, also supply the matching `--max-records`. Replace example paths with the host's actual databases.

## Accounting scope

Many Runs may map to one operation. Preparation, other Runs and host-supplied records can share that operation. A Run lookup still returns a `host-operation-not-this-run` aggregate: do not add these repeated totals together. Correlation is not record-level attribution. Arbitrary externally invoked services do not acquire Run labels automatically; operations without a Run, such as Provider probes, do not create links.

Implemented: correlation and reopened queries. Reserved: per-attempt Run attribution, automatic pricing, cross-database atomicity, link deletion/migration tools, and tamper-proof auditing.
