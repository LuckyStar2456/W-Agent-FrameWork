# CLI and TUI

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./tui.md)

Unpublished M4 adds `wagent application run` and the TUI Application page for the same custom `ApplicationProject`. Default Run/Resume/Evaluation and ordinary Workflow recovery also use the public container Host. Project import/execution requires explicit unsandboxed-Python authorization; see [unified assembly](./default-assembly.en.md) for usage and 572 passing stage cases.

Available in 2.0.0: [durable Run/Session usage links](./service-usage-links.en.md), [structural/overlapping splitting](./knowledge-splitting.en.md) and [raw-archive CLI entries](./knowledge-archive-entries.en.md). Links precede preparation, default splitting preserves v1, and export only creates new files. All are Experimental features included in 2.0.0; see [acceptance and remaining modules](./acceptance-2026-10-01-links-splitting-archives.en.md).

Run, approval resume, Evaluation and Provider probe expose Usage host with independent one-shot `LOAD USAGE` / `RECORD USAGE` confirmation. Nothing loads or records by default; display failure never retries a model.

The framework provides a [Knowledge sync tab](./knowledge-sync-tui.en.md): default UTF-8 / explicit four-format import previews, digest-locked saves, delta-plan preparation, inspection and separately approved execution using the CLI's management service. See [previous entry acceptance](./acceptance-2026-10-01-sync-usage.en.md) and [this format/usage increment](./acceptance-2026-10-01-http-archives-runtime.en.md); manual live-service scenarios remain unaccepted.

Follow-up worktree additions: [Replay media previews/exports](./tui-media.en.md), [explicit Plugins replacement](./plugin-replacement.en.md) and [per-case knowledge Evaluation](./knowledge-workflow-evaluation.en.md). Local/headless focused acceptance is in the [follow-up record](./acceptance-2026-10-01-followup.en.md), not manual-terminal or production acceptance.

[Full builds](./knowledge-builds.en.md) have create/review/single-batch execution CLI and a separate `Knowledge builds` TUI tab. Execution independently approves build/artifact digests, host code, reads, remote writes and journal recording; it never executes all batches automatically. Worktree local and headless TUI regressions pass, included in 2.0.0 and outside a9.

Worktree [plan catalogs/coverage](./knowledge-plan-catalog.en.md) adds List plans and coverage in Index plans with `READ PLAN` and optional manifest filtering; `SHOW TARGET` separately discloses targets/point IDs. The same tab now has Suggest missing batches: `READ BATCH INPUTS` reads exact snapshots/plans for advice with adjustable bounds; `SHOW BATCH IDS` separately discloses document/point IDs. No host loading or automatic preparation. UI is unaccepted.

Worktree [Index plans and CLI](./knowledge-plan-actions.en.md) now has inspection, prepare-save and approved-execute actions. Code/read/embed/save/create/overwrite/receipt consent is separate and approval digests are independently entered. No automatic preview approval/execution. Local regressions pass; included in 2.0.0 and outside a9.

The worktree also has [Index journal and CLI](./knowledge-index-management.en.md): exact-manifest local review and host-evidence reconciliation with separate read/write/no-late-effects/detail consent. No remote probe or resend. Local regressions pass; included in 2.0.0 and outside a9.

The framework provides a [Knowledge management tab and CLI](./knowledge-management.en.md): local import preview/explicit save, version catalog and pinned keyword search with independent read/write/create/body-display consent. Local and headless TUI regressions pass, included in 2.0.0 and outside a9.

Separate [Run knowledge context](./knowledge-runtime.en.md) supports Knowledge host, explicit query and per-attempt LOAD KNOWLEDGE / QUERY KNOWLEDGE consent. history=none supports knowledge-only context; fields are captured/locked during runs. Management never automatically selects Run versions or sends knowledge to models. Included in the 2.0.0 release; see the topic for named assembly and local UI regressions, not live-service acceptance.

a8/a9 additions on this page are Experimental; see [a9 release notes](./releases/2.0.0a9.en.md) for validation scope.

