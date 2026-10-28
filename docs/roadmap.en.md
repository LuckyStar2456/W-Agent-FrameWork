# Roadmap and capability status

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./roadmap.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

This document is the single capability-status overview for W-Agent. Phases describe implementation order and do not promise release dates.

The [Harness core baseline M0–M5](./harness-core.en.md) is now accepted at its fixed scope: Spring-inspired IoC/DI/AOP, decorators, lifecycle and replaceable public execution. M5 passed 259 related tests, offline candidate building/installation and three outside-repository examples via Python/CLI/headless TUI; see [final acceptance](./harness-acceptance.en.md). No required core milestone remains. The source is unpublished; release/version selection is a separate decision. Reserved and deferred features below are not new completion gates.

Release policy changed: no new alphas. Complete and accept the [stable baseline B01–B12](./stable-release-baseline.en.md), publish a stable release, then optimize enhancements. Not every Planned/Reserved item below is a basic-release blocker.

Current status: stable 2.0.0 is published. Basic gates, artifact checks, isolated installation, installed CLI/TUI and live Docker passed, with matching remote digests; see [publication acceptance](./acceptance-2026-10-01-stable-release.en.md). The a4–a9 references and batch counts remain historical provenance. Enhancements follow; no new alphas.

This increment adds durable Run/Session usage associations and read-only queries, structural/overlapping splitting and raw-archive CLI entries. See [acceptance and remaining modules](./acceptance-2026-10-01-links-splitting-archives.en.md). All are Experimental features included in 2.0.0. The earlier 375 HTTP/format/Runtime checks only cover [that previous code](./acceptance-2026-10-01-http-archives-runtime.en.md), not the complete framework or live services.

2026-10-01 uses parallel module agents and primary-agent unified acceptance; see the [acceptance record](./acceptance-2026-10-01.en.md). New worktree features are outside published a9. Local regressions and real vendor/sandbox acceptance are reported separately.

Follow-up work adds knowledge synchronization/evaluation entries, plugin replacement entries and media presentation. Later code uses [separately authorized focused acceptance](./acceptance-2026-10-01-followup.en.md), not the earlier full-suite count.

## 1.x compatibility foundation (1.5.2)

| Capability | Status | Notes |
|---|---|---|
| `BaseAgent.arun()` | `Implemented` | Minimal asynchronous agent abstraction |
| IOC, component scanning, lifecycle | `Implemented` | Existing 1.x engineering foundation |
| AOP, retry, circuit breaker, timeout, bulkhead | `Implemented` | General resilience capabilities |
| Dynamic configuration and event bus | `Implemented` | Not the next-generation plugin kernel |
| Logging, metrics, tracing, health | `Implemented` | Some backends are optional dependencies |
| Wasm and nsjail skill sandboxes | `Implemented` | Legacy APIs retained; modern nsjail and ProviderSkillSandbox bridge are worktree Experimental; generic Wasm hard-resource provider remains unimplemented |
| LangChain adapter and FastAPI example | `Implemented` | 1.x integrations |

## First-release plan

