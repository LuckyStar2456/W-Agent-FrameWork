# CLI and TUI

English | [简体中文](./tui.md)

Status: the Typer/Rich CLI, launchable Textual TUI, local session lifecycle, and configured text-agent entry point are `Experimental` in `2.0.0a1`; configured tool assembly, checkpoint management, plugin operations, and evaluation remain `Planned`.

## Principles

- CLI, TUI, and Python APIs use the same Application and Registry.
- The TUI needs no W-Agent hosted service or cloud control plane.
- The interface owns no private framework capability; public Python APIs can perform every operation.
- Installing code, incurring model cost, or accessing the host requires confirmation.

## Current CLI

```text
wagent init
wagent profile list
wagent probe <endpoint>
wagent doctor
wagent composition export|inspect|save|list
wagent session create|list|show|archive|unarchive
wagent run <prompt> --confirm-model-call
wagent tui
```

These commands are implemented. The CLI prints human-readable text by default; template, initialization, probe, composition, list, and session-lifecycle commands offer structured JSON. `session show` exposes input, output, and cached-input tokens for every run and marks whether usage is complete. Failures return stable nonzero exit codes. `probe` currently performs credential-free L1 safe probing only; potentially billable active provider probes still require later configured assembly and explicit authorization.

The compatibility window retains the `w-agent` command name and basic `config` and `bean` subcommands; `wagent` is canonical.

`run` uses strict `.wagent/config.json` plus environment-variable credential references and requires `--confirm-model-call` every time. Configured tool selection, `config validate`, plugin operations, checkpoint management, and composition install/load confirmation remain `Planned`.

## TUI technology

The TUI uses Textual through the optional `wagent-framework[tui]` dependency. The base CLI uses Typer/Rich. The TUI starts the framework in process and requires no resident daemon; remote connections are `Reserved`. The current UI has ten sections plus real session create/list/archive/unarchive controls, offline composition inspection, safe endpoint probing, template information, and Docker availability checks. Sections without runtime operations state that they are planned instead of presenting placeholders as functional controls.

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

The current screen can read strict local configuration, start a text agent, and show final output plus input/output tokens. The user must type `RUN` before a model call. Tool selection, approval resume, and live RunEvent streaming remain `Planned`; the later UI projects RunEvent values and never reads private loop state.

### Sessions

Creates, lists, archives, and unarchives local sessions through the same `JsonSessionStore` used by the Python API. The list shows run count and cumulative tokens; starting a configured agent remains later work for the Run screen.

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
