# CLI and TUI

English | [简体中文](./tui.md)

Status: the Typer/Rich CLI, launchable Textual TUI, local session lifecycle, configured-agent entry point, token/cost visibility, prompt-free agent-checkpoint listing, CLI tool selection/authority/approval resume, and CLI/TUI local evaluation are `Experimental` in current `2.0.0a2`; TUI tool-approval execution, workflow-checkpoint aggregation, and general plugin operations remain `Planned`.

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
wagent checkpoint list [--session <id>]
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent run <prompt> --confirm-model-call
wagent run-resume <session-id> <run-id> --approve-tool-call <call-id> --confirm-model-call
wagent evaluate <cases.json> --confirm-model-call [--report <report.json>]
wagent tui
```

These commands are implemented. The CLI prints human-readable text by default; template, initialization, probe, composition, list, session-lifecycle, and evaluation commands offer structured JSON. `session show` and `evaluate` expose input, output, and cached-input tokens plus versioned cost when available, and mark whether metering is complete. Evaluation uses disposable state by default, and reports omit prompts and outputs by default. Failures return stable nonzero exit codes. `probe` performs credential-free L1 probing; `provider-probe` assembles a provider from strict configuration and requires the additional `--confirm-active-probe` flag for active mode.

The compatibility window retains the `w-agent` command name and basic `config` and `bean` subcommands; `wagent` is canonical.

`run` uses strict `.wagent/config.json` plus environment-variable credential references and requires `--confirm-model-call` every time. Optional versioned pricing exposes cost and completeness in CLI/TUI runs, sessions, checkpoints, and evaluation. Configuration may select from an explicit tool catalog. The CLI imports developer Python tools only when `--tool-entry` and independent `--confirm-tool-code` are both present, while `--grant-permission` grants authority for that command. `checkpoint list` discovers prompt-free agent approval points; `run-resume` then requires exact `--approve-tool-call` values. The TUI Models screen also exposes configured safe/active provider probes; active generation requires typing `ACTIVE`, and confirmation is never retained. `config validate`, workflow-checkpoint aggregation, general plugin operations, and composition-install confirmation remain `Planned`.

The TUI Evaluation screen requires typing `EVALUATE` before sequentially running a strict JSON dataset. It uses disposable state, clears confirmation immediately, displays only token/cost/latency/tool/pass metrics, and may write a default privacy-safe report. Custom scorers, output persistence, and developer tool entries use the Python API/CLI.

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

The current screen can read strict local configuration, start a text agent, and show final output, input/output tokens, and versioned cost. The user must type `RUN` before a model call. The TUI does not import developer Python tools. Tool selection, approval resume, and live RunEvent streaming remain `Planned`; the later UI projects RunEvent values and never reads private loop state.

### Sessions

Creates, lists, archives, and unarchives local sessions through the same `JsonSessionStore` used by the Python API. Details show run count, cumulative tokens, and aggregate cost when table version and currency match; configured agents start from the Run screen.

### Checkpoints

The current screen refreshes prompt-free local agent approval checkpoints with run/session, status, tool name, call ID, argument names, tokens, and cost, but no prompts, argument values, or output. Unified workflow-checkpoint listing, version comparison, and guided recovery remain `Planned`.

### Sandbox

Shows Docker/OCI availability, images, mounts, network policy, and resource limits. Enabling `UnsafeLocalSandbox` displays a persistent risk indicator and requires explicit confirmation.

### Evaluation

Runs local customer-support and coding benchmarks and compares success rate, latency, tokens, estimated cost, and tool errors across models or composition versions.

## Security interactions

Neither a model nor imported configuration can confirm these operations for the user:

- Installing or upgrading a plugin.
- First execution of an unknown third-party plugin.
- Importing and executing a developer Python tool entry.
- Enabling `UnsafeLocalSandbox`.
- Relaxing Docker mounts or network policy.
- Running active capability probes that may incur model cost.

A confirmation binds to a specific operation, version, and configuration digest. A changed configuration cannot reuse an old confirmation.