| Capability | Status | Phase |
|---|---|---|
| Phase 1 microkernel public protocols | `Implemented` | 2.0.0a1 |
| Unified registry and plugin lifecycle | `Implemented` | 2.0.0a1 |
| Dependency resolution, reversible registration, scopes, event pipelines | `Implemented` | 2.0.0a1 |
| Unified model protocol and stream events | `Implemented` | Phase 2A / 2.0.0a1 |
| OpenAI-compatible Chat Completions adapter | `Implemented` | Phase 2B / 2.0.0a1 |
| Generic HTTP mapping layer and SSE/NDJSON transport | `Implemented` | Phase 2B / 2.0.0a1 |
| Native Anthropic, Gemini, Ollama, and Qwen templates | `Implemented` | Phase 2B / 2.0.0a1 |
| Gemini image/audio output Part mapping and replaceable mapper | `Experimental` (`2.0.0a4` release) | Phase 2B/3 |
| Responses image-generation tool and final PNG/JPEG/WebP output | `Experimental` (offline mapping regressions passed, no live acceptance) | Phase 2B/3 |
| Other vendor media output, audio/reasoning deltas and image previews | `Planned` | Phase 2B/3 |
| DeepSeek, GLM, Qwen-compatible, and Turbo template registry | `Implemented` | Phase 2B / 2.0.0a1 |
| Dedicated OpenAI Responses and vLLM differences | `Implemented` | Phase 2B / `2.0.0a4` |
| Python and YAML routing | `Implemented` | Phase 2A / 2.0.0a1 |
| Manual probe API, cache, and periodic scheduler | `Implemented` | Phase 2A / 2.0.0a1 |
| Automatic safe probing and health bridging through the explicit registration service | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI safe endpoint-probe entry points | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI configured safe/active provider probes | `Experimental` | Phase 2B/6 / 2.0.0a1 |
| Collecting invocation, timeout, retry, and failover executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Safe event-pass-through executor | `Implemented` | Phase 2B / 2.0.0a1 |
| Normalized provider input/output token metering | `Implemented` | Phase 2B / 2.0.0a1 |
| Explicit verified-prefix text-stream recovery | `Experimental` | Phase 2B / `2.0.0a4` |
| Provider-native cursor contract and executor wiring | `Experimental` (`2.0.0a4` release) | Phase 2B |
| Native Responses background continuation, replaceable checkpoints and SQLite cross-process cursor recovery | `Experimental` (offline Python API regressions passed, no live acceptance) | Phase 2B/6 |
| Other vendor cursors, CLI/TUI configuration and full Agent session/accounting recovery | `Planned` | Phase 2B/6 |
| Single-agent ReAct/tool-loop template | `Implemented` | Phase 3 / 2.0.0a1 |
| In-process RunEvent stream and bounded budgets | `Implemented` | Phase 3 / 2.0.0a1 |
| Visible run-level token metering and hard budgets | `Implemented` | Phase 3 / 2.0.0a1 |
| Session totals and per-attempt token ledger | `Implemented` | Phase 3/6 / 2.0.0a1 |
| Explicit opt-in agent text-delta RunEvents | `Experimental` (`2.0.0a4`) | Phase 3/6 |
| Versioned price tables, cost metering, and hard run cost budgets | `Implemented` | Phase 3/6 / 2.0.0a2 |
| Pluggable pre-call token estimators and soft-threshold events | `Experimental` (`2.0.0a4`) | Phase 3/6 |
| Cross-session per-agent usage/cost summaries | `Experimental` (`2.0.0a4`) | Phase 3/6 |
| Replaceable pre-call cost estimation and replay envelope | `Experimental` (`2.0.0a4`) | Phase 3/6 |
| Local JSONL RunEvents and approval-checkpoint resume | `Implemented` | Phase 3 / 2.0.0a1 |
| Read-only cursor paging of persisted RunEvents | `Experimental` (`2.0.0a4` release) | Phase 3/6 |
| Replaceable JSON RunEvent redaction projection and projected paging | `Experimental` (`2.0.0a4` release) | Phase 3/6 |
| Replaceable event reducer, read-only accumulated snapshots, and text/tool/media view reconstruction | `Experimental` (a6; focused regressions passed) | Phase 3/6 |
| Optional tool-result event bodies, replaceable encoder and independent accumulator disclosure | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Read-only cross-Run rich Session views, independent disclosure and versioned snapshots | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Run/Session accumulated-view CLI, explicit content disclosure and source-bound cache continuation | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Run/Session TUI Replay in-memory snapshots, independent disclosure and display slicing | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Replaceable Session input recorder, ordered text/image/audio persistence and schema 2 | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Standard input decoder, replaceable text/recorded-media history policies, independent input-block projection and CLI/TUI disclosure | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| Typed-message Runtime runs, strict input manifests, CLI media entry and separate recording/history confirmations | `Experimental` (2.0.0a7; focused regressions passed) | Phase 3/6 |
| TUI media run entry, separate recording/history consent, background tasks and cancellation | `Experimental` (`2.0.0a7`; focused regressions passed) | Phase 3/6 |
| Replaceable local keyword/extractive-summary policies, recent-segment retention and text-size limits | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Built-in context-template CLI/TUI wiring, shared immutable options and independent transformation consent | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Async history protocol, trusted retrieval/summary callback templates, Runtime awaiting/cancellation and post-preparation Session-change detection | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Agent-backed model summaries, independent Run budgets and prompt-free accounting observer | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Idempotent summary observer, explicit cumulative main-Run usage aggregation, completeness and grouped cost totals | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| SQLite summary-report observer, explicit initialization, transactional idempotence/capacity checks and reopening | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| Process-local shared token/cost reservation protocol, atomic admission, actual settlement and Provider wrapper | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| SQLite shared budgets, explicit configuration binding, transactional admission/settlement, durable tickets and reopening | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| Optional explicit shared-budget reconciliation, host inactivity confirmation, expected-state matching and immutable memory/SQLite receipts | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| Named Runtime/Provider shared-budget bindings, JSON host-catalog references, explicit pool snapshots and original-client ownership | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| CLI run/run-resume/evaluate/provider-probe and TUI Run/approval-resume/evaluation/probes budget factories, independent code consent, lifecycle cleanup and pool usage display | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| Shared-budget factory wiring for evaluation/probes, batch-wide pools and separate display | `Experimental` (2.0.0a9; see release validation) | Phase 3/6 |
| Replaceable embedding/dense-vector protocols, read-only Qdrant query template and local-candidate history selection | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Generic single-text HTTP embeddings, replaceable JSON mappings, OpenAI-compatible/native Ollama templates, fixed-dimension validation and structured service usage | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Explicit embedding budget wrapper, host bounds/pricing, admission reservations, known-usage settlement, unknown holds and shared memory/SQLite controller wiring | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Explicit history-vector preparation, separate body-embedding consent, exact-plan-bound Qdrant upserts and acknowledged/applied/unknown outcome handling | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Document-store/knowledge-retrieval protocols, memory/keyword templates, vector-ID document resolution and source-preserving USER-data context policy | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Ordinary knowledge_search binding, permission/external-call approval, query/JSON bounds, local factory and reuse of existing named Runtime/CLI/TUI tool entries | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Pure host-text preparation, replaceable UTF-8 splitting, deterministic chunk IDs, immutable snapshots/named SQLite versions, explicit creation/writes and pinned retrieval | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Snapshot/embedding-label/dimension-bound vector IDs, explicit body-embedding batches, existing Writer wiring and fixed-candidate retrieval restoring original document identities | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Explicit local text-file/directory imports, replaceable parser/UTF-8 template, limits/link rejection, raw/parsed source fingerprints and snapshot integration | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Named knowledge.binding catalogs, per-call Runtime queries/knowledge-only context, CLI/TUI run code/query consent and host-factory lifecycle | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Local knowledge management API/CLI/TUI, import preview/explicit save, separate creation/read/write/body consent, read-only catalog and pinned keyword browsing | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Index journal management API/CLI/TUI, local original/effective outcomes, sensitive-detail consent and exact-identity host-evidence reconciliation | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Exact-vector artifacts/strict codec, replaceable staging protocol/separate SQLite, preparation/approved-execution APIs and read-only CLI/TUI plan views (no re-embedding on execution) | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Named knowledge-plan host factories, prepare-save/approved-execute management API and CLI/TUI, independent code/read/embed/save/overwrite/journal consent | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Optional plan catalog protocol, full-artifact validation/consistent reads, preparation coverage/overlap, CLI/TUI discovery and pure missing-batch API/CLI/TUI advice with adjustable bounds | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Immutable named full-prepared builds, strict codec/separate SQLite, create/review/single-batch execution API/CLI/TUI, host lifecycle/separate digest approvals, stable batch attempt IDs/journal-derived continuation (no auto-replay) | `Experimental` (local/mock regressions passed, included in 2.0.0, outside a9) | Phase 3/6 |
| Optional PDF/DOCX/XLSX/PPTX parsing, incremental extraction reuse/deltas, extracted originals and character/UTF-8 chunk offsets, CLI/TUI preview-digest commits | `Experimental` (real four-format fixtures and local regressions passed, included in 2.0.0) | Phase 3/6 |
| BM25, RRF hybrid retrieval, replaceable reranking, Workflow evidence nodes/messages and isolated knowledge evaluation | `Experimental` (offline end-to-end regressions passed, real quality unaccepted) | Phase 3/6 |
| Build/journal catalog API/CLI/TUI, same-journal atomic conflict coordination, explicit predecessor-bound retries, ready preparation checkpoint recovery without re-embedding | `Experimental` (local regressions passed, included in 2.0.0; not a cross-store lease) | Phase 3/6 |
| Explicit SQLite import trace/extraction cache, file-level stable vector IDs/reuse, exact upsert/delete synchronization, same-store head/receipt barriers and history-preserving not-sent retries | `Experimental` (worktree Python API; real local stores/mock transport regressions passed, no live Qdrant acceptance) | Phase 3/6 |
| Existing evaluate CLI/TUI per-case knowledge queries, batch preflight, separate code/query consent and accounting scope | `Experimental` (actual offline Runtime/Provider and headless UI regressions passed) | Phase 3/6 |
| Incremental sync management API/CLI/TUI: UTF-8 trace preview-locked save, named-host preparation/staging, separate upsert/delete approval, saved-plan review/execution; explicit CLI retry/reconciliation | `Experimental` (separately scoped acceptance in the sync/accounting record) | Phase 3/6 |
| Explicit PDF/DOCX/XLSX/PPTX trace sync CLI/TUI; replaceable raw archive protocol, SQLite original bytes and trace associations | `Experimental` (real offline format/archive checks, included in 2.0.0) | Phase 3/6 |
| Paragraph/sentence structural splitting, bounded codepoint overlap, exact source spans, trace v2/legacy-v1 compatibility and sync CLI/TUI configuration locks | `Experimental` (deterministic text rules, not model semantic inference) | Phase 3/6 |
| Raw-archive API/CLI: version previews, approved-source saves, receipt verification and independently authorized single-blob new-file export | `Experimental` (no overwrite/execution/automatic directory restore) | Phase 3/6 |
| Directory restore/GC, model-semantic splitting, custom persistent splitter decoder registration, cross-store sync, per-document preparation checkpoints, cross-store execution leases and other backend plans | `Planned` | Phase 3/6 |
| Snapshot/target-bound knowledge-index manifests, separate SQLite pending/final-receipt journals, explicit journaled writes, duplicate-attempt rejection and local all-point coverage | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| Optional host-evidence index reconciliation, explicit inactivity/write confirmation, immutable decisions with original observations, v1/v2 journal reads and derived coverage | `Experimental` (included in 2.0.0, local/mock regressions passed, not part of a9) | Phase 3/6 |
| External collection creation, remote evidence collection/verification and operation/point lookup, erroneous reconciliation correction, legacy snapshot-index migration, other native/batch embedding templates and dedicated assembly, external reranking/other backends and live-service/retrieval-quality acceptance | `Planned` | Phase 3/6 |
| Cross-model/embedding/retrieval/rerank usage protocol, memory/SQLite observation ledger, explicit existing-budget decorators and read-only service-usage CLI | `Experimental` (explicit wiring, not a replacement budget or vendor invoice) | Phase 3/6 |
| Named Runtime/Provider observation bindings, actual model attempts/shared-ticket deduplication, optional retrieval observation and four CLI/TUI entry points | `Experimental` (host-operation scope, not exclusive per-Run costs) | Phase 3/6 |
| Optional memory/SQLite Run/Session→operation links, pre-preparation persistence, resume identity checks, read-only CLI queries and operation-summary lookup | `Experimental` (links do not prove Run start/completion and are not a cross-store transaction) | Phase 3/6 |
| Metered native cursors, per-observation Run attribution for preparation/services, full-chain automatic aggregation and unified retrieval/rerank service-budget wiring | `Planned` | Phase 3/6 |
| Optional input name/metadata wrapper records, independent field display and model-history reuse | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Independent input-message field disclosure in CLI/TUI Replay, wrapped content views and shared projector assembly | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| Explicit message-field CLI/TUI input, per-call recording and historical sending configuration | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| TUI trusted-cache import/continuation, explicit new-file export and CLI cache interoperability | `Experimental` (2.0.0a8; focused regressions passed) | Phase 3/6 |
| TUI Replay PNG/JPEG/WebP character previews, WAV metadata, independently confirmed export and replaceable renderer | `Experimental` (actual offline decoding and headless UI regressions passed) | Phase 3/6 |
| High-resolution/color terminal media, audio playback/waveforms, further codecs and isolated decoding | `Reserved` | Optional later enhancements, not additional first-release acceptance gates |
| Separate tool definition, policy, and execution | `Implemented` | Phase 3 / 2.0.0a1 |
| Python-function tool template | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP and shell-free command tool adapters | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP client binding adapter | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2026-07-28 stdio/Streamable HTTP clients and discovery | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2025 initialization negotiation and HTTP sessions | `Experimental` (`2.0.0a4` release) | Phase 3/5 |
| Explicit MCP handlers, bounded 2026 MRTR, duplex stdio and modern/legacy resource subscriptions | `Experimental` (local subprocess/mock regressions passed, no external interoperability acceptance) | Phase 3/5 |
| MCP 2026 POST subscriptions, 2025-11-25 HTTP server requests/explicit GET notifications and bounded cancellation/close | `Experimental` (real loopback HTTP checks, no external-service acceptance) | Phase 3/5 |
| MCP 2024 HTTP+SSE, Tasks, automatic recovery/reconnection, OAuth and complete sandbox binding | `Planned` | Phase 3/5 |
| Local session lifecycle and cross-run text projection | `Implemented` | Phase 3 / 2.0.0a1 |
| Explicit tool-argument delta RunEvents | `Experimental` (`2.0.0a4` release) | Phase 3 |
| Declarative top-level field allow/mask projection template | `Experimental` (`2.0.0a4` release) | Phase 3/6 |
| Explicit multimodal output events and three-level disclosure projection | `Experimental` (`2.0.0a4` release) | Phase 3/6 |
| Nested-path copy/rename/fixed-mask projection template | `Experimental` (`2.0.0a4` release) | Phase 3/6 |
| DAG, state-graph, and Python workflows | `Implemented` | Phase 4 / 2.0.0a1 |
| Bounded concurrent asynchronous DAG frontiers | `Experimental` (`2.0.0a4` release) | Phase 4 |
| Replaceable node invocation and opt-in synchronous thread execution | `Experimental` (`2.0.0a4` release) | Phase 4 |
| Run-ID-scoped external boundary pause and replaceable request source | `Experimental` (`2.0.0a4` release) | Phase 4 |
| TUI background recovery, boundary pause, and optional threaded invocation | `Experimental` (`2.0.0a4` release) | Phase 4/6 |
| CLI and cross-process workflow pause controls | `Experimental` (`2.0.0a5`; focused regressions passed) | Phase 4/6 |
| Read-only pause-source composition and opt-in TUI cross-process observation | `Experimental` (`2.0.0a5`; focused regressions passed) | Phase 4/6 |
| TUI large character-art welcome logo, kaomoji, and narrow-window layout | `Experimental` (`2.0.0a4` release) | Phase 6 |
| Local node-level checkpoint, pause, and resume | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/workflow convenience adapters | `Implemented` | Phase 4 / 2.0.0a1 |
| Node suspension and exact Agent approval continuation inside Workflow | `Experimental` (`2.0.0a5`; focused regressions passed) | Phase 3/4 |
| Approval link review, CLI/TUI read-only views, and host-owned one-shot grants | `Experimental` (`2.0.0a5`; focused regressions passed) | Phase 3/4/6 |
| Explicit assembly and CLI exact approval with parent recovery | `Experimental` (a6; focused regressions passed) | Phase 3/4/6 |
| TUI exact approval, background parent recovery, and fresh confirmations | `Experimental` (a6; focused regressions passed) | Phase 3/4/6 |
| Two-layer read-only linkage, independent grants, and parent Agent recovery service | `Experimental` (a6; focused regressions passed) | Phase 3/4 |
| Two-layer CLI review and recovery with four confirmations | `Experimental` (a6; focused regressions passed) | Phase 3/4/6 |
| Two-layer TUI review, explicit row selection and four-confirmation recovery | `Experimental` (a6; focused regressions passed) | Phase 3/4/6 |
| Agent-to-Workflow reference-first continuation bridge and parent/child suspension | `Experimental` (a6; focused regressions passed) | Phase 3/4 |
| Typed tool continuation, optional resume protocol, and ReAct schema 2 checkpoints | `Experimental` (a6; focused regressions passed) | Phase 3/4 |
| Atomic cross-store commit | `Reserved` | Later design |
| Privacy-safe workflow-checkpoint discovery, explicit definition loading, and CLI/TUI recovery | `Experimental` | Phase 4/6 / 2.0.0a4 |
| Docker/OCI coding sandbox | `Implemented` | Phase 5 / 2.0.0a1 |
| Explicit `UnsafeLocalSandbox` mode | `Implemented` | Phase 5 / 2.0.0a1 |
| Sandbox command-tool binding | `Implemented` | Phase 5 / 2.0.0a1 |
| nsjail cgroup v2 provider and legacy ProviderSkillSandbox bridge | `Experimental` (local parameter/lifecycle regressions, no real Linux isolation acceptance) | Phase 5 |
| Generic hard-resource Wasm provider, domain/IP network allowlists and real cross-platform acceptance | `Planned` | Phase 5 |
| Customer-support/RAG and coding profiles | `Implemented` | Phase 5 / 2.0.0a1 |
| Portable composition codes, safe preview, and versioning | `Implemented` | Phase 6 / 2.0.0a1 |
| Replaceable offline environment/plugin dependency planning | `Experimental` | Phase 6 / 2.0.0a4 |
| Host lock catalogs, sandboxed package installation, and independent plugin-load confirmation | `Experimental` (`2.0.0a4` release) | Phase 1/5/6 |
| Import-free general-plugin preview, confirmed batch load, and TUI unload | `Experimental` | Phase 1/6 / 2.0.0a4 |
| In-process replacement preview, explicit quiescence, one-shot exact plans and stale-handle isolation | `Experimental` (real local manager/registry regressions passed) | Phase 1/6 |
| Persistent plugin session CLI and TUI current-manager replacement, separate import approval, exact confirmations/drift checks | `Experimental` (local session and headless UI regressions passed) | Phase 1/6 |
| Plugin online discovery/lock generation/package upgrades, automatic draining/consumer rebuilding/state migration and durable audit | `Planned` | Phase 1/6 |
| Typer/Rich CLI, Textual TUI, and session lifecycle UI | `Experimental` | Phase 6 / 2.0.0a1 |
| Locally configured text-agent run entry point | `Experimental` | Phase 6 / 2.0.0a1 |
| Configured tool selection, explicit code loading, and CLI approval resume | `Experimental` | Phase 3/6 / 2.0.0a1 |
| Prompt-free agent approval-checkpoint listing in API/CLI/TUI | `Implemented` | Phase 3/6 / 2.0.0a1 |
| TUI tool loading/authority/exact approval resume and privacy-safe live RunEvents | `Experimental` | Phase 3/6 / 2.0.0a3 |
| Scripted model mocks, explicit record/replay, and local evaluation metrics | `Experimental` | Phase 6 / 2.0.0a1 |
| CLI/TUI local-evaluation entry points and privacy-safe reports | `Experimental` | Phase 6 / 2.0.0a1 |
| Evaluation pricing/cost metrics | `Experimental` | Phase 6 / 2.0.0a2 |
| Versioned support/coding suites and case-contract scoring | `Experimental` (`2.0.0a4`) | Phase 6 |
| Minimal 1.x `LegacyAgentAdapter` | `Implemented` | Phase 6 / 2.0.0a1 |

