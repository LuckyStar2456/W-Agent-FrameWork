# CLI and TUI

English | [简体中文](./tui.md)

Status: `Planned`. Version 1.5.2 has only a basic `w-agent` CLI. This document defines the next-generation local development interface.

## Principles

- CLI, TUI, and Python APIs use the same Application and Registry.
- The TUI needs no W-Agent hosted service or cloud control plane.
- The interface owns no private framework capability; public Python APIs can perform every operation.
- Installing code, incurring model cost, or accessing the host requires confirmation.

## Planned CLI

```text
wagent init
wagent config validate
wagent plugins list|inspect|enable|disable
wagent profile list|resolve
wagent probe
wagent doctor
wagent run
wagent checkpoint list|resume
wagent composition export|inspect|import
wagent tui
```

The CLI prints human-readable text by default and offers structured JSON output. Failed commands return stable exit codes and never present a warning as success.

## TUI technology

The TUI uses Textual through the optional `wagent-framework[tui]` dependency. The base CLI uses Typer/Rich. The TUI starts the framework in process and requires no resident daemon; remote connections are `Reserved`.

The canonical next-generation command is `wagent`; the existing `w-agent` command remains a compatibility alias during migration.

## First-release screens

### Home

Shows the current workspace, Python and W-Agent versions, active profile, plugin errors, and recent runs.

### Models

Manages provider configuration references, model catalogs, and probe results. Before an active probe, it shows potential cost and the minimal test type that will be sent.

### Plugins

Shows source, version, API compatibility, provided capabilities, dependencies, scope, and state. Installing or upgrading a third-party package requires explicit user action; the first release does not auto-update.

### Composition

Displays a resolved profile, compares named versions, exports a code, and previews dependencies, configuration differences, and security risk during import.

### Run

Starts customer-support, coding, or custom agents and streams messages, model selection, tool calls, workflow nodes, budgets, and events. The UI projects RunEvent values and never reads private loop state.

### Checkpoints

Lists resumable workflows with creation time, definition version, plugin snapshot, and last completed node. Incompatible versions block recovery with an explanation.

### Sandbox

Shows Docker/OCI availability, images, mounts, network policy, and resource limits. Enabling `UnsafeLocalSandbox` displays a persistent risk indicator and requires explicit confirmation.

### Evaluation

Runs local customer-support and coding benchmarks and compares success rate, latency, tokens, estimated cost, and tool errors across models or composition versions.

## Security interactions

Neither a model nor imported configuration can confirm these operations for the user:

- Installing or upgrading a plugin.
- First execution of an unknown third-party plugin.
- Enabling `UnsafeLocalSandbox`.
- Relaxing Docker mounts or network policy.
- Running active capability probes that may incur model cost.

A confirmation binds to a specific operation, version, and configuration digest. A changed configuration cannot reuse an old confirmation.