## Shared-budget entry (2.0.0a9 Experimental)

Run and Checkpoints approval-resume forms add `Budget host`, accepting `module:factory`. Enter `LOAD BUDGET` for each attempt to authorize unsandboxed host Python. Configuration `shared_budget.binding` selects the factory's catalog entry. Model execution still requires `RUN`/`RESUME`; tool imports and permissions remain separate. Budget confirmation is consumed per attempt, and Run captures/locks the entry with its request.

A separate post-run panel shows shared-pool input/output/cached tokens, known/held amounts, limits and status counts. It omits ticket IDs/evidence and never merges into current Run usage. Read failure displays unavailable, not zero, and never replays models. Factories own budget-resource initialization/cleanup. Cleanup may fail after a model already ran, requiring ledger inspection. Matching CLI `run`/`run-resume` flags are `--budget-entry` and `--confirm-budget-code`.

See [local Runtime](./local-runtime.en.md) for a factory example, persistent-pool reopening and authorization boundaries. Evaluation and configured Models probes also load budget factories, retaining EVALUATE / ACTIVE consent. Safe probes do not generate but still require factory-code consent. Missing bindings fail closed. One factory spans an evaluation batch and saved reports remain unchanged. See a9 release notes for validation.

## Run media input and history policies (2.0.0a7 Experimental)

a8 also adds message-field checkboxes (2.0.0a8 Experimental; focused regressions passed): permit input-file name/metadata sending, independently record names/metadata, and independently reuse historical names/metadata. All default off. Recording requires field input and input recording; history fields require recorded mode. Existing `RUN`, `RECORD INPUTS` and `SEND HISTORY` confirmations apply. Selections are captured for each attempt and locked during execution without changing shared recorder defaults. Replay display never authorizes sending. Input fields have size and finite-JSON validation; see [field run options](./local-runtime.en.md). Focused regressions passed.

a8 adds `retrieved` / `summarized` text-history templates, 2.0.0a8 Experimental; focused regressions passed. Run fields expose an explicit query, recent/retrieved segment counts, summary-character limit and output-byte limit; leave unused numeric fields blank. Both templates require per-attempt `TRANSFORM HISTORY`, accepting lossy context selection/summarization without granting media reuse. Every attempt consumes all five confirmations; new fields participate in request capture, execution locking and cancellation cleanup. Queries are not inferred from Prompt and errors omit query values; irrelevant mode-specific fields are rejected. See [local Runtime](./local-runtime.en.md) for examples and defaults. Existing media entry and its a7 validation boundaries follow.

The Run form accepts either Prompt or an input file, never both. Files use the [CLI structured input format](./local-runtime.en.md); relative paths use the workspace. Only user-message text/image/audio blocks are accepted, with no implicit URL download.

- Enter `RUN` for each invocation; loading tools independently requires `LOAD TOOLS`.
- `Record current input blocks` defaults off; enabling it additionally requires `RECORD INPUTS`.
- History accepts `text` (default), `recorded` or `none`. Resending recorded media requires `SEND HISTORY`. Display, recording and sending are independent decisions.
- a7 consumes four confirmations per attempt; a8 consumes five including transformation consent, even on rejection. File reads, tool imports and Runtime assembly follow authorization. An immutable request is captured, the form is locked and duplicate submissions are rejected during background execution.
- `Request cancellation` requests cancellation. Cancellation or exit cleans up Runtime without automatic replay; completed model calls and tool side effects are not rolled back. A parser thread may finish read-only work, but cancellation prevents subsequent dispatch. Synchronous user code may still block the UI; a worker is not a sandbox.

The live event view retains the latest 200 safe projections without changing persisted logs. `record_inputs=False` does not disable checkpoints or other logs. Large-character/emoticon branding and narrow-window fallback remain unchanged. See [a7 release notes](./releases/2.0.0a7.en.md) for validation scope.

## Read-only rich Replay page (2.0.0a7; focused regressions passed)