## Delivery phases

### Phase 0: design and documentation

- Status: `Implemented`.
- Freeze design principles, protocol boundaries, status labels, and non-goals.
- Update all Chinese and English documentation.
- Do not modify existing runtime code.

### Phase 1: microkernel

- Status: `Implemented` in `2.0.0a1`.
- Python 3.11+.
- `PluginSpec`, unified registry, lifecycle, dependency resolution, scopes, and event/pipeline dispatch.
- Four plugin entry styles converge on one registration process.
- Tests for unload, failure rollback, and run snapshots.

### Phase 2: models and routing

- Status: `Implemented` for the 2A foundation and 2B adapters/execution; explicit text-prefix recovery is `Experimental`, while the provider-native cursor contract and executor wiring are in the `2.0.0a4` release.
- 2A implements model requests, responses, stream events, capabilities, extensions, the provider registry, and stable error categories.
- 2A implements explainable route decisions, Python/YAML policies, endpoint sniffing, provider probes, caching, and periodic scheduling.
- 2B implements an OpenAI-compatible Chat Completions provider with replaceable HTTP transport.
- 2B implements the generic HTTP request-mapping layer, JSON/SSE/NDJSON transport, four native templates, and four compatible-vendor templates.
- 2B implements collecting and event-pass-through executors with one call by default, explicit bounded retry/failover, per-attempt timeout, and audit records. Pass-through execution prohibits silent replay after any event becomes visible.
- 2B normalizes provider-reported input, output, and cached-input tokens. `usage_reported` distinguishes a real zero-token report from missing provider metadata instead of presenting a zero value as complete metering.
- 2B implements optional register-and-safe-probe through `ModelRegistrationProbeService` and `ProbeHealthBridge`; low-level `ModelRegistry.register()` keeps pure registration semantics.
- 2B now includes dedicated OpenAI Responses/vLLM handling, credential-free L1 endpoint probes, and CLI/TUI provider probes assembled from strict local configuration. Provider-only assembly performs no registration or I/O; whether `safe` accesses a remote catalog is provider-defined, while explicitly authorized `active` verifies minimal generation and stream termination.
- `2.0.0a4` adds `StreamRecoveryStrategy` and `VerifiedTextPrefixRecovery`. A same-route replay occurs only when the caller passes a strategy and configures a positive `max_stream_replays`; already visible text is checked as a semantic prefix and only the unseen suffix is exposed. Divergence, tool/multi-block events, and incomplete replay fail closed. Every replay enters the attempt ledger and may incur another charge. The `2.0.0a4` release separately adds `CursorResumableModelProvider`, after-event cursors, and explicit bounded `NativeCursorRecovery`; it reuses one stream validator without restarting the full request, while the provider must guarantee generation identity and cursor exactness. The ReAct loop and local-runtime assembly now accept an explicit continuation strategy, disabled by default, and pre-call cost envelopes include resume connections. Bundled vendor adapters and cross-process recovery remain later work.

