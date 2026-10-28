# Explicit local plugin replacement

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./plugin-replacement.md)

Status: `Experimental`, included in 2.0.0. See the [focused record](./acceptance-2026-10-01-followup.en.md) for offline lifecycle coverage; this does not certify arbitrary third-party plugins.

`PluginManager.plan_replacement()` and `replace()` replace an **already constructed, trusted, same-name Python plugin**. Models, routers, workflows, tools and other capabilities use the same lifecycle. This does not install a package, import a module, authorize unknown code, or hot-reload Python's module cache.

```python
plan = await manager.plan_replacement(next_plugin)
print(plan.previous.version, plan.replacement.version, plan.unload_order)
# Host stops new runs, drains existing runs and relinquishes old registry snapshots.
# Obtain application/user approval of this exact preview before proceeding.
handle = await manager.replace(
    plan,
    expected_plan_id=plan.plan_id,
    host_quiescent=True,
    config={"mode": "local"},
)
```

## Contract

- Preview runs no plugin setup/unload. It exposes both `PluginSpec` objects (including provided/required capabilities) and the consumer-first unload order. The currently active plugin and replacement must have the same name; a fresh plugin instance is required. Intentional same-version replacements and downgrades are allowed.
- Preflight simulates the registry after removing affected owners, checks the kernel API, required dependencies, declared registrations and conflicts, including remaining plugins' conflicts. It cannot validate undeclared setup behavior.
- Dependency impact follows the existing conservative unload policy: any hard requirement for a declared provided capability counts, even if another provider could satisfy it. Optional dependencies are not tracked.
- A plan is process-local and bound to the exact object returned by this manager. Only the latest preview is executable. The plan ID is an approval correlation token, **not a package/code hash or security boundary against trusted Python code**. Configuration is supplied explicitly by the host at execution and is not part of the preview.
- Execution holds the manager's lifecycle lock and rejects changed plugin records/spec identities or registry contributions before teardown. The host must not mutate objects, registry entries or configuration concurrently; this is not a cross-thread/process lease or protection against malicious plugins.
- `host_quiescent=True` is a host assertion, not automatic draining. Registry snapshots and existing runs do not have lifecycle leases. The host must prevent new work, wait for active users, and stop using old provider references before approval.
- Consumers are stopped before the old provider. They **remain stopped** after success, so the host explicitly constructs/reloads compatible consumers. Unrelated plugins remain active.
- A handle remains bound to its original record. An old handle reports the original state and cannot unload the replacement by accident.

## Failure and recovery

The plan is consumed immediately before teardown. A cleanup failure stops the sequence and no replacement setup runs. Earlier consumers may already be disposed; the provider may still be active or disposed. Inspect `manager.records()` and their `error` fields before manual recovery. A new setup failure removes its registered effects and leaves its record `FAILED`; old components are not silently restarted. Setup cancellation also attempts cleanup and propagates cancellation. Cancellation during teardown may leave an intermediate lifecycle state and requires host inspection. Repeated cancellation or external side effects cannot be transactionally undone.

There is no automatic rollback, dependent reconstruction, state transfer, timeout/forced cleanup, source discovery, lock generation, package upgrade, import-cache mutation, persistent replacement audit, or run-binding migration. These remain planned. Installed package updates still require independent install/load approvals and may require a fresh process; see [plugin system](./plugin-system.en.md).

## CLI and TUI entry points

The current worktree adds `PluginReplacementSession`, a shared review controller with a single-reference YAML file:

```yaml
plugins:
  - entry: my_plugins.next_router:setup
    config:
      mode: local
```

This file must contain exactly one enabled reference. Inspection reads at most 1 MiB, shows only configuration keys, and binds subsequent actions to the SHA-256 of those bytes. This is a **configuration digest, not a Python source/artifact hash**; imported modules remain trusted developer-owned code. Edit/new import, code signing and installation remain independent responsibilities.

Open an actual current-process plugin session:

```text
wagent plugin session --config .wagent/plugins.yml --confirm-plugin-code
plugin-session: status
plugin-session: inspect .wagent/replacement.yml
plugin-session: prepare
Exact IMPORT REPLACEMENT confirmation: IMPORT REPLACEMENT <source_digest>
plugin-session: replace
Exact REPLACE confirmation: REPLACE <plan_id>
Exact QUIESCENT confirmation: QUIESCENT <plan_id>
plugin-session: status
plugin-session: exit
```

Initial code authorization loads the initial YAML only. Preparing a replacement requires its separate exact import phrase, and replacement requires both exact plan-bound phrases. Plugins remain active across commands until `exit`, EOF or interruption closes this session. `cancel` discards a pending review. This command does **not** update another process, persist a project's plugin selection, or upgrade installed packages. It is a live local manager, not a remote-process control command. Configuration values and arbitrary exception messages are not printed.

The TUI **Plugins** tab uses the same controller against its existing long-lived manager: inspect replacement → authorize import/prepare → execute with `REPLACE` and `QUIESCENT` → refresh lifecycle state. Changing the path or YAML contents requires review again. Execution attempts consume the review even if rejected. Cancel review clears its retained candidate but cannot undo Python import side effects, stop already running plugin code or unload imported modules.

The TUI rejects replacement while its Agent, Workflow, chain or evaluation work is active, and rejects an affected installed-plugin batch because its import-path leases need separate fresh-process handling. UI busy checks cover known operations only; the host's explicit quiescence assertion remains required for plugin-created background users and external references. No forced lease/draining or sandbox guarantee is added.

`PluginManager.discard_replacement(plan)` only discards the exact retained plan and cannot cancel a newer preview. Controller cancellation uses it to release pending objects. Python embedding may import `PluginReplacementSession` from `w_agent.plugin_replacement_session`.

## Acceptance

`tests/test_plugin_replacement.py` exercises preview/approval, one-shot/stale plans, changed registry/specs, consumer ordering, missing dependencies, incompatible APIs, reverse conflicts, cleanup/setup failures, cancellation, original-handle safety and explicit config forwarding. These are real local manager/registry tests, not external package upgrade or production concurrency acceptance.

The CLI/TUI integration iteration was independently tested with 15 new `tests/test_plugin_replacement_session.py` cases plus the 17 replacement and 7 lifecycle cases: **39 passed** in the isolated Python 3.11 environment. The existing CLI, TUI and package-installation regression group separately passed **61 tests**. Relevant compileall and diff checks also passed. This is scoped evidence for this iteration, not a reuse of the previous full-suite result. External package upgrades and production concurrency remain unverified.