a8 adds `Recorded input names` / `Recorded input metadata` checkboxes (2.0.0a8 Experimental; focused regressions passed), for Session mode only. Both default off; either requires per-read `VIEW CONTENT`. Confirmation is consumed before reading and fields are locked during work. Changing either switch clears displayed content and memory snapshots, also discarding older in-flight delivery. Display never enables persistence or model reuse. Input-media selection independently controls content; wrapped records can expose block metadata while fields remain hidden. CLI/TUI share projector assembly, with field settings included in snapshot identity; see [input-message field disclosure](./event-replay.en.md). Focused regressions passed.

a7 adds a twelfth `Replay` section, separate from the existing safe Checkpoints event list. Large-character/emoticon welcome branding is unchanged. The panel uses public `RunEventAccumulator` / `SessionEventReplay` APIs without loading developer code, invoking models, executing tools, approving recovery or downloading media.

1. Enter `run` / `session`, an exact ID and the Run State Root; Session mode also uses Session Root. Relative paths are based on the TUI workspace; reads require existing directories.
2. Defaults expose counts, status and media metadata only. Model text, tool identities/arguments, recorded tool results and Session text have independent checkboxes; media supports `metadata` / `references` / `content`. Every read disclosing bodies, references or inline media requires `VIEW CONTENT`. The confirmation is cleared when capturing the request, never saved as authority.
3. Click `Read next batch`. Run pages accept 1–500 events. Session batches accept 1–32 members and 1–500 events per Run. Success advances the in-memory snapshot. Session offset moves to the next member batch, or zero at the end; another explicit click can refresh appended events in older Runs. End-of-sweep or zero pending views does not establish Agent completion.
4. `Previous/Next display slice` navigates already-authorized in-memory content, up to 16,000 characters per slice, without reading events. Display is structured JSON text with controls and non-ASCII escaped, never Rich/ANSI interpretation, image rendering, audio playback or URL opening. Missing historical tool bodies cannot be reconstructed.
5. `Clear view` drops the snapshot, visible body and confirmation. Changing sources, ID, kind or disclosure settings also clears the view. Failures retain the prior snapshot without partial advancement. In-flight results arriving after Clear are discarded. Switching tabs does not clear automatically; use Clear before leaving if needed.

Reads and projection run in a separate read-only worker thread. Forms are temporarily locked and duplicate clicks cannot start concurrent reads; Clear remains available and fields unlock afterward. Exit discards delivery and snapshots, but a thread already inside a store read may finish; cancellation does not forcibly terminate I/O. Clearing releases display references, not secure memory erasure.

a7 snapshots are memory-only within the TUI session; cross-process continuation uses the [accumulated-view CLI](./event-replay.en.md). a8 adds cache actions described below. Limits are 8 / 32 MiB per Run / Session snapshot and 64 MiB for escaped display. Stores may still load full Sessions and scan log prefixes; these are not total I/O or memory sandboxes. `Legacy events` only permits missing Session IDs, never another Session's events. Input recording is available through Python [Session schema 2](./sessions.en.md) in 2.0.0a7 with focused regressions passing; Replay has independent Session input media selection (default off; metadata/references/content), requiring per-read VIEW CONTENT for references/content. TUI media entry and history selection use the Run form above; dedicated media players remain unimplemented. See a7 release notes for validation scope.

### a8 cache import/export (2.0.0a8 Experimental; focused regressions passed)

Replay adds a cache-path input and two explicit actions, without automatic saving, Python loading, model/tool calls or media downloads.