### Phase 3: agents and tools

- Status: the tool foundation, run contracts, single-agent ReAct, local event recording, approval resume, and local session lifecycle are `Implemented`; read-only cursor paging, replaceable JSON redaction projection, declarative top-level/nested field policy, explicitly enabled tool-argument deltas, and explicit multimodal output projection are in the `2.0.0a4` release.
- Implemented replaceable loops, a default ReAct template, in-process/JSONL RunEvents, step/tool budgets, and approval resume without repeating the first model request.
- Implemented run-level input, output, and total hard limits through `TokenBudget`; `RunResult.usage` and `TOKEN_USAGE` events expose cumulative values, and approval checkpoints preserve metering state. `max_output_tokens` remains a per-model-request generation cap.
- Current budgets reconcile provider-reported actual usage after each successful response and tighten the next request from the remaining output/total allowance. `require_usage=True` fails closed when a provider omits usage. A `TokenEstimator` may be injected to estimate input before the call, tighten that request's output allowance, and block an obvious overrun; `require_estimate=True` fails closed when estimation is unavailable, while `soft_limit_ratio` emits an observable warning without changing stop policy. Estimates cannot predict retry/failover accounting, so provider usage remains authoritative.
- Implemented session totals, `AttemptRecord` token ledgers covering retry/failover, and RunEvent/CLI visibility. Missing usage for failed attempts remains unknown and makes strict accounting fail closed.
- Implemented application-supplied versioned price tables, normal/cached-input and output cost metering, pricing completeness, approval-checkpoint persistence, and hard run cost budgets. Missing prices or usage fail closed, and money is never silently inferred from token counts.
- `2.0.0a4` implements `SessionManager.agent_usage()`, CLI/TUI cross-session summaries by agent, and completeness semantics that never disguise unknown usage or cost as zero.
- `2.0.0a4` implements explicit pre-call `CostEstimator`, a default versioned-price/route/retry-failover envelope, cost soft-threshold events, and hard stops before model-generation requests; provider-reported cost remains authoritative afterward. Later work adds more application-policy templates that consume soft-threshold events.
- Implemented `SessionManager`, memory/JSON stores, create/list/archive/unarchive, cross-run text projection, and session-bound agent start/approval resume.
- `2.0.0a4` implements agent text-delta RunEvents behind explicit `emit_text_deltas`. The `2.0.0a4` release adds separate `emit_tool_call_deltas`, `RunEventReplay`, replaceable `RunEventProjector`, and default-deny `FieldPolicyRunEventProjector` contracts. Replay reads ordered run-bound pages from a replaceable source, while projected pages default to content removal and JSON-compatibility validation. The declarative template can allow or fixed-mask top-level fields by exact event type or `*` fallback, and applications may still replace the projector completely. `NestedFieldRunEventProjector` adds nested selection and renaming through explicit object/array source paths, object target paths, and copy/fixed-mask actions; missing paths are skipped and target conflicts fail closed. Built-in memory/JSONL stores provide optional bounded page reads, and existing custom stores can retain their full-log method. Paging does not re-execute models or tools; callers still own raw-event read authority and custom disclosure policy. The same a8 adds explicit `emit_output_blocks`, replaceable `ModelOutputEventEncoder`, a bounded standard image/audio encoder, and three-level `MultimodalRunEventProjector` disclosure; default interfaces still hide media URLs/bodies.
- Implemented Python tools, unified registration, argument validation, permission/per-call approval, timeout/cancellation, normalized results, and prompt-free audit.
- Implemented fixed-endpoint HTTP, shell-free command tools, transport-neutral MCP binding, and MCP 2026-07-28 stdio/Streamable HTTP JSON/SSE clients with paginated discovery, explicit binding, and `x-mcp-header`. Discovery never registers, authorizes, or approves a tool automatically.
- The `2.0.0a4` release adds an explicitly selected 2025-era `initialize` / `initialized` client for stdio and Streamable HTTP session/version headers, without automatic fallback or tool-call replay. The worktree adds explicit handlers, MRTR and duplex stdio subscriptions; see [MCP interactions](./mcp-interactions.en.md). New [live HTTP transports](./mcp-http-interactions.en.md) cover 2026 POST subscriptions and 2025-11-25 callbacks/explicit GET separately. Tasks, automatic reconnect, OAuth and complete MCP sandbox binding remain planned.

