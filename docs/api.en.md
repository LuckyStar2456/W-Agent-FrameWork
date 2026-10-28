# W-Agent API status and plan

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./api.md)

> Release scope: the new framework core described here is included in 2.1.0. Earlier “unpublished” labels and candidate 2.0.0 metadata below record pre-release stages, not the 2.1.0 package status. See [2.1.0 notes](./releases/2.1.0.en.md); upload status is on [PyPI](https://pypi.org/project/wagent-framework/2.1.0/).

Unpublished M4 adds `ApplicationProject`, `ApplicationOperation`, `ApplicationHost`, `ApplicationCall`, explicit project loading/execution, default Runtime/Workflow compilation/opening and `replace_components()`. CLI/TUI share public entries; 572 stage-related cases pass. See [default assembly](./default-assembly.en.md) for APIs, ownership and compatibility limits.

M5 adds `ApplicationPlugin(..., scope_order=...)`, preserving declared custom scope order during both preflight and startup. Developer examples are not library dependencies; see [tutorials](./harness-development.en.md) and [final acceptance](./harness-acceptance.en.md).

Unpublished M3 adds `Aspect`, `Before`, `Around`, `After`, `OnError`, `Finally`, `AspectDefinition`, `AdviceRef`, `MethodPointcut`, `Invocation`, `InvocationOutcome`, `AspectMatch` and `AspectError`. `AssemblyPlan.aspects`, `compile_assembly(..., aspects=...)` and `ApplicationPlugin(..., aspects=...)` preserve the same aspect assembly. Component `tags` participate in matching; scope `aspect_matches` reports actual matches. See [application aspects](./application-aspects.en.md) for 207 passing stage-related cases and compatibility boundaries.

Unpublished M2 source adds `Bean`, `Configuration`, `scan_components()`, `compile_decorated()` and `compile_configured()`, and completes the top-level `Value` export. `ComponentDefinition.inject(instance, resolved_arguments)` runs after ownership registration and before initialization; `Value(..., required=True)` enables required bindings. See [decorator development](./annotation-development.en.md) for usage, type matching and 142 passing stage cases. These are not released 2.0.0 APIs.

Available in 2.0.0: [durable Run/Session usage links](./service-usage-links.en.md), [structural/overlapping splitting](./knowledge-splitting.en.md) and [raw-archive CLI entries](./knowledge-archive-entries.en.md). Links precede preparation, default splitting preserves v1, and export only creates new files. All are Experimental features included in 2.0.0; see [acceptance and remaining modules](./acceptance-2026-10-01-links-splitting-archives.en.md).

New exports: `ServiceUsageRunLink`, `ServiceUsageLinkStore`, `InMemoryServiceUsageLinkStore`, `SQLiteServiceUsageLinkStore`; `KnowledgeTextSpan`, `KnowledgeSpanSplitter`, `StructureKnowledgeSpanSplitter`; four `KnowledgeArchivePreview/Create/Inspect/ExportRequest` types and `preview_local_knowledge_archive`, `archive_local_knowledge_sources`, `inspect_local_knowledge_archive`, `export_local_knowledge_blob`. Nothing creates stores, runs custom splitters or exports files by default.

New root exports: `KnowledgeArchiveError`, `KnowledgeRawBlob`, `KnowledgeArchiveReceipt`, `KnowledgeRawArchive`, `SQLiteKnowledgeRawArchive`, `archive_knowledge_sources`; `LocalServiceUsageConfig`, `LocalServiceUsageBinding`, `ObservedModelProvider`; `McpStreamingHttpTransport`, `McpLegacyDuplexHttpTransport`.

New worktree sync-management exports: `KnowledgeSyncImportRequest`, `KnowledgeSyncPrepareRequest`, `KnowledgeSyncInspectRequest`, `KnowledgeSyncExecuteRequest`, `KnowledgeSyncRetryRequest`, `KnowledgeSyncReconcileRequest`, the corresponding `import/prepare/inspect/execute/retry/reconcile_local_knowledge_sync` functions, and `knowledge_sync_summary`. CLI/TUI share them; see [sync entries](./knowledge-sync-entries.en.md).

Cross-service observation adds `ServiceUsageError`, `ServiceUsageUnit`, `ServiceUsageRecord`, `ServiceUsageLedger`, `InMemoryServiceUsageLedger`, `SQLiteServiceUsageLedger`, `aggregate_service_usage`, `service_usage_from_budget_entry`, `service_usage_from_run`, `ObservedSharedBudgetController`, `ServiceUsageMeasurement`, `observe_service_call`, `ObservedKnowledgeRetriever` and `ObservedKnowledgeReranker`. All export from `w_agent` without forcing TUI imports; see [usage-ledger boundaries](./service-usage.en.md). These are Experimental features included in 2.0.0 additions, not published a9 APIs.

This document covers implemented APIs in the 2.0.0 source, distinguishing the 1.x compatibility foundation, Experimental features and planned protocols. See the [release record](./acceptance-2026-10-01-stable-release.en.md) for verification scope; the historical [a9 release notes](./releases/2.0.0a9.en.md) do not describe every 2.0.0 API or its acceptance. Planned protocols without implementations are still not importable APIs.

`2.0.0a7` exports `ToolResultEventEncoder`, `TextToolResultEventEncoder`, `ToolResultEventEncodingError` and `normalize_tool_result_event()`, with Agent/local configuration `emit_tool_results` / `max_tool_result_event_bytes` and accumulator `include_tool_results` / `max_tool_result_bytes`. Focused regressions passed; recording and display default to off. See [event replay](./event-replay.en.md).

## 1. Current top-level API

Follow-up exports include `MediaDisplay`, `MediaDisplayLimits`, `MediaPreview`, `MediaDisplayError`, `TerminalMediaDisplay`, `decode_inline_media`, `export_recorded_media`, `safe_media_text` and `PluginReplacementSession`. These provide an offline [media presentation protocol/template](./tui-media.en.md) and a current-process [replacement review controller](./plugin-replacement.en.md). They are Experimental features included in 2.0.0 and do not force Pillow/Textual imports. Knowledge evaluation uses the existing evaluate/Evaluation entries with [per-case query authorization](./knowledge-workflow-evaluation.en.md).

Incremental knowledge adds `KnowledgeImportStore` / `SQLiteKnowledgeImportStore`, `KnowledgeSyncIndex` / `KnowledgeSyncPlan` / `KnowledgeSyncStatus`, `KnowledgeSyncWriter` / `KnowledgeSyncJournal` / `SQLiteKnowledgeSyncJournal`, `QdrantKnowledgeSyncWriter` / `QdrantDeletePlan`, `prepare_knowledge_sync_index` / `execute_knowledge_sync` / `knowledge_sync_point_ids`, `SyncVectorKnowledgeRetriever`, `KnowledgeSyncRetryRecord` / `knowledge_sync_retry_digest` and `KnowledgeSyncError`. This explicit Python API is a separate mutable-index scheme, not an automatic migration of snapshot indexes; see [usage and boundaries](./knowledge-sync.en.md).

The 2026-10-01 worktree adds these importable APIs (`Experimental`, included in 2.0.0, not part of a9):

- Ingestion: `OptionalDocumentKnowledgeParser`, `compare_knowledge_imports`, `prepare_traced_knowledge_import`; [formats and provenance](./knowledge-import-extensions.en.md).
- Retrieval/pipelines: `BM25KnowledgeRetriever`, `HybridKnowledgeRetriever`, `RerankedKnowledgeRetriever`, `knowledge_workflow_node`, `knowledge_evaluation_target`; [retrieval](./knowledge-retrieval.en.md) and [Workflow/evaluation](./knowledge-workflow-evaluation.en.md).
- Index recovery: `SQLiteKnowledgePreparationStore`, `prepare_recoverable_knowledge_plan`, `retry_knowledge_build_batch`; [boundaries](./knowledge-build-recovery.en.md).
- Models: `OpenAIResponsesResumableProvider`, `ResponsesCheckpointStore`, `ResponsesCheckpoint`, `SqliteResponsesCheckpointStore`; [continuation and images](./responses-continuation.en.md).
- MCP: `McpClientHandlers`, `McpRequestHandler`, `McpNotificationHandler`, `McpDuplexStdioTransport`; [active interactions](./mcp-interactions.en.md).
- Sandbox: `NsJailSandboxProvider`, `NsJailSandboxHandle`, `ProviderSkillSandbox`; [sandbox boundaries](./sandbox.en.md).
- Plugins: `PluginReplacementPlan`, `PluginReplacementError` and `PluginManager.plan_replacement()` / `replace()`; [explicit replacement](./plugin-replacement.en.md).

See the [unified acceptance report](./acceptance-2026-10-01.en.md) for implementation versus offline and real-environment acceptance.

The framework provides `KnowledgeIndexBuild`, `KnowledgeBuildStore` / `SQLiteKnowledgeBuildStore`, `assemble_knowledge_build` / `knowledge_build_from_json`, `knowledge_build_progress` / `inspect_knowledge_build_progress`, `execute_knowledge_build_batch` and local create/review entries. Frozen `KnowledgeBuildExecuteRequest` and `execute_local_knowledge_build_batch` add single-batch execution; create/review/execute have CLI and TUI entries, separate build/artifact approval, stable attempt identities and no automatic replay. Local/mock regressions passed; included in 2.0.0 and outside a9; see [build manifests](./knowledge-builds.en.md).

The framework provides optional `KnowledgeIndexPlanCatalog`, `KnowledgeIndexPlanInfo`, `KnowledgePlanCoverage`, SQLite `list_plans()`, `review_knowledge_plan_catalog`, plus `KnowledgePreparationBatch` and `plan_missing_knowledge_batches` / `review_missing_knowledge_batches`. Catalog uses CLI/TUI; batch advice uses API/CLI/TUI with three adjustable partition bounds, without automatic execution. Local/mock regressions passed; included in 2.0.0 and outside a9; see [catalogs/batches](./knowledge-plan-catalog.en.md).

The framework provides `KnowledgeIndexHostOptions` / `KnowledgeIndexHostBinding`, `KnowledgePlanPrepareRequest` / `KnowledgePlanExecuteRequest`, `knowledge_index_host_scope`, `prepare_local_knowledge_plan` / `execute_local_knowledge_plan`: shared host lifecycle and independent consent now wired into separate CLI/TUI prepare-save/approved-execute actions. Included in 2.0.0; local/mock regressions passed and outside a9; see [plan actions](./knowledge-plan-actions.en.md).

`PreparedKnowledgeIndexPlan`, `KnowledgeIndexPlanStore`, `SQLiteKnowledgeIndexPlanStore`, `prepare_knowledge_index_plan`, `prepared_knowledge_plan_from_json`, `execute_prepared_knowledge_plan` and `inspect_stored_knowledge_plan` provide underlying exact-vector planning/staging APIs, also locally/mock-tested worktree source. See [exact plans](./knowledge-index-plans.en.md).

The framework provides `KnowledgeIndexReviewRequest`, `knowledge_index_review_view` and `review_local_knowledge_index` for exact-manifest journal review and host-evidence reconciliation through CLI/TUI. No remote verification or replay. Included in 2.0.0; local/mock regressions passed and outside a9; see [index journal management](./knowledge-index-management.en.md).

The framework provides `LocalKnowledgeRequest`, `manage_local_knowledge`, optional `KnowledgeSnapshotCatalog` / `KnowledgeSnapshotInfo` and SQLite `list_snapshots()`: explicit local import preview/save, read-only catalog and pinned keyword search shared by CLI/TUI management. Included in 2.0.0; local/mock regressions passed and outside a9; see [knowledge management](./knowledge-management.en.md).

The framework provides `LocalKnowledgeConfig`, `LocalKnowledgeBinding`, Runtime `knowledge.binding`, assembly `knowledge_bindings`, and per-call `knowledge_query` / `confirm_knowledge_query` for `run()`/`run_messages()`. CLI/TUI run supports independent host-code/query consent. Configuration alone never retrieves and checkpoint resume does not requery. Included in 2.0.0; local/mock regressions passed and outside a9; see [knowledge assembly](./knowledge-runtime.en.md).

The framework exports `AsyncEmbeddingProvider`, `EmbeddingResult`, `EmbeddingError`, `HttpEmbeddingMapping`, `JsonEmbeddingMapping`, `HttpTextEmbedder`, `OpenAIEmbeddingMapping`, `OllamaEmbeddingMapping`, `openai_compatible_text_embedder()`, `ollama_text_embedder()`, `EmbeddingBudgetMeter` and `SharedBudgetTextEmbedder`. Single-text HTTP mapping, structured service usage and optional shared budgeting do not automatically choose models, retry or create dedicated Runtime configuration. Included in 2.0.0; local/mock regressions passed and outside a9; see [embeddings](./embeddings.en.md).

The framework exports `KnowledgeFileImporter`, `LocalTextKnowledgeImporter`, `KnowledgeFileTextParser`, `Utf8KnowledgeFileParser`, `KnowledgeFileRecord`, `KnowledgeTextImport` and `KnowledgeFileImportError`: explicit bounded local file/directory reads, replaceable parsing, source fingerprints and snapshot integration. No automatic persistence, embedding, indexing or sandbox isolation. Included in 2.0.0; local/mock regressions passed and outside a9; see [local imports](./knowledge-files.en.md).

The framework exports `KnowledgeIndexManifest`, `knowledge_index_manifest()`, `KnowledgeIndexAttempt`, `KnowledgeIndexJournalSnapshot`, `KnowledgeIndexJournal`, optional `KnowledgeIndexReconciler` and `KnowledgeIndexReconciliation`, `SQLiteKnowledgeIndexJournal`, `KnowledgeIndexJournalError` and `journaled_knowledge_upsert()`. It provides explicit pending registration, non-overwritable final observations, separate immutable host-reconciliation decisions, `effective_outcome()` and derived fixed-manifest coverage. It does not retry or verify remote state automatically, or migrate body snapshots. Included in 2.0.0; local/mock regressions passed and outside a9; see [index journals](./knowledge-index-journal.en.md).

The framework exports `KnowledgeVectorIndex`, `knowledge_document_embedding_text()`, `prepare_knowledge_vectors()` and `SnapshotVectorKnowledgeRetriever`. Point IDs bind snapshot digest/host embedding label/dimension; separately authorized batches of up to 128 documents reuse the independent Writer, and retrieval restores original document identities. No automatic index-completeness or actual-model-identity verification. Included in 2.0.0; local/mock regressions passed and outside a9; see [snapshot vectors](./knowledge-vectors.en.md).

The framework exports `KnowledgeTextSplitter`, `Utf8KnowledgeTextSplitter`, `prepare_knowledge_snapshot()`, `KnowledgeSnapshot`, `KnowledgeSnapshotStore`, `SQLiteKnowledgeSnapshotStore` and `KnowledgeStoreError`: pure host-text preparation, user-named versions, explicit creation/writes, identical-save reuse and conflict rejection. Snapshots convert to the existing in-memory document store without automatic latest selection. Included in 2.0.0; local/mock regressions passed and outside a9; see [knowledge preparation/persistence](./knowledge-ingestion.en.md).

The framework exports `knowledge_search_tool(retriever, ...) -> ToolBinding`, with configurable name, permissions, effect class, query/document/JSON byte bounds and timeout. Defaults are `EXTERNAL` and `knowledge.read`; existing tool permission/approval and named assembly apply. No automatic import, indexing or accounting. Included in 2.0.0; local/mock regressions passed and outside a9; see [knowledge tools](./knowledge-tools.en.md).

Worktree additions export `KnowledgeDocument`, `AsyncKnowledgeDocumentStore`, `InMemoryKnowledgeDocumentStore`, `KnowledgeRetriever`, `KeywordKnowledgeRetriever`, `VectorKnowledgeRetriever`, `AsyncKnowledgeContextPolicy` and `KnowledgeRetrievalError`. The existing `history_policy` hook explicitly composes text knowledge, retains sources and rejects invalid/out-of-scope results, without automatic indexing/accounting. Included in 2.0.0; local/mock regressions passed and outside a9; see [knowledge context](./knowledge-context.en.md).

Worktree additions export `DenseVectorPoint`, `prepare_qdrant_history_points()`, `qdrant_history_embedding_text()`, `QdrantVectorWriter`, `QdrantUpsertPlan`, `QdrantWriteResult` and `VectorIndexWriteError`. History embedding and remote overwrites require separate consent. Pure plans bind exact targets/vectors; unknown writes are never automatically retried. Collection creation, synchronization and accounting are not automatic. Included in 2.0.0; local/mock regressions passed and not part of a9; see [explicit vector writes](./vector-indexing.en.md).

The worktree additionally exports `AsyncTextEmbedder`, `DenseVectorSearch`, `VectorSearchMatch`, `VectorRetrievalError`, `QdrantVectorSearch`, `QdrantSessionHistoryRetriever` and `qdrant_history_point_id()`. Replaceable vector lookup/embedding plugs into the existing async history-selector protocol. Qdrant returns IDs/scores only; the adapter rechecks the current candidate set. Hosts own indexing, authorization, accounting and borrowed-resource lifecycle; no history upload is automatic. Included in 2.0.0; local/mock regressions passed and not part of a9; see [external vector retrieval](./vector-retrieval.en.md).

a9 shared-budget additions: `SharedBudgetController`, `SharedBudgetMeter`, `InMemorySharedBudget`, `SQLiteSharedBudget`, `SharedBudgetModelProvider`, immutable `SharedBudgetLimits` / `SharedBudgetAmount` / `SharedBudgetReservation` / `SharedBudgetEntry` / `SharedBudgetSnapshot`, and non-retryable `SharedBudgetError`. Wrapping summary/main Providers with the same budget shares reservations. SQLite provides explicit initialization, transactional admission and durable tickets, requiring matching configuration on reopen. Optional `SharedBudgetReconciler` and `SharedBudgetReconciliation` resolve pending/unknown through `reconcile(decision, confirm_inactive=True)`, preserving an immutable receipt in `SharedBudgetEntry.reconciliation`. Hosts must confirm against independent evidence; no automatic verification or replay occurs. 2.0.0a9 Experimental; see a9 release notes for validation; see [shared budgets](./shared-budget.en.md).

a9 Runtime additions export `LocalSharedBudgetConfig(binding)` and `LocalSharedBudgetBinding(controller, meter)`. Optional JSON `shared_budget.binding` selects the host `shared_budget_bindings` catalog passed to either assembly function. Assembly wraps the selected Provider and never downgrades missing bindings. `LocalAgentRuntime.shared_budget_snapshot()` explicitly reads pool totals or returns None when disabled; it neither merges Run/Session statistics nor initializes/closes borrowed budget objects. CLI run/run-resume `--budget-entry` / `--confirm-budget-code` and TUI Run/approval-resume `LOAD BUDGET` add factory lifecycle handling and pool summaries without ticket contents. Evaluation/configured-probe entry points share the factory; one pool spans each batch and saved reports remain unchanged. 2.0.0a9 Experimental; see a9 validation; see [named Runtime bindings](./local-runtime.en.md).

a9 additionally exports `SQLiteSessionSummaryObserver(database_path, operation_id, *, max_runs=1024, max_report_bytes=16384, timeout=1.0)`. It implements the existing `SessionSummaryObserver` and offers `initialize()`, `record()`, `reports()` and `snapshot(main_result=None)`. Initialization explicitly writes, reads never create missing files, and main results are not persisted. Experimental, 2.0.0a9; see release validation; see [SQLite summary reports](./context-accounting.en.md).

Usage additions export `InMemorySessionSummaryObserver`, `SessionPreparationUsage`, `SessionUsageError` and `aggregate_session_preparation_usage(reports, main_result=None)` (2.0.0a8; focused regressions passed). The observer updates idempotently by summary Run ID; `snapshot(main_result)` explicitly combines one cumulative main result. Missing reports are not zeros, and cost is grouped by currency/price version. This is not a shared budget controller and does not automatically modify Runtime/Session totals. See [context usage aggregation](./context-accounting.en.md).

Model-summary additions export `AgentSessionHistorySummarizer`, `SessionSummaryObserver`, `SessionSummaryRunReport` and `SessionSummaryError` (2.0.0a8; focused regressions passed). The summarizer creates an independent Run through an injected Agent Loop, with a required async observer receiving prompt-free started/terminal reports. Defaults allow one step and no tool calls and require Usage; its token/cost budgets are independently configurable, not shared with the main Run. See [metered model summaries](./sessions.en.md) for usage and failure/cancellation reconciliation boundaries.

a8 also exports `AsyncSessionHistoryPolicy`, `AsyncSessionHistoryRetriever`, `AsyncSessionHistorySummarizer`, `AsyncRetrievedSessionHistoryPolicy` and `AsyncSummarizedSessionHistoryPolicy` (2.0.0a8 Experimental; focused regressions passed). Manager/Runtime `history_policy` accepts synchronous or async protocols; `conversation(..., cancellation=...)` can cancel a pending projection. Templates require explicitly injected async callbacks, default to a 30-second callback timeout, load no external clients and never retry automatically. Preparation costs are not automatically included in the main Agent budget; see [async history and accounting boundaries](./sessions.en.md).

a8 Experimental run additions: parser `allow_message_fields=False`, `InputManifestLimits.max_message_field_bytes` (default 65536), per-call `input_recorder` on Runtime `run()` / `run_messages()` and SessionManager `run_agent()`, plus `BuiltinSessionHistoryOptions.include_name/include_metadata` (recorded mode only). They do not mutate the shared default recorder or derive authority from fields. CLI/TUI separately select current sending, additional recording and history reuse; see [run options](./local-runtime.en.md). These interfaces require a8 or later.

a8 also exports `build_session_message_projector(include_text=False, input_media=None, include_name=False, include_metadata=False)`, sharing default-hidden projection assembly between CLI/TUI and Python hosts. It grants no read/send authority; selecting fields or media returns a wrapper-aware projector and changed disclosure settings change snapshot identity. 2.0.0a8 Experimental; focused regressions passed; see [Replay field disclosure](./event-replay.en.md).

Message-field preservation adds `MessageFieldsSessionInputRecorder`, `MessageFieldsSessionInputDecoder`, `SessionMessageFieldsDecoder` and `MessageFieldsSessionMessageProjector` (2.0.0a8; focused regressions passed). `RecordedSessionHistoryPolicy` separately accepts `fields_decoder` and a field-size limit; content decoding never implicitly authorizes field reuse. Recording, display and sending are independently selected, with name/metadata hidden by default; see [Session field boundaries](./sessions.en.md).

`BuiltinSessionHistoryOptions` is an a8 Experimental convenience object with focused regressions passing. `runtime_options()` returns fresh Runtime kwargs, not authority; CLI/TUI independently obtain execution, recording, media-reuse or text-transformation consent. `text` preserves Runtime defaults, `none` sets `include_history=False`, and other modes construct their built-in policies. Python hosts can bypass this object and inject any policy-protocol implementation.

a8 additionally exports `SessionHistoryTurn`, `SessionHistoryLimits`, `SessionHistoryRetriever`, `SessionHistorySummarizer`, `KeywordSessionHistoryRetriever`, `RetrievedSessionHistoryPolicy`, `ExtractiveSessionHistorySummarizer` and `SummarizedSessionHistoryPolicy`. These are a8 Experimental local text-context templates with per-invocation queries and explicitly injected callbacks, without model invocation or Session rewriting. See [Session retrieval and summaries](./sessions.en.md).

Structured running adds `InputManifestLimits`, `InputManifestError`, `load_input_manifest()`, `input_manifest_from_mapping()` and `LocalAgentRuntime.run_messages()` (2.0.0a7; focused regressions passed). Text/message runs accept `record_inputs`, `include_history` and `history_policy`; CLI adds `--input-file`; TUI Run supports the same media input and separate recording/history consent. See [local Runtime](./local-runtime.en.md).

Session input recording (2.0.0a7; focused regressions passed) adds `SessionInputRecorder`, `StandardSessionInputRecorder`, `SessionInputRecordingError` and `session_input_to_dict()`. `SessionManager(..., input_recorder=...)` replaces the encoding policy; `run_agent(..., record_inputs=True)` independently enables recording. `SessionMessage.recorded_input` holds deeply immutable codec-tagged finite JSON. The first actual record upgrades the Session to schema 2; schema 1 remains readable. Default history stays text-only without automatically resending media. See [Session recording boundaries](./sessions.en.md).

History and input display add `SessionHistoryPolicy`, `TextSessionHistoryPolicy`, `RecordedSessionHistoryPolicy`, `SessionInputDecoder`, `StandardSessionInputDecoder`, `SessionInputDecodingError` and `RecordedSessionMessageProjector` (2.0.0a7; focused regressions passed). `conversation()` / `run_agent()` accept an explicit per-call `history_policy`, defaulting to text only. Recording, display and model sending are independent; see [Session policies](./sessions.en.md).

Session display APIs (2.0.0a7; focused regressions passed) add `SessionEventReplay`, `SessionRecordSource`, `SessionRunReplaySource`, `SessionMessageProjector`, `TextSessionMessageProjector`, `SessionRunView`, `SessionReplaySnapshot`, `SessionReplayPage` and `SessionReplayError`. `RunEventPageSource` additionally generalizes accumulator readers to a replaceable page protocol; existing `RunEventReplay` remains supported. Views read registered Runs' recorded content without changing Session schema, model input or execution state. See the [Session guide](./sessions.en.md).

Status: the table includes released and a6 APIs; not every export is an accepted `Implemented` capability. `w_agent.__init__` currently exports these primary types:

| Group | API |
|---|---|
| Agent | `BaseAgent`, `LegacyAgentAdapter`, `AgentDefinition`, `AgentLoop`, `ReactAgentLoop`, `RunContext`, `RunEvent`, `RunResult`, `RunStore`, `RunEventSource`, `PagedRunEventSource`, `RunEventReplay`, `RunEventCursor`, `RunEventPage`, `safe_run_event_to_dict`, `RunCheckpointSummary`, `JsonlRunStore`, `TokenBudget`, `TokenEstimator`, `TokenEstimate`, `CharacterTokenEstimator`, `CostBudget`, `CostEstimator`, `CostEstimateRequest`, `CostEstimateRoute`, `CostEstimate`, `PricingCostEstimator` |
| Session | `SessionManager`, `RunEventCallback`, `SessionRecord`, `SessionRunRecord`, `AgentUsageSummary`, `InMemorySessionStore`, `JsonSessionStore` |
| Local assembly | `LocalRuntimeConfig`, `LocalToolConfig`, `LocalPricingConfig`, `LocalProviderAssembly`, `LocalAgentRuntime`, `load_local_runtime_config`, `assemble_local_provider`, `assemble_local_runtime` |
| Container | `BeanFactory`, `BeanDefinition`, `Scope` |
| Configuration | `DynamicConfigManager` |
| Decorators | `AgentComponent`, `ServiceComponent`, `ToolComponent`, `Component`, `Autowired`, `Qualifier` |
| Lifecycle | `PostConstruct`, `PreDestroy`, `LifecycleManager`, `GracefulShutdownManager` |
| Events | `EventBus`, `Event`, `ConfigChangedEvent` |
| AOP/resilience | `Retry`, `CircuitBreaker`, `AspectJPointcut`, advice types, `ProxyFactory`, `ResilienceManager` |
| Observability | `global_tracer`, `CompositeHealthIndicator`, `HealthIndicator`, `LLMHealthIndicator` |
| Distributed | `RedisDistributedLock`, `LockRenewalPool` |
| Skills/sandbox | `Skill`, `WasmSkillSandbox`, `NsJailSkillSandbox`, `SandboxProvider`, `DockerSandboxProvider`, `UnsafeLocalSandboxProvider` |
| Tools/scanning | `ToolRegistry`, `ToolExecutor`, `ToolCall`, `ToolResult`, `python_tool`, `load_tool_entries`, `LangChainToolAdapter`, `ParallelASTScanner`, `Doctor` |
| Microkernel | `PluginManager`, `Registry`, `ScopePath`, `EventDispatcher`, and related types |
| Models/pricing | `ModelProvider`, `ModelRegistry`, `ModelRequest`, `StreamEvent`, `OpenAICompatibleProvider`, `HttpModelProvider`, vendor mappings/templates, `ModelPrice`, `PriceTable`, `PricingResolver`, `PricingCatalog`, `ModelCost`, and related types |
| Routing/invocation/probing | `ModelRouter`, `ModelExecutor`, `InvocationPolicy`, `YamlRoutingPolicy`, `EndpointProbe`, `ModelProviderProbe`, and related types |
| Workflow | `WorkflowEngineProtocol`, `LocalWorkflowEngine`, all three definitions, `WorkflowStore`, `JsonlWorkflowStore`, and related types |
| Testing/evaluation | `ScriptedModelProvider`, `RecordingModelProvider`, `ReplayModelProvider`, `EvaluationDataset`, `EvaluationSuite`, `EvaluationSuiteRegistry`, `LocalEvaluationRunner`, scorers, and the JSON reporter |

The retained 1.x agent abstraction is:

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` is not integrated with the new model protocol. The new `AgentLoop`, ReAct/tool, and workflow runtimes are available independently. ReAct approval checkpoints, workflow node checkpoints, and the local persistent session lifecycle/cross-run text context are implemented. The `2.0.0a4` release also contains `RunEventReplay.page()` for run-bound cursor paging; the a6 release adds read-only multimodal/tool-delta accumulation (focused regressions passed), while optional tool-result bodies are a a7 addition (2.0.0a7, focused regressions passed) and read-only rich Replay UI is available in a7; the worktree adds explicitly disclosed character-image/WAV presentation and exports (see tui-media.en.md).

Strict local JSON can be assembled by `load_local_runtime_config()` and `assemble_local_runtime()` into a built-in provider template, single-provider route, bounded invocation policy, selected ToolBindings, ReAct loop, RunStore, and SessionStore. `assemble_local_provider()` only constructs a provider with asynchronous cleanup lifecycle; it performs no registration or I/O, leaving probe and registration policy to the application. Both `LocalProviderAssembly` and `LocalAgentRuntime` support asynchronous contexts and idempotent cleanup. Configuration accepts only `api_key_env` credential references and can only select from a host catalog; it cannot import, authorize, or approve tools. `LocalAgentRuntime.resume()` and `wagent run-resume` resume approval checkpoints by exact call ID. CLI import of developer tool code additionally requires independent `--confirm-tool-code` authorization. See [locally configured runtime](./local-runtime.en.md).

The a6 release also exports `ToolContinuation`, `ToolContinuationError`, `ToolResumeHandler`, and optional `ResumableToolExecutorProtocol` (focused regressions passed). `ToolBinding.resume_handler` and `ToolExecutor.resume()` provide a separate continuation entry point. `RunCheckpoint.tool_continuation` persists unfinished-tool tickets using schema 2; checkpoints without tickets retain schema 1. Resume requires exact-call authorization and policy allowance, with no fallback to restarting the initial handler. The a6 release also exports `WorkflowToolReference` and `resumable_workflow_tool()` for reference-first Workflow tool continuation; two-layer approval coordination services are now in the a6 release (focused regressions passed), while UI guidance is also present in the a6 release (focused regressions passed). See [tool continuation](./tools.en.md).

Two-layer coordination (a6, focused regressions passed) also exports `WorkflowToolApprovalReview`, `WorkflowToolApprovalAssemblyContext`, `WorkflowToolApprovalFactory`, `WorkflowToolApprovalError`, `review_workflow_tool_approvals()`, `resume_workflow_tool_approval()`, and `open_workflow_tool_approval_entry()`. Read-only matching grants nothing; resume accepts independent parent/child permissions and drives only parent Agent recovery. Factories must faithfully assemble the three stores and temporary grants. The two-layer CLI is now in the a6 release (focused regressions passed); TUI guidance is also present in the a6 release (focused regressions passed); see [two-layer approval coordination](./workflows.en.md).

Display-state reconstruction (a6, focused regressions passed) exports `RunEventReducer`, `RunEventAccumulator`, `RunReplaySnapshot`, `ReducedRunEventPage`, and `TranscriptRunEventReducer`. Snapshots bind Run, cursor and reducer configuration; defaults hide text/tool content and failed pages leave the input snapshot unchanged. This neither resumes execution nor authorizes tools. See [event replay](./event-replay.en.md).

## 2. Next-generation export strategy

Status: `Implemented` / `Planned`. Microkernel, model, tool, `AgentLoop`, and `WorkflowEngineProtocol` foundations are exported directly. Unpublished M1 source adds `ApplicationContext`, `ApplicationScope`, `ApplicationState`, `ApplicationLifecycleError`, plus `ComponentDefinition`, `BorrowedComponent`, `ComponentRef`, `AssemblyComponent`, `AssemblyPlan`, `AssemblyDefinitionError` and `compile_assembly()`. Bridge APIs are `ApplicationPlugin`, `CapabilityImport`, `CapabilityExport` and `borrow_legacy_singletons()`; configuration preflight uses `ConfigurationField`, `ConfigurationSchema` and definition-level `validate_arguments`. See [assembly and lifecycle](./application-assembly.en.md). The previously planned `Application` symbol is not exported. Plugin bridging does not imply complete decorator or AOP integration.

Next-generation APIs are exported directly from `w_agent`; there is no `w_agent.v2` namespace:

```python
from w_agent import AgentLoop, LocalWorkflowEngine, ModelProvider
```

Until migration is complete, top-level exports avoid ambiguous behavior between old and new objects with the same name. Old objects remain through a compatibility module or adapter.

## 3. Microkernel protocols

Status: `Implemented` in `2.0.0a1`.

```python
class Plugin(Protocol):
    spec: PluginSpec

    async def load(self, context: PluginContext) -> None: ...
    async def unload(self) -> None: ...


class Registry(Protocol):
    def register(self, contribution: Contribution) -> Registration: ...
    def resolve(self, capability: CapabilityKey, scope: ScopePath) -> object: ...
```

`Registration.dispose()` is idempotent. When loading fails, the lifecycle manager removes every registration produced by that load attempt.

Current exports also include `PluginManager`, `PluginContext`, `FunctionPlugin`, `CapabilityDeclaration`, `CapabilityRequirement`, `Contribution`, `RegistryView`, `ScopePath`, `EventDispatcher`, YAML-reference loading, and entry-point discovery APIs. In the `2.0.0a4` release, `load_plugin_references(..., pre_load_validator=...)` lets a host inspect an imported plugin before its setup executes. Installed-plugin loading uses it to check entry-module origin and plugin name/version. Import itself remains a code-execution boundary.

## 4. Model protocols

Status: `Implemented` in Phase 2A.

```python
class ModelProvider(Protocol):
    async def list_models(self) -> tuple[ModelDescriptor, ...]: ...
    async def resolve(self, model: str) -> ModelDescriptor: ...

    def stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[StreamEvent]: ...
```

`StreamEvent` covers content-block start/delta/end, text/tool-call deltas, usage, normalized errors, and finish. `TokenUsage` normalizes input, output, and cached-input tokens and exposes `total_tokens` without double-counting the cached subset; `ModelResponse.usage_reported` distinguishes omitted metadata from a real zero report. `collect_stream()` validates block ordering and an explicit terminal event. A provider reports unsupported standard fields and never silently ignores them.

`OpenAICompatibleProvider` implements `/models` and streaming `/chat/completions` with a replaceable `OpenAICompatibleTransport`. Generic `HttpModelProvider` exposes `HttpRequest`, `HttpStreamFrame`, `HttpProviderMapping`, `HttpStreamDecoder`, and `HttpProviderTransport`; the default `HttpxProviderTransport` supports JSON, SSE, and NDJSON.

`AnthropicMessagesMapping`, `GeminiGenerateContentMapping`, `OllamaChatMapping`, `QwenDashScopeMapping`, and `OpenAIResponsesMapping` implement native protocols. `ProviderTemplateRegistry` includes OpenAI Responses, Anthropic, Gemini, Ollama, Qwen-native, DeepSeek, GLM, Qwen-compatible, vLLM, and Turbo AI/SIAM.AI templates; `VllmProvider` adds vLLM-specific Chat Completions parameters. Default HTTPX implementations are in the `models` extra.

## 5. Routing protocol

Status: `Implemented` for Phase 2A policy/decisions and Phase 2B collecting/event-pass-through invocation.

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` contains candidates, rejection reasons, scores, the selected route, fallback routes, and the policy version, but no prompt plaintext. `WeightedRoutingPolicy` and the `yaml.safe_load`-based `YamlRoutingPolicy` produce the same type. `ModelRouter` reads the current model catalog and applies a policy; it still does not execute providers directly.

`ModelExecutor.invoke()` consumes a decision and returns `ModelInvocationResult`; `InvocationPolicy` bounds per-attempt timeout, retry count, route count, and deterministic backoff. `ModelExecutor.stream()` returns a single-use `ModelStreamExecution` that validates and yields events with `ModelStreamValidator`; policy-driven retry/failover is allowed before the first visible event. The default `max_stream_replays=0`; callers may explicitly pass `VerifiedTextPrefixRecovery` or another `StreamRecoveryStrategy` for bounded same-route replay, prefix verification, and suffix deduplication of one text block. Such replay can incur another charge and is not provider-native cursor continuation. `AttemptRecord` records emitted-event count plus provider-reported TokenUsage and completeness, but no prompt or credential. A final failure raises `ModelInvocationError` with the decision and every completed attempt.

The `2.0.0a4` release also exports `CursorStreamItem`, `CursorResumableModelProvider`, and `NativeCursorRecovery`. When a caller explicitly passes `NativeCursorRecovery(max_resumes=N)` to `ModelExecutor.stream()`, only a provider implementing exact after-event cursors may continue the same generation on the same route; cursor reuse fails closed. Bundled vendor templates do not yet implement native cursors, the Agent loop does not enable the strategy by default, and no cross-process cursor persistence exists. Usage missing from a failed attempt remains unknown.

## 6. Probe protocols

Status: `Implemented` as a Phase 2A foundation.

- `EndpointProbe.probe()`: L1 URL, DNS, TCP, TLS, and HTTP reachability sniffing; the target identifier strips credentials, query data, and fragments.
- `ModelProviderProbe.probe()`: L2/L3 provider access and model-catalog checks.
- `ProbeMode.ACTIVE`: runs an L4/L5 minimal generation and stream-protocol check only with `allow_active=True`.
- `ProbeMode.CAPABILITY`: currently reports L6/L7 declarations as `SKIPPED`; it never presents declarations as active verification.
- `ProbeCache` and `PeriodicProbeService`: shared building blocks for manual and periodic probes.
- `ModelRegistrationProbeService` and `ProbeHealthBridge`: explicit register-and-safe-probe wiring plus external routing-health projection; direct `ModelRegistry.register()` performs no I/O. Credential-free L1 and configured safe/active provider CLI/TUI entry points are implemented; active mode requires explicit per-run authorization.

## 7. Agent protocol

Status: `Implemented` for the run contracts and single-agent ReAct foundation.

```python
class AgentLoop(Protocol):
    async def run(
        self, definition: AgentDefinition, context: RunContext
    ) -> RunResult: ...

    def stream(
        self, definition: AgentDefinition, context: RunContext
    ) -> AgentExecution: ...
```

`ReactAgentLoop` is an ordinary implementation built only on public model/tool contracts and can be replaced as a whole through the same protocol. It runs a bounded model/tool cycle, appends through `RunStore` before event visibility, and returns `pending_tool_call` plus `checkpoint_id` when approval is required. `RunStore.list_checkpoints()` exposes `RunCheckpointSummary` without prompts, argument values, or outputs. `AgentDefinition.emit_text_deltas=True` explicitly switches to the safe model stream and produces persisted `MODEL_TEXT_DELTA` events; collecting mode remains the default, and the TUI never renders delta bodies. `TokenBudget` provides cumulative token limits; construction may inject a `TokenEstimator` for pre-call protection and visibility through `TOKEN_ESTIMATED`, `TOKEN_ESTIMATE_UNAVAILABLE`, and `TOKEN_BUDGET_WARNING`. `CharacterTokenEstimator` is an explicit opt-in heuristic template that rejects image/audio input and never claims exact tokenizer behavior. `CostBudget` combines with a replaceable `PricingResolver` and application-supplied versioned `PriceTable` for cost metering and hard stops. Explicit pre-call protection may inject a `CostEstimator`; the default `PricingCostEstimator` derives `COST_ESTIMATED`, `COST_ESTIMATE_UNAVAILABLE`, and `COST_BUDGET_WARNING` from a prompt-free route/token/replay envelope. `TOKEN_USAGE`/`COST_USAGE`, `RunResult`, and checkpoints expose and preserve token values, costs, attempt ledgers, and completeness. `SessionManager.run_agent()`/`resume_agent()` accept an optional synchronous or asynchronous `RunEventCallback` and project live events in public stream order; the built-in ReAct loop persists each event before exposing it. The a6 release's `RunEventReplay.page()` reads only persisted events and returns a `RunEventPage` plus next cursor without executing models or tools; the caller owns raw-content authorization and redaction. `SessionManager.agent_usage()` returns prompt/output-free `AgentUsageSummary` values with cross-session token, cost, and completeness totals by agent, excluding archived sessions by default. `customer_support_agent()` and `coding_agent()` build fully overridable ordinary definitions and bind no model, tool, or authority. See [Agent runtime](./agents.en.md) and [Session lifecycle](./sessions.en.md).

The `2.0.0a4` release also adds independent `AgentDefinition.emit_tool_call_deltas=True`, persisting raw `MODEL_TOOL_CALL_DELTA` argument fragments from the model stream. Text streaming does not enable it implicitly. The default CLI/TUI safe projection hides call IDs, tool names, and arguments; applications still control access to raw RunEvents.

`RunEventReplay.projected_page()` returns `ProjectedRunEventPage` and uses `SafeRunEventProjector` by default; callers may instead pass an application projector satisfying `RunEventProjector`. Output must be a JSON-compatible object or the operation fails closed with `RunStoreError`. Raw `page()` remains available for authorized low-level consumers.

`FieldPolicyRunEventProjector` plus `RunEventFieldPolicy` provides a default-deny declarative allow/fixed-mask policy for top-level data fields. Rules use exact `RunEventType` members (or their value strings), with `"*"` only as fallback. `NestedFieldRunEventProjector` plus `RunEventPathRule`/`RunEventPathAction` copies, renames, or fixed-masks nested object/array paths into a new nested object. Arbitrary computation still uses an ordinary custom `RunEventProjector`.

`AgentDefinition.emit_output_blocks=True` explicitly persists image/audio model outputs accepted by the default encoder. `ModelOutputEventEncoder` is replaceable; `StandardMultimodalEventEncoder` produces `MODEL_OUTPUT_BLOCK` with a bounded inline body and fails closed as `MODEL_OUTPUT_BLOCK_FAILED` / `OUTPUT_EVENT_ERROR`. `MultimodalRunEventProjector` separates metadata, URL, and actual inline-body disclosure through `MediaProjectionMode.METADATA`, `REFERENCES`, and `CONTENT`, with a replaceable fallback for non-media events. Default CLI/TUI views request no media body.

## 8. Workflow protocol

Status: `Implemented` for Phase 4 local sequential execution and node-boundary recovery; explicitly bounded asynchronous DAG concurrency is `Experimental` in the `2.0.0a4` release.

External boundary pause is also in the `2.0.0a4` release: inject `WorkflowPauseSource` via `LocalWorkflowEngine(pause_source=...)`, or use the bundled `WorkflowPauseController.request_pause(run_id)` / `clear(run_id)`. Requests are isolated by run ID, take effect after the current node/batch, and do not turn completed or failed execution into a pause. Clearing a request does not resume execution. Existing `start()` / `resume()` and checkpoint formats stay unchanged. The TUI exposes a pause control for recovery tasks owned by this UI; CLI and cross-process controls are included in a5 through the SQLite source described below.

The `2.0.0a4` release also provides `WorkflowNodeInvoker`, `InlineWorkflowNodeInvoker`, and `ThreadedWorkflowNodeInvoker`. `LocalWorkflowEngine(node_invoker=...)` replaces invocation across all bundled workflow frontends and resume paths. Inline remains the default; synchronous handlers may explicitly run in threads. Thread cancellation waits for the synchronous call to exit before propagating cancellation and retaining an uncertain checkpoint, so handlers need their own I/O timeouts. Invocation policy is not persisted in checkpoints and must be reassembled for recovery.

```python
class WorkflowEngineProtocol(Protocol):
    async def start(
        self, definition: WorkflowDefinition, context: WorkflowContext
    ) -> WorkflowResult: ...


    async def resume(
        self,
        definition: WorkflowDefinition,
        run_id: str,
        *,
        cancellation: CancellationToken | None = None,
    ) -> WorkflowResult: ...
```

`DagWorkflowDefinition`, `StateGraphDefinition`, and `PythonWorkflowDefinition` use the same engine and can be registered by version and scope through `WorkflowRegistry` on the shared microkernel. Nodes return `WorkflowNodeResult` to update state, select a next node, or request a pause. `LocalWorkflowEngine` supports boundary cancellation and writes events/checkpoints through a replaceable `WorkflowStore`; in-memory and JSONL implementations are included. On `2.0.0a4`, the separate `WorkflowCheckpointCatalog.list_checkpoints()` returns `WorkflowCheckpointSummary` without input/state/output/scope/metadata values, leaving the stable `WorkflowStore` contract unchanged. `load_workflow_entry()` / `load_workflow_entries()` import developer `module:attribute` definitions only after explicit application authorization and catalog them by name and version. Recovery guarantees completed node boundaries only and never restores an arbitrary Python instruction stack. An uncertain node remains `RESUMING` and rejects automatic replay. The `2.0.0a4` release explicitly enables bounded concurrent asynchronous DAG frontiers via `LocalWorkflowEngine(max_parallel_nodes=N)`; `N=1` remains the default. `agent_workflow_node()` and `workflow_start_tool()` / `workflow_resume_tool()` provide bidirectional public-protocol adapters. Automatic cascading recovery and nested workflows are not implemented. See [Workflows and node-boundary recovery](./workflows.en.md).

The `2.0.0a5` release (focused regressions passed) also provides `SQLiteWorkflowPauseController(state_root)`, implementing `WorkflowPauseSource.is_pause_requested(run_id)` with `request_pause(run_id)` / `clear(run_id)`. Engine and checkpoint contracts are unchanged. Read failures raise `WorkflowPauseControlError` rather than silently running a node. The CLI opts in with `workflow-resume --enable-pause-control`, with separate request, status, and clear commands. `AnyWorkflowPauseSource(*sources)` provides ordered read-only OR composition; an off-by-default TUI option combines its UI-owned controller with SQLite, clearing only UI-owned requests at task end. Clearing does not resume; status does not prove process liveness. See [cross-process pause](./workflows.en.md).

Workflow approval bridge addition (`2.0.0a5`, focused regressions passed): optional `ResumableAgentLoop` supports child-run continuation. `approval_agent_workflow_node()` validates an `AgentWorkflowApproval` reference through the same `RunStore` and obtains exact-call authority from a host callback. `WorkflowNodeResult(pause=True, suspend=True)` leaves the current node unfinished and emits `NODE_SUSPENDED`. Ordinary `pause=True` and the old adapter are unchanged. Reverse automatic cascading remains pending; see a6 notes for UI wiring; see [Workflow approval cascading](./workflows.en.md).

The a6 release (focused regressions passed) also provides `WorkflowApprovalAssemblyContext`, `WorkflowApprovalFactory`, `WorkflowApprovalResumeError`, `open_workflow_approval_entry()`, and `resume_workflow_approval()`. Factories return async context managers and explicitly receive stores and operation-local authority. The coordinator checks exact linkage and complete checkpoint snapshots before/after assembly, injects one grant into parent recovery, and always clears residual authority. Python hosts authorize code and execution themselves; CLI `checkpoint workflow-approve-resume` requires three independent confirmations. This is neither a sandbox nor a cross-store atomic transaction; see [approval recovery factories](./workflows.en.md).

## 9. Tool protocol

Host approval interfaces (`2.0.0a5`, focused regressions passed): `review_workflow_approvals()` returns read-only `WorkflowApprovalReview` / `WorkflowApprovalLinkStatus` without granting authority. `WorkflowApprovalGrants.grant(reference, scope=..., permissions=..., ttl_seconds=300)` creates an in-memory one-shot grant; pass the callable object explicitly as the approval node's `approval_context`. Consumption is not refunded; `revoke()` / `clear()` are supported. The a5 CLI/TUI provide read-only link review; see above for a6 CLI factory wiring. TUI now uses the same factory service (focused regressions passed).

Status: `Implemented` as the Phase 3 tool-execution foundation.

```python
class ToolPolicy(Protocol):
    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision: ...
```

`ToolRegistry` registers `ToolBinding` entries by version and scope in the unified registry. `ToolExecutor.execute()` resolves, validates, applies policy, handles timeout/cancellation, and records audit. The default `PermissionPolicy` checks locally granted authority; `SideEffectApprovalPolicy` requires per-call ID approval for write, destructive, and external effects. A definition owns no execution policy, and the default executor never retries. `python_tool()`, `http_tool()`, `command_tool()`, `mcp_tool()`, `sandbox_command_tool()`, `McpClient`, `McpStdioTransport`, `McpStreamableHttpTransport`, and `discover_mcp_bindings()` are implemented; the `2.0.0a4` release adds `McpLegacyClient` and `McpLegacyStreamableHttpTransport`. Legacy server-initiated requests, automated MRTR input exchange, and subscription streams remain `Planned`. See [Tool registration, policy, and execution](./tools.en.md).

## 10. Sandbox protocol

Status: `Implemented` for the unified local contract, Docker/OCI, and explicitly authorized local development mode.

```python
class SandboxProvider(Protocol):
    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle: ...
```

`SandboxHandle.execute()` takes a shell-free `SandboxCommand` and returns `SandboxResult`; `close()` converges the container or local handle. `DockerSandboxProvider` defaults to no network, a read-only root filesystem, dropped capabilities, no privilege escalation, CPU/memory/PID limits, and container removal on close or uncertain execution failure. `UnsafeLocalSandboxProvider` is not a security sandbox and accepts only a runtime object created through `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)`; Docker failure never selects it as fallback. Providers join the shared registry through `SandboxRegistry`. New-contract adapters for nsjail/Wasm remain `Planned`; remote sandbox is `Reserved`. See [Sandbox and local execution](./sandbox.en.md).

## 11. Composition protocol

Status: encoding, decoding, safe preview, and the local version store are `Implemented`. `2.0.0a4`'s offline dependency planning and general-plugin confirmation lifecycle are `Experimental`; host-lock-catalog-driven sandboxed package installation is included in `2.0.0a4`. Online source discovery, automatic locking, and automatic upgrades are `Planned`.

```python
code = encode_composition(manifest)
manifest = decode_composition(code)
preview = inspect_composition(code)
CompositionStore(".wagent/compositions").save(manifest, alias="stable")

environment = CompositionEnvironment("3.11.9", "2.0.0a3")
resolver = StaticCompositionDependencyResolver(plugin_candidates)
plan = plan_composition(manifest, environment, resolver)

catalog = load_plugin_install_catalog("install-lock.json")
install_plan = plan_plugin_installations(plan, catalog)  # still fully offline
request = install_plan.requests[0]
authorization = PluginInstallAuthorization.grant(
    request.digest,
    "my-ui",
    acknowledge_network_access=True,
    acknowledge_package_code=True,
)
result = await SandboxPipPackageInstaller(provider, sandbox).install(
    request,
    authorization,
)
# This is the second, independent plugin-code loading boundary:
batch = await load_installed_plugin_references(
    manager,
    (InstalledPluginReference(result),),
)
```

Decode, preview, dependency planning, and install planning perform no network access, install no dependency, load no plugin, and execute no code. Manifests reject secrets, absolute local paths, embedded code, and `UnsafeLocalSandbox` authority; the codec bounds compressed and expanded sizes. Both `CompositionDependencyResolver` and `PackageInstaller` are replaceable. The default installer accepts only exact versions, a complete SHA-256 wheel closure, and source mappings declared by a host catalog; it uses the caller-selected `SandboxProvider` and revalidates the content tree before loading. `PluginInstallAuthorization` binds the full request digest, and successful installation grants no authority to call `load_installed_plugin_references()`. Online catalogs, lock generation, automatic upgrades, and same-name hot migration are not implemented.

## 12. Testing and evaluation API

Status: `Experimental` in `2.0.0a2`.

`ScriptedModelProvider` supplies finite deterministic network-free model turns. `RecordingModelProvider` and `ReplayModelProvider` use `JsonlModelCassette` for complete-turn recording and sequential replay behind explicit sensitive-content authorization. `load_evaluation_dataset()` loads versions and scorer recommendations from bounded strict JSON or a `builtin:` reference; `load_evaluation_cases()` preserves the cases-only compatibility API. `EvaluationSuite`/`EvaluationSuiteRegistry` are replaceable ordinary data and registry contracts; built-in support/coding suites can be exported through `evaluation_suite_to_dict()` or `wagent benchmark export`. `LocalEvaluationRunner` executes cases sequentially against asynchronous targets returning public `RunResult`, with `ExactTextScorer`, `ContainsTextScorer`, declarative `CaseContractScorer`, or custom `EvaluationScorer` implementations. `EvaluationReport`/`JsonEvaluationReporter` aggregate pass rate, token/cost values and completeness, latency, errors, and tool outcomes; reports do not persist prompts, metadata, outputs, or exception bodies by default. CLI/TUI model calls, tool-code imports, and permissions are separately authorized. See [Local testing, model replay, and evaluation](./testing-evaluation.en.md).

## 13. Compatibility API

Status: `Implemented` (`LegacyAgentAdapter`) / `Deprecated` (1.x abstraction).

`LegacyAgentAdapter` wraps 1.x `BaseAgent.arun()` as a workflow node. It performs explicit text argument/result conversion only and does not pretend that legacy agents support streaming, tools, token usage, or checkpoints; non-text input requires a caller-supplied `prompt_mapper`.