1. For import, manually select the same kind, ID, stores and disclosure settings, then enter the cache path, `VIEW CONTENT` and `TRUST CACHE`. `Import + read batch` loads the existing CLI/TUI JSON envelope, checks source binding, ID, reducer/message projection and limits, and reads one further batch. This is not offline viewing: source stores must be available. Membership offset comes from the explicit form value, never automatically from cached page metadata; zero can rescan existing members.
2. For export, first read a snapshot, enter a new `.json` path, `VIEW CONTENT` and `SAVE CACHE`, then choose `Export current snapshot`. This only serializes the captured snapshot, without another event read, in a format accepted by CLI `--snapshot`. Files retain selected disclosed content and absolute source paths: protect them as sensitive data. They are not project-sharing codes, execution checkpoints or permission grants.
3. Export requires an existing parent directory and a new file, creates no directories, never replaces existing files and refuses paths inside the selected Run/Session stores. Complete output is capped at 64 MiB. A failed write may leave a partial newly created file; there is no automatic retry, deletion or rollback. Choose a new path for a subsequent export.

Every attempt consumes content and cache confirmations; reading/importing/exporting share the execution lock. Failures retain the prior view. Clear or source/disclosure changes discard older delivery, and Clear does not delete saved files. Cache tasks not yet started are discarded, but already-started thread I/O may complete after Clear or exit, including writes. Cancellation is not filesystem rollback. Path checks are not a sandbox against concurrent local directory replacement.

Only import caches from trusted sources. Source binding and projection identity are not signatures and cannot prove redaction, unchanged historical logs or unchanged source directories. Even metadata-only cache import requires `VIEW CONTENT`; do not use it to inspect caches received from strangers. ASCII JSON escaping and literal Rich Text display remain in place. Read/write, interoperability, rejection and UI concurrency regressions passed.

The a6 release (focused regressions passed) adds CLI `checkpoint workflow-approve-resume` and TUI “Approve exact call and resume parent”: supply an async factory and complete parent-node/child-run/Agent/call/tool identity, with independent code, approval, and parent-execution confirmations. It rechecks before/after assembly and clears operation grants. See [factories and authority boundaries](./workflows.en.md).

In TUI, review links read-only and separately inspect the actual action, manually enter exact identities/permissions, then enter `LOAD WORKFLOW`, `APPROVE <Call ID>`, and `RESUME WORKFLOW`. Confirmations are consumed after form validation. Ordinary and approval recovery share one background task lock; both forms are locked while active, and later input changes cannot redirect captured parameters. Pause, optional synchronous-node threading, and SQLite observation reuse existing mechanisms. Errors display types only. Cancellation/exit releases factory resources and grants without clearing external durable pause requests. No pending item is selected automatically, no batch approval is inferred, and a pause does not prove tool execution. Focused regressions have passed.

The `2.0.0a5` release (focused regressions passed) adds `wagent checkpoint workflow-approvals <run-id>` and read-only approval-link review on Checkpoints. A separate Agent state root and custom state keys are optional. Only parent/child identities, checkpoint status, and match results are displayed, always with `authorized=false`. Review imports no definitions, runs no models/tools, and consumes no code-load/recovery confirmations. Python hosts may explicitly inject `WorkflowApprovalGrants` for one-shot exact authority; the a6 CLI/TUI now use the same factory service (focused regressions passed). See the [workflow guide](./workflows.en.md).

Status: the Typer/Rich CLI, launchable Textual TUI, local session lifecycle, configured-agent entry point, token/cost visibility, prompt-free agent-checkpoint listing, CLI/TUI tool selection/authority/approval resume, privacy-safe live RunEvents, and local evaluation are `Experimental` in `2.0.0a3`. `2.0.0a4` additionally implements safe pre-call cost-envelope event projection, cross-session per-agent usage/cost summaries, guided workflow-checkpoint recovery, and confirmed general-plugin lifecycle operations. Host-lock-catalog-driven sandboxed package installation with independent load confirmation is included in `2.0.0a4`. Online source discovery, automatic locking, and automatic upgrades remain `Planned`.

The `2.0.0a4` release adds a six-line `W-AGENT` character-art welcome banner, a kaomoji, and version information to the TUI Home page. It uses terminal characters without images, fonts, or network resources. Narrow windows use a compact title, and resizing updates the layout. The artwork appears only on Home and does not occupy other operation pages.