### Phase 4: workflows

- Status: the local sequential engine, node-boundary recovery, and bidirectional agent adapters are `Implemented`; explicitly bounded asynchronous DAG concurrency is `Experimental` in the `2.0.0a4` release.
- Implemented DAG, state-graph, and Python APIs sharing `WorkflowEngineProtocol`, events, and results.
- Implemented in-memory/JSONL node checkpoints, explicit pause, restart resume, and boundary cancellation.
- `2.0.0a4` implements `WorkflowCheckpointSummary`, a `WorkflowCheckpointCatalog` query contract separate from the stable store, explicit `module:attribute` definition loading, and CLI/TUI recovery with exact name/version/kind checks. Runtime values are hidden by default, and code loading and execution are confirmed separately.
- Uncertain node execution remains `RESUMING` and rejects automatic replay; arbitrary Python instruction stacks are not restored.
- Implemented `agent_workflow_node()` plus `workflow_start_tool()` / `workflow_resume_tool()` governed by the normal tool permission and per-call approval pipeline. The adapters depend only on public protocols and allow replacement of message, authority-context, and result mapping.
- The `2.0.0a4` release adds `max_parallel_nodes`: ready siblings run concurrently, merge in definition order, reject conflicting state keys, and leave `RESUMING` after failure/cancellation to prevent replay of uncertain side effects. The default remains sequential. It also adds replaceable `WorkflowNodeInvoker` and opt-in `ThreadedWorkflowNodeInvoker` across all bundled frontends and resume paths. Cancellation drains started synchronous calls without forcibly stopping threads or committing cancelled results. The `2.0.0a5` release adds node suspension and `approval_agent_workflow_node()` for exact child-run/call continuation using fresh host authority (`2.0.0a5`, focused regressions passed). The a6 release adds reverse tool continuation; two-layer authorization coordination is also in the a6 release (focused regressions passed). CLI/TUI factory wiring is also covered by focused regressions, and atomic cross-store commit is reserved.

- The `2.0.0a4` release adds `WorkflowPauseSource` and thread-safe `WorkflowPauseController`: exact run IDs pause at committed node/batch boundaries and retain a `PAUSED` checkpoint. Requests must be explicitly cleared before resuming, and committed nodes are not repeated. The source is replaceable without changing the execution contract or checkpoint format. TUI-owned recovery now runs in the background with exactly bound pause controls and optional threaded invocation, clearing each request when the operation ends. The `2.0.0a5` release adds `SQLiteWorkflowPauseController` and CLI request/status/clear plus opt-in observation during recovery; focused regressions pass for these changes. They preserve boundary pause semantics without adding execution ownership or multi-primary recovery; the TUI can opt into combining its UI-owned controller with SQLite. New `AnyWorkflowPauseSource` provides read-only OR composition, and task cleanup never clears external persistent requests.

### Phase 5: local profiles and sandboxing

- Status: unified contracts, Docker provider, explicitly authorized local provider, command-tool binding, and initial agent templates are `Implemented`; broader environment acceptance remains `Planned`.
- Implemented Docker/OCI lifecycle handles, network-off defaults, resource limits, least-privilege arguments, fixed-image policy, and cleanup.
- Implemented `UnsafeLocalSandboxProvider`, constructible only with a runtime authorization object; safe-backend failure never downgrades automatically.
- Implemented `sandbox_command_tool()` through the existing permission, per-call approval, cancellation, and audit pipeline.
- Implemented fully overridable customer-support/RAG and coding `AgentTemplate` values. Templates bind no model, register no tool, and grant neither permission nor local-execution authority.
- The worktree adds the nsjail cgroup v2 provider and legacy skill bridge. A generic hard-resource Wasm provider, network allowlists and broad Windows Docker Desktop/WSL2/Linux acceptance remain; see [sandbox](./sandbox.en.md).