Workflow recovery in the `2.0.0a4` release now uses a Textual-managed background worker. Checkpoints adds “Pause active workflow at next boundary”, targeting only the workflow currently resumed by this TUI. State root, run ID, entry, and execution options are locked during recovery, and duplicate resumes do not start another task. A request displays a pending state; only an engine result of `paused` confirms a saved pause boundary. Resuming again requires fresh code-load and execution confirmations. Synchronous-node threading is off by default; enabling it selects `ThreadedWorkflowNodeInvoker`, while inline blocking code can still occupy the UI. Python imports remain on the original thread. Exiting cancels the worker and does not constitute a completed boundary pause; inspect checkpoints for uncertain execution. The `2.0.0a5` release separately adds SQLite cross-process requests and opt-in CLI observation (`2.0.0a5`, focused regressions passed). The TUI now has an off-by-default SQLite observation checkbox alongside its in-process pause button. Observation mode and run/root are captured at recovery start. Cleanup clears only UI-owned temporary requests, never external persistent requests. See [workflow source composition](./workflows.en.md).

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
wagent plugin inspect --config <plugins.yml> [--json]
wagent plugin validate-load --config <plugins.yml> --confirm-plugin-code [--json]
wagent plugin validate-installed <installed-path> --confirm-plugin-code [--json]
wagent composition export|inspect|save|list
wagent composition plan <code> [--inventory <plugins.json>] [--json]
wagent composition install-plan <code> --catalog <install-lock.json> [--json]
wagent composition install <code> <request-digest> --catalog <install-lock.json> --confirm-network --confirm-package-code [--json]
wagent session create|list|show|usage|archive|unarchive
wagent checkpoint list [--session <id>]
wagent checkpoint workflow-list [--state-root <path>]
wagent checkpoint workflow-resume <run-id> --workflow-entry <module:attribute> --confirm-workflow-code --confirm-resume
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent run <prompt> --confirm-model-call
wagent run-events <run-id> [--after-sequence <n>] [--limit <n>] [--json]
wagent run-resume <session-id> <run-id> --approve-tool-call <call-id> --confirm-model-call
wagent evaluate <cases.json> --confirm-model-call [--report <report.json>]
wagent tui
```

The source entry points for these commands exist; locked installation and `run-events` are included in `2.0.0a4`. The CLI prints human-readable text by default; template, initialization, probe, composition, list, session-lifecycle, and evaluation commands offer structured JSON. `run-events` reads only persisted events for one run through a sequence cursor, projecting a strict allowlist of status, counts, and cost by default. It does not show model text, tool arguments/results, media URLs, or inline bodies, and does not execute a model or tool; applications can read raw events through the Python API only after applying their own authorization. `session show` and `evaluate` expose input, output, and cached-input tokens plus versioned cost when available, and mark whether metering is complete. `session usage` aggregates metering across sessions by agent without emitting prompts, messages, model outputs, or tool results; archived data is opt-in. Evaluation uses disposable state by default, and reports omit prompts and outputs by default. Failures return stable nonzero exit codes. `probe` performs credential-free L1 probing; `provider-probe` assembles a provider from strict configuration and requires the additional `--confirm-active-probe` flag for active mode.

The compatibility window retains the `w-agent` command name and basic `config` and `bean` subcommands; `wagent` is canonical.

`run` uses strict `.wagent/config.json` plus environment-variable credential references and requires `--confirm-model-call` every time. Optional versioned pricing exposes cost and completeness in CLI/TUI runs, sessions, checkpoints, and evaluation. Configuration may select from an explicit tool catalog. The CLI imports developer Python tools only when `--tool-entry` and independent `--confirm-tool-code` are both present, while `--grant-permission` grants authority for that command. The TUI uses independent `RUN`, `LOAD TOOLS`, authority input, and `RESUME` confirmations bound to exact session/run/call IDs, and clears confirmations immediately. Workflow recovery likewise requires independent code-load and execution confirmations and selects a definition by checkpoint name, version, and kind. RunEvent panels expose only allowlisted event type, status, token, and cost fields, never arbitrary error bodies, tool/model bodies, or media content. The TUI Models screen also exposes configured safe/active provider probes; active generation requires typing `ACTIVE`, and confirmation is never retained.

`plugin inspect` parses only references, enabled state, and configuration keys, and imports no code. `plugin validate-load` requires `--confirm-plugin-code`, loads transactionally in a temporary `PluginManager`, prints an active snapshot without configuration values, and unloads before the process exits. `composition install-plan` reads an explicit lock catalog and emits offline request digests plus the index origin (scheme/host/port, not full path or credentials). `composition install` binds the exact digest and separately confirms network and package-code execution; Docker is the default, and unisolated local development additionally requires `--backend unsafe-local --confirm-unsafe-local`. `plugin validate-installed` revalidates the install tree and applies the second load confirmation, checking entry-module origin and plugin name/version before setup. The TUI persistent manager uses `LOAD PLUGINS` for YAML, `LOAD INSTALLED` for an installed site, and exact `UNLOAD <name>` for lifecycle teardown. `config validate`, online source discovery, automatic locking, and automatic upgrades remain `Planned`.

The TUI Evaluation screen requires typing `EVALUATE` before sequentially running a strict JSON dataset. It uses disposable state, clears confirmation immediately, displays only token/cost/latency/tool/pass metrics, and may write a default privacy-safe report. Custom scorers, output persistence, and developer tool entries use the Python API/CLI.

## TUI technology

The TUI uses Textual through the optional `wagent-framework[tui]` dependency. The base CLI uses Typer/Rich. The TUI starts the framework in process and requires no resident daemon; remote connections are `Reserved`. a7 UI has twelve sections (Replay is available in 2.0.0a7 with focused regressions passing), plus real session create/list/archive/unarchive controls, offline composition inspection, safe endpoint probing, template information, and Docker availability checks. Sections without runtime operations state that they are planned instead of presenting placeholders as functional controls.

The canonical next-generation command is `wagent`; the existing `w-agent` command remains a compatibility alias during migration.

## First-release screens

### Home

Shows the current workspace, Python and W-Agent versions, active profile, plugin errors, and recent runs.

### Models

Manages provider configuration references, model catalogs, and probe results. Before an active probe, it shows potential cost and the minimal test type that will be sent.

### Plugins

`2.0.0a4` can show local YAML `module:attribute` sources, enabled state, and configuration keys without importing modules. After `LOAD PLUGINS` confirmation, it shows name, version, API compatibility, provided capabilities, dependencies, and lifecycle state. Configuration values, plugin exception bodies, and metadata are excluded from the projection. After locked installation, the user must select the installed directory here and enter `LOAD INSTALLED`; only then is the tree revalidated and the entry loaded. A name-bound confirmation unloads a plugin and its active consumers, and releases process import-path leases owned by installed batches. The first release does not discover sources online or auto-update.

### Composition

Displays a resolved profile, compares named versions, exports a code, and previews dependencies, configuration differences, and security risk during import. `2.0.0a4` can build a fully offline environment/plugin dependency plan from an explicit JSON candidate inventory and a fully offline install request from a host lock catalog. Without a candidate inventory, it considers only plugin names and versions active in the current TUI process. Planning performs no network query, code import, or package installation and never replaces later confirmations. Installation requires exact `INSTALL <digest>`; unisolated local mode deliberately uses the distinct `INSTALL LOCAL <digest>` phrase so Docker confirmation cannot authorize host execution. The result explicitly remains unloaded and is handed to the Plugins screen for the second confirmation.

### Run

The current screen can read strict local configuration, start a text agent, and show final output, input/output tokens, and versioned cost. The user must type `RUN` before a model call. When cost preflight is enabled explicitly, the event panel shows the estimator, route/attempt counts, replay cost envelope, and projected cumulative cost without prompts. Tool entries are imported only after a separate `LOAD TOOLS` confirmation, and authority applies only to the current run. The screen projects persisted events live through the public `RunEventCallback`, never reads private loop state, and omits prompts, model text, and tool arguments.

### Sessions

Creates, lists, archives, and unarchives local sessions through the same `JsonSessionStore` used by the Python API. Details show run count, cumulative tokens, aggregate cost when table version and currency match, and prompt/output-free cross-session agent summaries. Configured agents start from the Run screen.

### Checkpoints

The current screen refreshes prompt-free local agent approval checkpoints with run/session, status, tool name, call ID, argument names, tokens, and cost, but no prompts, argument values, or output. The `2.0.0a4` release also adds a read-only next-page view of persisted RunEvents by exact run ID and sequence. The UI requests the safe default from `RunEventReplay.projected_page()` directly instead of first receiving a raw event page, then advances the cursor input; this does not resume execution. The user can resume only after supplying configuration, tool entries, authority, the exact call ID, and separate `LOAD TOOLS`/`RESUME` confirmations; checkpoints never restore authority.

`2.0.0a4` also refreshes workflow-checkpoint summaries from a user-selected local state root. It shows workflow name/version/kind, status, node identifiers, and counters while excluding input, state, output, scope, and metadata values. Recovery requires a `module:attribute` definition entry plus separate `LOAD WORKFLOW` and `RESUME WORKFLOW` confirmations; the loaded name, version, and kind must match exactly. Results and events use privacy-safe projections. The UI neither copies nor migrates stores automatically, and it never force-replays an uncertain `RESUMING` checkpoint.

### Approval chains (a6, focused regressions passed)

This separate screen handles `parent Agent → Workflow tool → child Agent → pending tool` through the public coordinator. It does not replace single-layer recovery on Checkpoints.

1. Enter the parent Agent state root and outer Run ID, plus optional separate Workflow/child roots and custom approval state keys. All three store directories must already exist.
2. Choose **Review chain**. Background read-only review displays one-based row numbers, complete call links and the pause-event sequence, excluding scope, inputs, arguments and model output. Nothing is selected automatically.
3. Enter a row number and choose **Select reviewed row**. Only matching pending links can be selected. Changed query inputs require a new review; changed row numbers require reselection. Every review/selection clears old confirmations.
4. Separately inspect actual actions, then provide the async parent-loop factory `module:attribute` and independent parent/child permissions (comma-separated, empty by default). The factory follows `WorkflowToolApprovalFactory`, not the single-layer WorkflowDefinition contract.
5. Enter four exact confirmations: `LOAD AGENT`, `APPROVE PARENT <outer Call ID>`, `APPROVE CHILD <inner Call ID>`, and `RESUME AGENT <outer Run ID>`, then resume.

Recovery captures the request and clears confirmations/selection immediately. Chain fields and other recovery buttons are locked during execution. Review/recovery shares the existing Workflow worker exclusion; repeated clicks cannot start a second task. A stop, failure or cancellation requires another review; the next call is never filled or approved automatically. Results contain status, pending identifiers, counts and token/cost accounting only; a stop reason does not prove the inner tool executed.

Exiting cancels and waits for cleanup. The coordinator clears temporary grants and the factory closes resources, without automatic replay. Cancellation does not prove absence of side effects; inspect uncertain checkpoints. Background workers do not isolate Python: synchronous factory imports or nodes can still block the UI. Hosts explicitly assemble threading, pause and concurrency policies. The Checkpoints pause button does not control this chain, and the framework does not clear external persistent pause requests for it.

Companion CLI commands are `checkpoint workflow-tool-approvals` and `workflow-tool-approve-resume`; see [two-layer operations](./workflows.en.md). This UI passed focused a6 regressions and remains Experimental.

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

Local regressions pass; the final clean-environment unified result will be recorded in [acceptance-2026-10-01](./acceptance-2026-10-01.en.md). This does not establish live-service, billing, quality or manual production UI acceptance.