### Phase 6: sharing, interfaces, and evaluation

- Implemented named/versioned `CompositionManifest` values, deterministic encoding/decoding, size bounds, integrity checks, safe preview, and a conflict-safe local version/alias store.
- Composition preview performs no network access, installation, import, or plugin execution. `2.0.0a4` implements Python/W-Agent compatibility and plugin dependency plans over an explicit candidate inventory, plus import-free preview of independent YAML references, explicitly confirmed transactional batch loading, and persistent in-process TUI unload. The `2.0.0a4` release adds a host-supplied exact wheel/SHA-256 closure catalog, redacted install requests with visible index origins, request-digest-bound authorization, Docker installation mounting only a fresh staging directory or explicitly authorized local-sandbox installation, install-tree revalidation, and entry-origin/name/version checks after import but before setup; plugin loading still needs independent confirmation. Online source discovery, automatic locking, automatic upgrades, and silent same-name hot migration remain `Planned`.
- An initial `wagent` CLI (with the `w-agent` alias) and launchable Textual TUI now cover workspace initialization, template listing, safe endpoint probing, composition export/preview/save/list, local session create/show/archive/unarchive, safe cross-session per-agent usage/cost summaries, and offline TUI composition inspection.
- Implemented strict local JSON assembly into provider/routing/ReAct/run/session components for text runs. CLI/TUI require explicit authorization for every call, and credentials resolve only through environment-variable references.
- Implemented host-catalog-bounded configured tool selection, per-command authority grants, separate Python tool-code load confirmation, and CLI approval resume by known session/run/call IDs. Configuration itself cannot import, authorize, or approve a tool.
- Implemented prompt-free agent approval-checkpoint listing in the API, CLI, and TUI. Summaries exclude prompts, argument values, outputs, and credentials.
- Implemented network-free scripted model providers, JSONL recording/sequential replay requiring explicit sensitive-content authorization, and a sequential evaluation runner with replaceable scorers. The CLI reads strict JSON datasets, uses disposable state by default, and reports token completeness, latency, errors, and tool success rate. JSON reports omit prompts, outputs, metadata, and exception bodies by default.
- Implemented a sequential TUI evaluation screen with strict JSON cases, disposable state, one-shot `EVALUATE` authorization, aggregate metrics, and optional privacy-safe reports; prompts and outputs are hidden by default.
- The TUI now implements separately confirmed tool-entry loading, per-run authority, exact session/run/call-ID approval resume, and privacy-safe live RunEvents. Confirmations are not retained, and the UI omits prompts, model text, tool arguments, and tool results.
- Implemented workflow-checkpoint discovery and recovery from an explicitly selected local state root; stores are never copied, merged, or migrated automatically.
- `2.0.0a4` implements configuration-value-free plugin-reference preview, ephemeral CLI validation bound to `--confirm-plugin-code`, and TUI lifecycle controls bound to `LOAD PLUGINS` / `UNLOAD <name>`. The `2.0.0a4` release additionally provides `composition install-plan/install`, `plugin validate-installed`, and TUI locked-install/independent-load entry points. Unattended installation, online source discovery, and automatic upgrades remain `Planned`.
- `2.0.0a4` implements a replaceable `CompositionDependencyResolver`, strict JSON candidate inventories, environment-constraint checks, and per-plugin offline actions. CLI/TUI dependency-plan entry points, plus install-plan entry points in the `2.0.0a4` release, never query the network, install packages, or treat Ready/Installable as code-load authority; only the later exact-confirmation install action permits network and package-code execution.
- Versioned cost aggregation is implemented in evaluation reports, CLI, and TUI. `2.0.0a4` adds a replaceable `EvaluationSuiteRegistry`, versioned support/coding suites, declarative `CaseContractScorer`, `builtin:` resolution, and network-free CLI export. Suites bundle no tool implementations or authority; CLI/TUI model calls, tool-code imports, and one-run permissions remain separately authorized.
- Implemented a strict text-only bridge from legacy `BaseAgent.arun()` to workflow nodes; other old-API bridges remain demand-driven plans rather than a second runtime.

## Reserved without a release phase

The following capabilities are `Reserved`:

- Out-of-process multi-language plugin SDKs.
- A first-party remote-sandbox implementation.
- A complete MCP tool provider.
- Delegation, human-approval coordination and communication across multiple agents; this does not include the existing single-agent/local-workflow approval and recovery paths.
- Nested and distributed workflows.
- Composition-code signing, publishing indexes, and trust networks.
- A complete online evaluation service.
- Specialized modality adapters such as voice; the core multimodal protocol is reserved in the model phase.

## Non-goals

- A hosted W-Agent platform.
- First-release tenancy, organizations, billing, or cloud-account administration.
- Automatically executing third-party code from an imported composition.
- Silently falling back to host execution when an isolated backend is unavailable.
