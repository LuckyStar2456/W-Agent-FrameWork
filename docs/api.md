# W-Agent API 状态与规划

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./api.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

未发布 M4 新增 `ApplicationProject`、`ApplicationOperation`、`ApplicationHost`、`ApplicationCall`，以及显式项目加载/执行、默认 Runtime/Workflow 编译与开启、`replace_components()`。CLI/TUI 共用公开入口；572 个阶段相关用例通过。完整接口、所有权和兼容限制见[默认装配](./default-assembly.md)。

M5 补充 `ApplicationPlugin(..., scope_order=...)`，预检和启动均保留声明的自定义层级。开发示例不是库依赖；参见[三条教程](./harness-development.md)和[终验](./harness-acceptance.md)。

未发布 M3 新增 `Aspect`、`Before`、`Around`、`After`、`OnError`、`Finally`、`AspectDefinition`、`AdviceRef`、`MethodPointcut`、`Invocation`、`InvocationOutcome`、`AspectMatch` 和 `AspectError`。`AssemblyPlan.aspects`、`compile_assembly(..., aspects=...)` 和 `ApplicationPlugin(..., aspects=...)` 保留同一切面装配；组件 `tags` 参与匹配，作用域 `aspect_matches` 可查询实际匹配。207 项阶段相关验证及兼容边界见[应用切面](./application-aspects.md)。

未发布 M2 源码新增 `Bean`、`Configuration`、`scan_components()`、`compile_decorated()`、`compile_configured()`，并补齐 `Value` 顶层导出。`ComponentDefinition.inject(instance, resolved_arguments)` 在所有权登记后、初始化前运行；`Value(..., required=True)` 支持严格必填绑定。用法、类型匹配及 142 项阶段验证见[注解开发](./annotation-development.md)。这些不是已发布 2.0.0 API。

现提供 [Run/Session 用量持久关联](./service-usage-links.md)、[结构与重叠分块](./knowledge-splitting.md)、[原始归档 CLI](./knowledge-archive-entries.md)。关联在准备前写入，分块默认保持 v1，导出只创建新文件；均为Experimental（随 2.0.0 发布）。验证与剩余模块见[本轮记录](./acceptance-2026-10-01-links-splitting-archives.md)。

本轮新增导出：`ServiceUsageRunLink`、`ServiceUsageLinkStore`、`InMemoryServiceUsageLinkStore`、`SQLiteServiceUsageLinkStore`；`KnowledgeTextSpan`、`KnowledgeSpanSplitter`、`StructureKnowledgeSpanSplitter`；四个 `KnowledgeArchivePreview/Create/Inspect/ExportRequest` 和 `preview_local_knowledge_archive`、`archive_local_knowledge_sources`、`inspect_local_knowledge_archive`、`export_local_knowledge_blob`。默认不建库、不运行自定义分块代码或导出文件。

新增顶层导出：`KnowledgeArchiveError`、`KnowledgeRawBlob`、`KnowledgeArchiveReceipt`、`KnowledgeRawArchive`、`SQLiteKnowledgeRawArchive`、`archive_knowledge_sources`；`LocalServiceUsageConfig`、`LocalServiceUsageBinding`、`ObservedModelProvider`；`McpStreamingHttpTransport`、`McpLegacyDuplexHttpTransport`。

现提供同步管理公共接口：`KnowledgeSyncImportRequest`、`KnowledgeSyncPrepareRequest`、`KnowledgeSyncInspectRequest`、`KnowledgeSyncExecuteRequest`、`KnowledgeSyncRetryRequest`、`KnowledgeSyncReconcileRequest`，以及对应的 `import/prepare/inspect/execute/retry/reconcile_local_knowledge_sync` 和 `knowledge_sync_summary`。CLI/TUI 共用它们，见[同步入口](./knowledge-sync-entries.md)。

跨服务观测新增 `ServiceUsageError`、`ServiceUsageUnit`、`ServiceUsageRecord`、`ServiceUsageLedger`、`InMemoryServiceUsageLedger`、`SQLiteServiceUsageLedger`、`aggregate_service_usage`、`service_usage_from_budget_entry`、`service_usage_from_run`、`ObservedSharedBudgetController`、`ServiceUsageMeasurement`、`observe_service_call`、`ObservedKnowledgeRetriever`、`ObservedKnowledgeReranker`。均从 `w_agent` 导出，不强制加载 TUI；计量与预算边界见[用量账本](./service-usage.md)。以上为Experimental（随 2.0.0 发布），不属于已发布 a9。

本文覆盖 2.0.0 源码中已实现的 API，并区分 1.x 兼容底座、Experimental 能力与后续计划协议。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)；[a9 发布说明](./releases/2.0.0a9.md)仅用于追溯历史版本，不代表 2.0.0 的全部 API 或验收结论。标记 `Planned` 且尚无实现的协议仍不能作为可用 API 导入。

`2.0.0a7` 新增 `ToolResultEventEncoder`、`TextToolResultEventEncoder`、`ToolResultEventEncodingError`、`normalize_tool_result_event()`，以及 Agent/本地配置的 `emit_tool_results` / `max_tool_result_event_bytes` 与累积器 `include_tool_results` / `max_tool_result_bytes`。针对性回归通过，记录与展示默认关闭，详见[事件回放](./event-replay.md)。

## 1. 当前顶层 API

后续工作区还导出 `MediaDisplay`、`MediaDisplayLimits`、`MediaPreview`、`MediaDisplayError`、`TerminalMediaDisplay`、`decode_inline_media`、`export_recorded_media`、`safe_media_text` 与 `PluginReplacementSession`。前者是无联网/播放的[媒体展示协议与模板](./tui-media.md)，后者是绑定当前进程管理器的[替换复核控制器](./plugin-replacement.md)。均为Experimental（随 2.0.0 发布）；没有强制导入 Pillow/Textual。知识评测沿用 `evaluate`/Evaluation 入口，见[逐用例查询授权](./knowledge-workflow-evaluation.md)。

知识增量另提供 `KnowledgeImportStore` / `SQLiteKnowledgeImportStore`、`KnowledgeSyncIndex` / `KnowledgeSyncPlan` / `KnowledgeSyncStatus`、`KnowledgeSyncWriter` / `KnowledgeSyncJournal` / `SQLiteKnowledgeSyncJournal`、`QdrantKnowledgeSyncWriter` / `QdrantDeletePlan`、`prepare_knowledge_sync_index` / `execute_knowledge_sync` / `knowledge_sync_point_ids`、`SyncVectorKnowledgeRetriever`、`KnowledgeSyncRetryRecord` / `knowledge_sync_retry_digest` 与 `KnowledgeSyncError`。这是显式 Python API 的独立可变索引方案，不自动迁移既有快照索引；[完整用法与边界](./knowledge-sync.md)。

2026-10-01 工作区新增以下可导入 API（均为`Experimental`（随 2.0.0 发布），不属于 a9）：

- 导入：`OptionalDocumentKnowledgeParser`、`compare_knowledge_imports`、`prepare_traced_knowledge_import`；[多格式与追溯](./knowledge-import-extensions.md)。
- 检索与链路：`BM25KnowledgeRetriever`、`HybridKnowledgeRetriever`、`RerankedKnowledgeRetriever`、`knowledge_workflow_node`、`knowledge_evaluation_target`；[检索](./knowledge-retrieval.md)与[Workflow/评测](./knowledge-workflow-evaluation.md)。
- 索引恢复：`SQLiteKnowledgePreparationStore`、`prepare_recoverable_knowledge_plan`、`retry_knowledge_build_batch`；[完整边界](./knowledge-build-recovery.md)。
- 模型：`OpenAIResponsesResumableProvider`、`ResponsesCheckpointStore`、`ResponsesCheckpoint`、`SqliteResponsesCheckpointStore`；[原生续流与图片](./responses-continuation.md)。
- MCP：`McpClientHandlers`、`McpRequestHandler`、`McpNotificationHandler`、`McpDuplexStdioTransport`；[主动交互](./mcp-interactions.md)。
- 沙箱：`NsJailSandboxProvider`、`NsJailSandboxHandle`、`ProviderSkillSandbox`；[沙箱边界](./sandbox.md)。
- 插件：`PluginReplacementPlan`、`PluginReplacementError` 与 `PluginManager.plan_replacement()` / `replace()`；[显式替换](./plugin-replacement.md)。

实现、离线验收及外部环境未验收的区别见[统一验收记录](./acceptance-2026-10-01.md)。

现提供 `KnowledgeIndexBuild`、`KnowledgeBuildStore` / `SQLiteKnowledgeBuildStore`、`assemble_knowledge_build` / `knowledge_build_from_json`、`knowledge_build_progress` / `inspect_knowledge_build_progress`、`execute_knowledge_build_batch` 和本地创建/查看入口。另提供冻结的 `KnowledgeBuildExecuteRequest` 与 `execute_local_knowledge_build_batch`，创建/查看/单批执行均接 CLI 和 TUI；分别核对构建与工件批准，使用稳定批次身份，不自动重发。本地/模拟回归通过，已随 2.0.0 发布，不属于 a9；见[构建清单](./knowledge-builds.md)。

现提供可选 `KnowledgeIndexPlanCatalog`、`KnowledgeIndexPlanInfo`、`KnowledgePlanCoverage`、SQLite `list_plans()`、`review_knowledge_plan_catalog`，以及 `KnowledgePreparationBatch`、`plan_missing_knowledge_batches` / `review_missing_knowledge_batches`。目录接 CLI/TUI，缺失批次建议接 API/CLI/TUI，支持三项分批限额，不自动执行。本地/模拟回归通过，已随 2.0.0 发布，不属于 a9；见[目录与批次](./knowledge-plan-catalog.md)。

现提供 `KnowledgeIndexHostOptions` / `KnowledgeIndexHostBinding`、`KnowledgePlanPrepareRequest` / `KnowledgePlanExecuteRequest`、`knowledge_index_host_scope`、`prepare_local_knowledge_plan` / `execute_local_knowledge_plan`，共用宿主生命周期和独立确认，已接 CLI/TUI 准备保存/授权执行入口。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[计划动作](./knowledge-plan-actions.md)。

`PreparedKnowledgeIndexPlan`、`KnowledgeIndexPlanStore`、`SQLiteKnowledgeIndexPlanStore`、`prepare_knowledge_index_plan`、`prepared_knowledge_plan_from_json`、`execute_prepared_knowledge_plan` 和 `inspect_stored_knowledge_plan` 提供底层精确向量计划与暂存 API；同属已通过本地/模拟回归的工作区源码。见[精确计划](./knowledge-index-plans.md)。

现提供 `KnowledgeIndexReviewRequest`、`knowledge_index_review_view`、`review_local_knowledge_index`，用于精确清单日志查看与宿主证据对账，共用 CLI/TUI 管理入口，不核验远端也不重放。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[索引日志管理](./knowledge-index-management.md)。

现提供 `LocalKnowledgeRequest`、`manage_local_knowledge`、可选 `KnowledgeSnapshotCatalog` / `KnowledgeSnapshotInfo` 和 SQLite `list_snapshots()`。支持显式本地导入预览/保存、只读版本目录和固定版本关键词检索，共用 CLI/TUI 管理入口。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[知识管理](./knowledge-management.md)。

现提供 `LocalKnowledgeConfig`、`LocalKnowledgeBinding`，Runtime 配置 `knowledge.binding`、装配参数 `knowledge_bindings`，以及 `run()`/`run_messages()` 的 `knowledge_query` / `confirm_knowledge_query`。CLI/TUI run 支持独立知识工厂与查询确认；配置本身不触发检索，检查点恢复不重查。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[知识装配](./knowledge-runtime.md)。

现提供 `AsyncEmbeddingProvider`、`EmbeddingResult`、`EmbeddingError`、`HttpEmbeddingMapping`、`JsonEmbeddingMapping`、`HttpTextEmbedder`、`OpenAIEmbeddingMapping`、`OllamaEmbeddingMapping`、`openai_compatible_text_embedder()`、`ollama_text_embedder()`、`EmbeddingBudgetMeter` 和 `SharedBudgetTextEmbedder`。支持单文本 HTTP 映射、结构化服务用量与可选共享预算；不自动选择模型、重试或建立专用 Runtime 配置。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见 [Embedding](./embeddings.md)。

现提供 `KnowledgeFileImporter`、`LocalTextKnowledgeImporter`、`KnowledgeFileTextParser`、`Utf8KnowledgeFileParser`、`KnowledgeFileRecord`、`KnowledgeTextImport`、`KnowledgeFileImportError`。显式限额读取本地文件/目录、可替换解析、来源指纹和快照接线；不自动保存、Embedding 或索引写入，不提供沙箱隔离。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[本地导入](./knowledge-files.md)。

现提供 `KnowledgeIndexManifest`、`knowledge_index_manifest()`、`KnowledgeIndexAttempt`、`KnowledgeIndexJournalSnapshot`、`KnowledgeIndexJournal`、可选 `KnowledgeIndexReconciler` 与 `KnowledgeIndexReconciliation`、`SQLiteKnowledgeIndexJournal`、`KnowledgeIndexJournalError`、`journaled_knowledge_upsert()`。显式登记 pending、记录不可冲突覆盖的最终观察、另存不可覆盖的宿主对账决定、`effective_outcome()` 与固定清单派生覆盖率；不自动重试或核查远端，不迁移正文快照库。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[索引日志](./knowledge-index-journal.md)。

现提供 `KnowledgeVectorIndex`、`knowledge_document_embedding_text()`、`prepare_knowledge_vectors()`、`SnapshotVectorKnowledgeRetriever`。点 ID 绑定快照摘要/宿主 Embedding 标签/维度；显式授权后准备最多 128 篇的批次，复用独立 Writer，检索恢复原始文档身份，不自动核验索引完整性或实际模型身份。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[快照向量](./knowledge-vectors.md)。

现提供 `KnowledgeTextSplitter`、`Utf8KnowledgeTextSplitter`、`prepare_knowledge_snapshot()`、`KnowledgeSnapshot`、`KnowledgeSnapshotStore`、`SQLiteKnowledgeSnapshotStore`、`KnowledgeStoreError`。宿主文本纯准备、用户具名版本、显式建库/写入、相同内容复用与冲突拒绝；快照可转换为既有内存文档存储，不自动选择最新版本。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[知识准备与持久化](./knowledge-ingestion.md)。

现提供 `knowledge_search_tool(retriever, ...) -> ToolBinding`，支持自定义名称、权限、效果声明、查询/文档/JSON 字节限额与超时。默认 `EXTERNAL`、`knowledge.read`，沿既有工具权限/审批与具名装配通道工作；不自动导入、索引或计费。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[知识工具](./knowledge-tools.md)。

现提供 `KnowledgeDocument`、`AsyncKnowledgeDocumentStore`、`InMemoryKnowledgeDocumentStore`、`KnowledgeRetriever`、`KeywordKnowledgeRetriever`、`VectorKnowledgeRetriever`、`AsyncKnowledgeContextPolicy`、`KnowledgeRetrievalError`。通过既有 `history_policy` 显式装配文本知识，保留来源，拒绝非法/越界结果；无自动索引或费用归集。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[知识上下文](./knowledge-context.md)。

现提供 `DenseVectorPoint`、`prepare_qdrant_history_points()`、`qdrant_history_embedding_text()`、`QdrantVectorWriter`、`QdrantUpsertPlan`、`QdrantWriteResult`、`VectorIndexWriteError`。历史嵌入与远端覆盖写入分别确认，纯计划绑定精确目标/向量，未知写入状态不自动重试；不自动建库、同步或计费。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[显式向量写入](./vector-indexing.md)。

工作区另导出 `AsyncTextEmbedder`、`DenseVectorSearch`、`VectorSearchMatch`、`VectorRetrievalError`、`QdrantVectorSearch`、`QdrantSessionHistoryRetriever` 与 `qdrant_history_point_id()`。可替换向量查询/Embedding 接入既有异步历史选择协议，Qdrant 模板只返回匹配 ID/分数，历史适配器再次限制在当前候选集内。宿主负责预建索引、授权、计量与借用资源生命周期；不自动上传历史。已随 2.0.0 发布，本地/模拟回归通过，不属于 a9；见[外部向量检索](./vector-retrieval.md)。

a9 共享调用预算增量：`SharedBudgetController`、`SharedBudgetMeter`、`InMemorySharedBudget`、`SQLiteSharedBudget`、`SharedBudgetModelProvider`，以及不可变 `SharedBudgetLimits` / `SharedBudgetAmount` / `SharedBudgetReservation` / `SharedBudgetEntry` / `SharedBudgetSnapshot` 和不可重试的 `SharedBudgetError`。摘要与主模型通过同一预算的 Provider 包装器共享预留；SQLite 模板显式初始化、事务入场并持久化票据，重开要求配置一致。另有可选 `SharedBudgetReconciler` 与 `SharedBudgetReconciliation`，通过 `reconcile(decision, confirm_inactive=True)` 处理 pending/unknown，并在 `SharedBudgetEntry.reconciliation` 保留不可覆盖回执。只允许宿主按独立证据确认，不自动核查或重放。2.0.0a9 Experimental，验证范围见 a9 发布说明；见[共享预算](./shared-budget.md)。

a9 Runtime 增量导出 `LocalSharedBudgetConfig(binding)`、`LocalSharedBudgetBinding(controller, meter)`；JSON 可选 `shared_budget.binding`，两个装配函数接收宿主 `shared_budget_bindings` 目录并自动包装所选 Provider，缺失绑定不降级。`LocalAgentRuntime.shared_budget_snapshot()` 显式读取池总量或在未启用时返回 None；不并入 Run/Session 统计、不初始化/关闭借用的预算对象。CLI run/run-resume 的 `--budget-entry` 与 `--confirm-budget-code`、TUI 运行/审批恢复的 `LOAD BUDGET` 另提供工厂生命周期与无票据内容的池摘要；也覆盖评测/配置化探测，整批评测共用一个池，保存的评测报告不变。a9 Experimental，验证范围见 a9 发布说明，见[Runtime 具名绑定](./local-runtime.md)。

a9 另导出 `SQLiteSessionSummaryObserver(database_path, operation_id, *, max_runs=1024, max_report_bytes=16384, timeout=1.0)`。实现既有 `SessionSummaryObserver`，提供 `initialize()`、`record()`、`reports()`、`snapshot(main_result=None)`；初始化显式写入，读取不创建缺失文件，主结果不持久化。2.0.0a9 Experimental，验证范围见 a9 发布说明；边界见[SQLite 摘要报告](./context-accounting.md)。

用量归集增量导出 `InMemorySessionSummaryObserver`、`SessionPreparationUsage`、`SessionUsageError` 与 `aggregate_session_preparation_usage(reports, main_result=None)`（2.0.0a8；针对性回归通过）。观察器按摘要 Run ID 幂等更新，`snapshot(main_result)` 显式合并一个主 Run 的累计结果；缺失报告不当作零，费用按币种/价格版本分组。这不是共享预算控制器，不自动更改 Runtime/Session 汇总。详见[上下文用量归集](./context-accounting.md)。

模型摘要增量导出 `AgentSessionHistorySummarizer`、`SessionSummaryObserver`、`SessionSummaryRunReport`、`SessionSummaryError`（2.0.0a8；针对性回归通过）。摘要器通过显式注入的 Agent Loop 创建独立 Run，必需的异步观察器接收无正文开始/终态报告。默认一步、零工具调用、要求 Usage；可配置自身 Token/费用预算，不共享主 Run 预算。用法和异常/取消对账边界见 [可计量模型摘要](./sessions.md)。

a8 另导出 `AsyncSessionHistoryPolicy`、`AsyncSessionHistoryRetriever`、`AsyncSessionHistorySummarizer`、`AsyncRetrievedSessionHistoryPolicy` 和 `AsyncSummarizedSessionHistoryPolicy`（2.0.0a8 Experimental；针对性回归通过）。Manager/Runtime 的 `history_policy` 接受同步或异步协议；`conversation(..., cancellation=...)` 可取消待完成的投影。模板要求显式注入异步回调，默认回调超时 30 秒，不加载外部客户端、不自动重试。准备阶段费用不自动归入主 Agent 预算；详见[异步历史与计量边界](./sessions.md)。

a8 运行入口新增（Experimental，针对性回归通过）：输入解析器的 `allow_message_fields=False`、`InputManifestLimits.max_message_field_bytes`（默认 65536），Runtime `run()` / `run_messages()` 与 SessionManager `run_agent()` 的逐次 `input_recorder`，以及 `BuiltinSessionHistoryOptions.include_name/include_metadata`（仅 recorded 模式）。不改变共享默认记录器，不从字段推导权限；CLI/TUI 独立选择当前发送、额外保存及历史复用，见[运行选项](./local-runtime.md)。这些接口要求 a8 或更高版本。

a8 另导出 `build_session_message_projector(include_text=False, input_media=None, include_name=False, include_metadata=False)`，供 CLI/TUI 与 Python 宿主共用默认隐藏内容的投影装配。它不授予读取/发送权限；选择字段或媒体时返回包装兼容投影器，变更披露配置会改变快照身份。2.0.0a8 Experimental；针对性回归通过；参见 [Replay 字段披露](./event-replay.md)。

消息字段保存另新增 `MessageFieldsSessionInputRecorder`、`MessageFieldsSessionInputDecoder`、`SessionMessageFieldsDecoder` 和 `MessageFieldsSessionMessageProjector`（2.0.0a8；针对性回归通过）。`RecordedSessionHistoryPolicy` 可额外注入 `fields_decoder` 与字段大小上限，内容解码不自动授权字段复用。保存、展示、发送三条路径分别选择，默认均不暴露 name/metadata；详见 [Session 字段边界](./sessions.md)。

`BuiltinSessionHistoryOptions` 为 a8 的内置历史选项对象（Experimental，针对性回归通过）。`runtime_options()` 返回新的 Runtime 参数，不代表授权；CLI/TUI 独立取得执行、记录、媒体复用或文本变换确认。`text` 不覆盖 Runtime 默认策略，`none` 设置 `include_history=False`，其余模式构建对应内置策略。Python 宿主仍可绕过此便捷对象直接注入任意协议实现。

a8 另新增 `SessionHistoryTurn`、`SessionHistoryLimits`、`SessionHistoryRetriever`、`SessionHistorySummarizer`、`KeywordSessionHistoryRetriever`、`RetrievedSessionHistoryPolicy`、`ExtractiveSessionHistorySummarizer` 和 `SummarizedSessionHistoryPolicy`。这是 a8 的本地文本上下文模板（Experimental，针对性回归通过）；查询逐次绑定，回调显式注入，不调用模型或改写 Session，详见 [Session 检索与摘要](./sessions.md)。

结构化运行新增 `InputManifestLimits`、`InputManifestError`、`load_input_manifest()`、`input_manifest_from_mapping()` 与 `LocalAgentRuntime.run_messages()`（2.0.0a7；针对性回归通过）。文本/消息运行可传入 `record_inputs`、`include_history`、`history_policy`；CLI 新增 `--input-file`，TUI Run 提供同样的媒体输入及独立记录/历史授权，详见[本地 Runtime](./local-runtime.md)。

Session 输入记录（2.0.0a7；针对性回归通过）新增 `SessionInputRecorder`、`StandardSessionInputRecorder`、`SessionInputRecordingError`、`session_input_to_dict()`。`SessionManager(..., input_recorder=...)` 可替换编码策略，`run_agent(..., record_inputs=True)` 独立开启记录；`SessionMessage.recorded_input` 保存深度只读、codec 标记的有限 JSON，首次实际记录升级 Session schema 2，旧 schema 1 继续可读。默认历史仍仅文本，不自动再次发送媒体；详见 [Session 记录边界](./sessions.md)。

Session 历史与输入展示新增 `SessionHistoryPolicy`、`TextSessionHistoryPolicy`、`RecordedSessionHistoryPolicy`、`SessionInputDecoder`、`StandardSessionInputDecoder`、`SessionInputDecodingError` 和 `RecordedSessionMessageProjector`（2.0.0a7；针对性回归通过）。`conversation()` / `run_agent()` 可逐次显式传入 `history_policy`，默认仍只文本；记录、展示与模型发送独立，详见 [Session 策略](./sessions.md)。

Session 展示层（2.0.0a7；针对性回归通过）新增 `SessionEventReplay`、`SessionRecordSource`、`SessionRunReplaySource`、`SessionMessageProjector`、`TextSessionMessageProjector`、`SessionRunView`、`SessionReplaySnapshot`、`SessionReplayPage` 和 `SessionReplayError`。`RunEventPageSource` 另将累积器读取端抽象为可替换的分页协议，旧 `RunEventReplay` 继续适用。仅展示已登记 Run 的已记录内容，不改变 Session schema、模型输入或执行状态，详见 [Session 文档](./sessions.md)。

状态：下表包含稳定版与 `2.0.0a7` API；不能把所有导出都视为已验收的 `Implemented`。`w_agent.__init__` 当前导出以下主要类型：

| 分组 | API |
|---|---|
| Agent | `BaseAgent`、`LegacyAgentAdapter`、`AgentDefinition`、`AgentLoop`、`ReactAgentLoop`、`RunContext`、`RunEvent`、`RunResult`、`RunStore`、`RunEventSource`、`PagedRunEventSource`、`RunEventReplay`、`RunEventCursor`、`RunEventPage`、`safe_run_event_to_dict`、`RunCheckpointSummary`、`JsonlRunStore`、`TokenBudget`、`TokenEstimator`、`TokenEstimate`、`CharacterTokenEstimator`、`CostBudget`、`CostEstimator`、`CostEstimateRequest`、`CostEstimateRoute`、`CostEstimate`、`PricingCostEstimator` |
| Session | `SessionManager`、`RunEventCallback`、`SessionRecord`、`SessionRunRecord`、`AgentUsageSummary`、`InMemorySessionStore`、`JsonSessionStore` |
| 本地装配 | `LocalRuntimeConfig`、`LocalToolConfig`、`LocalPricingConfig`、`LocalProviderAssembly`、`LocalAgentRuntime`、`load_local_runtime_config`、`assemble_local_provider`、`assemble_local_runtime` |
| 容器 | `BeanFactory`、`BeanDefinition`、`Scope` |
| 配置 | `DynamicConfigManager` |
| 装饰器 | `AgentComponent`、`ServiceComponent`、`ToolComponent`、`Component`、`Autowired`、`Qualifier` |
| 生命周期 | `PostConstruct`、`PreDestroy`、`LifecycleManager`、`GracefulShutdownManager` |
| 事件 | `EventBus`、`Event`、`ConfigChangedEvent` |
| AOP/弹性 | `Retry`、`CircuitBreaker`、`AspectJPointcut`、Advice、`ProxyFactory`、`ResilienceManager` |
| 观测 | `global_tracer`、`CompositeHealthIndicator`、`HealthIndicator`、`LLMHealthIndicator` |
| 分布式 | `RedisDistributedLock`、`LockRenewalPool` |
| 技能/沙箱 | `Skill`、`WasmSkillSandbox`、`NsJailSkillSandbox`、`SandboxProvider`、`DockerSandboxProvider`、`UnsafeLocalSandboxProvider` |
| 工具/扫描 | `ToolRegistry`、`ToolExecutor`、`ToolCall`、`ToolResult`、`python_tool`、`load_tool_entries`、`LangChainToolAdapter`、`ParallelASTScanner`、`Doctor` |
| 微内核 | `PluginManager`、`Registry`、`ScopePath`、`EventDispatcher` 等 |
| 模型/价格 | `ModelProvider`、`ModelRegistry`、`ModelRequest`、`StreamEvent`、`OpenAICompatibleProvider`、`HttpModelProvider`、厂商映射与模板、`ModelPrice`、`PriceTable`、`PricingResolver`、`PricingCatalog`、`ModelCost` 等 |
| 路由/调用/探测 | `ModelRouter`、`ModelExecutor`、`InvocationPolicy`、`YamlRoutingPolicy`、`EndpointProbe`、`ModelProviderProbe` 等 |
| Workflow | `WorkflowEngineProtocol`、`LocalWorkflowEngine`、三种 Definition、`WorkflowStore`、`JsonlWorkflowStore` 等 |
| 测试与评测 | `ScriptedModelProvider`、`RecordingModelProvider`、`ReplayModelProvider`、`EvaluationDataset`、`EvaluationSuite`、`EvaluationSuiteRegistry`、`LocalEvaluationRunner`、Scorer 与 JSON Reporter |

保留的 1.x Agent 抽象为：

```python
class BaseAgent:
    async def arun(self, prompt: str) -> str:
        raise NotImplementedError
```

`BaseAgent` 尚未接入新的模型协议；新的 `AgentLoop`、ReAct/工具和 Workflow 运行时独立提供。ReAct 审批 Checkpoint、Workflow 节点 Checkpoint，以及本地持久化 Session 生命周期/跨 Run 文本上下文已经实现。`2.0.0a4`另有 `RunEventReplay.page()` 的 Run ID 绑定游标分页读取；`2.0.0a6`另有多模态/工具增量的只读累积器（针对性回归通过），工具结果正文的可选记录已纳入 a7（2.0.0a7，针对性回归通过），只读 Replay 已接入 a7，专用媒体渲染仍在计划中。

严格本地 JSON 配置可通过 `load_local_runtime_config()` 和 `assemble_local_runtime()` 装配内置 Provider 模板、单 Provider 路由、受限调用策略、所选 ToolBinding、ReAct Loop、RunStore 与 SessionStore。`assemble_local_provider()` 只构建带异步关闭生命周期的 Provider，不注册也不执行 I/O，由应用自行选择探测或注册策略。`LocalProviderAssembly` 与 `LocalAgentRuntime` 都支持异步上下文和幂等关闭。配置只接受 `api_key_env` 凭据引用，只能从宿主 Catalog 选择工具，不能自行导入、授权或批准。`LocalAgentRuntime.resume()` 与 `wagent run-resume` 可按精确 Call ID 恢复审批断点；CLI 导入开发者工具代码还要求独立的 `--confirm-tool-code`。详见[本地配置化 Runtime](./local-runtime.md)。

`2.0.0a6`另导出 `ToolContinuation`、`ToolContinuationError`、`ToolResumeHandler` 与可选 `ResumableToolExecutorProtocol`（针对性回归通过）。`ToolBinding.resume_handler` 和 `ToolExecutor.resume()` 提供独立续执行入口；`RunCheckpoint.tool_continuation` 使用 schema 2 保存未完成工具票据，无票据仍使用 schema 1。恢复要求精确 Call ID 授权及策略允许，不能退回初始处理器重跑。`2.0.0a6`另导出 `WorkflowToolReference` 与 `resumable_workflow_tool()`，提供引用优先的 Workflow 工具续执行；双层授权协调服务已加入`2.0.0a6`（针对性回归通过），TUI 引导亦已加入`2.0.0a6`（针对性回归通过）；详见[工具续执行](./tools.md)。

双层审批协调（`2.0.0a6`，针对性回归通过）另导出 `WorkflowToolApprovalReview`、`WorkflowToolApprovalAssemblyContext`、`WorkflowToolApprovalFactory`、`WorkflowToolApprovalError`，以及 `review_workflow_tool_approvals()`、`resume_workflow_tool_approval()`、`open_workflow_tool_approval_entry()`。只读关联不授权，恢复接收独立父/子权限，仅驱动父 Agent 的恢复入口；工厂需忠实装配三个 Store 和临时 grants。双层 CLI 已接入`2.0.0a6`（针对性回归通过），TUI 引导亦已接入`2.0.0a6`（针对性回归通过），详见[双层审批协调](./workflows.md)。

事件展示状态重建（`2.0.0a6`，针对性回归通过）导出 `RunEventReducer`、`RunEventAccumulator`、`RunReplaySnapshot`、`ReducedRunEventPage` 与 `TranscriptRunEventReducer`。快照绑定 Run、游标和 reducer 配置；默认不公开文本/工具内容，失败页不推进原快照。它不恢复执行、不授权工具，详见[事件回放](./event-replay.md)。

## 2. 下一代导出策略

状态：`Implemented` / `Planned`。微内核、模型、工具、`AgentLoop` 与 `WorkflowEngineProtocol` 已经直接导出。未发布的 M1 源码新增 `ApplicationContext`、`ApplicationScope`、`ApplicationState`、`ApplicationLifecycleError`，以及 `ComponentDefinition`、`BorrowedComponent`、`ComponentRef`、`AssemblyComponent`、`AssemblyPlan`、`AssemblyDefinitionError`、`compile_assembly()`；桥接接口为 `ApplicationPlugin`、`CapabilityImport`、`CapabilityExport`、`borrow_legacy_singletons()`，配置预检为 `ConfigurationField`、`ConfigurationSchema` 和定义上的 `validate_arguments`；见[装配与生命周期](./application-assembly.md)。原计划中的 `Application` 尚未导出；插件桥接不代表注解与 AOP 已贯通。

下一代 API 直接从 `w_agent` 导出，不创建 `w_agent.v2`：

```python
from w_agent import AgentLoop, LocalWorkflowEngine, ModelProvider
```

在迁移完成前，顶层导出必须避免新旧同名对象产生模糊行为。旧对象通过兼容模块或适配器保留。

## 3. 微内核协议

状态：`Implemented`（`2.0.0a1`）。

```python
class Plugin(Protocol):
    spec: PluginSpec

    async def load(self, context: PluginContext) -> None: ...
    async def unload(self) -> None: ...


class Registry(Protocol):
    def register(self, contribution: Contribution) -> Registration: ...
    def resolve(self, capability: CapabilityKey, scope: ScopePath) -> object: ...
```

`Registration.dispose()` 必须幂等。加载失败时，生命周期管理器撤销该次加载已经产生的所有注册。

当前还导出 `PluginManager`、`PluginContext`、`FunctionPlugin`、`CapabilityDeclaration`、`CapabilityRequirement`、`Contribution`、`RegistryView`、`ScopePath`、`EventDispatcher`、YAML 引用加载和 entry point 发现 API。`2.0.0a4`的 `load_plugin_references(..., pre_load_validator=...)` 允许宿主在导入后、执行插件 setup 前校验插件对象；已安装插件加载利用它核对入口模块来源及插件名称/版本。导入本身仍是代码执行边界。

## 4. 模型协议

状态：`Implemented`（Phase 2A）。

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

`StreamEvent` 已覆盖内容块开始/增量/结束、文本/工具调用增量、Usage、标准错误和 Finish。`TokenUsage` 统一输入、输出和缓存输入 Token，并提供不重复计算缓存子集的 `total_tokens`；`ModelResponse.usage_reported` 区分 Provider 未上报与真实零值。`collect_stream()` 校验块顺序和明确终止事件。Provider 必须完整报告不支持的标准字段，不得静默忽略。

`OpenAICompatibleProvider` 已实现 `/models` 和流式 `/chat/completions`，其 `OpenAICompatibleTransport` 可以替换。通用 `HttpModelProvider` 公开 `HttpRequest`、`HttpStreamFrame`、`HttpProviderMapping`、`HttpStreamDecoder` 与 `HttpProviderTransport`；默认 `HttpxProviderTransport` 支持 JSON、SSE 和 NDJSON。

`AnthropicMessagesMapping`、`GeminiGenerateContentMapping`、`OllamaChatMapping`、`QwenDashScopeMapping` 与 `OpenAIResponsesMapping` 为原生协议映射。`ProviderTemplateRegistry` 提供 OpenAI Responses、Anthropic、Gemini、Ollama、Qwen-native、DeepSeek、GLM、Qwen-compatible、vLLM 和 Turbo AI/SIAM.AI 模板；`VllmProvider` 扩展 Chat Completions 的 vLLM 专用参数。默认 HTTPX 实现位于 `models` 可选依赖。

## 5. 路由协议

状态：`Implemented`（Phase 2A 策略与决策、Phase 2B 收集式与逐事件透传调用执行）。

```python
class RoutingPolicy(Protocol):
    def select(self, request: RouteRequest) -> RouteDecision: ...
```

`RouteDecision` 包含候选模型、过滤原因、得分、最终路由、故障转移列表和策略版本，但不保存提示词明文。`WeightedRoutingPolicy` 与使用 `yaml.safe_load` 的 `YamlRoutingPolicy` 产生同一类型。`ModelRouter` 获取当前模型目录并应用策略，仍不直接执行调用。

`ModelExecutor.invoke()` 消费决定，通过 `InvocationPolicy` 控制逐尝试超时、重试次数、路由数和确定性退避，并返回 `ModelInvocationResult`。`ModelExecutor.stream()` 返回单次消费的 `ModelStreamExecution`，使用 `ModelStreamValidator` 实时校验和透传事件；首个事件可见前允许按策略重试/故障转移。默认 `max_stream_replays=0`；调用者可显式传入 `VerifiedTextPrefixRecovery` 或自定义 `StreamRecoveryStrategy`，在同一路由对单文本块执行有界重放、前缀核对与后缀去重。该操作可能再次计费，且不是 Provider 原生游标续传。`AttemptRecord` 记录已输出事件数、Provider 明确报告的 TokenUsage 和完整性标记，但不包含 Prompt 或凭据。执行失败抛出携带决定和全部已完成尝试的 `ModelInvocationError`。

`2.0.0a4`另导出 `CursorStreamItem`、`CursorResumableModelProvider` 与 `NativeCursorRecovery`。调用者向 `ModelExecutor.stream()` 显式传入 `NativeCursorRecovery(max_resumes=N)` 后，仅实现精确事件后游标协议的 Provider 可在同一路由、同次生成内继续事件流；重复游标失败关闭。内置厂商模板尚无原生游标适配，Agent 默认不启用此策略，也不提供跨进程游标持久化。失败尝试无用量报告时仍保持未知。

## 6. 探测协议

状态：`Implemented`（Phase 2A 基础）。

- `EndpointProbe.probe()`：L1 URL、DNS、TCP、TLS 和 HTTP 可达性嗅探，目标标识会移除凭据、查询串和片段。
- `ModelProviderProbe.probe()`：L2/L3 Provider 访问和模型目录检查。
- `ProbeMode.ACTIVE`：只有 `allow_active=True` 时才执行 L4/L5 最小生成与流协议检查。
- `ProbeMode.CAPABILITY`：L6/L7 当前只报告 Provider 声明，明确标记 `SKIPPED`，不会伪装成主动验证。
- `ProbeCache` 与 `PeriodicProbeService`：为手动和周期探测提供公共构件。
- `ModelRegistrationProbeService` 与 `ProbeHealthBridge`：提供显式的注册安全探测和外部路由健康映射；直接 `ModelRegistry.register()` 不执行 I/O。无凭据 L1 与配置化 Provider 安全/主动 CLI/TUI 入口已实现；主动模式必须单次明确授权。

## 7. Agent 协议

状态：`Implemented`（Run 协议与单 Agent ReAct 基础）。

```python
class AgentLoop(Protocol):
    async def run(
        self, definition: AgentDefinition, context: RunContext
    ) -> RunResult: ...

    def stream(
        self, definition: AgentDefinition, context: RunContext
    ) -> AgentExecution: ...
```

`ReactAgentLoop` 是只使用公开模型与工具协议的普通实现，可以被同协议 Loop 整体替换。它执行有界模型/工具循环，通过 `RunStore` 在事件可见前追加记录，并在需要审批时返回 `pending_tool_call` 与 `checkpoint_id`。`RunStore.list_checkpoints()` 提供不含 Prompt/参数值/输出的 `RunCheckpointSummary`。`AgentDefinition.emit_text_deltas=True` 显式切换到安全模型流并产生持久化的 `MODEL_TEXT_DELTA`；默认仍为收集模式，TUI 不显示增量正文。`TokenBudget` 提供 Run 级累计 Token 限制；构造 Loop 时可注入 `TokenEstimator`，通过 `TOKEN_ESTIMATED`、`TOKEN_ESTIMATE_UNAVAILABLE` 和 `TOKEN_BUDGET_WARNING` 提供调用前保护与软阈值可见性。`CharacterTokenEstimator` 是必须显式启用且不处理图片/音频的启发式模板，不会冒充精确分词器。`CostBudget` 配合可替换 `PricingResolver` 和应用提供的版本化 `PriceTable` 提供费用计量与硬停止；显式调用前保护可注入 `CostEstimator`，默认 `PricingCostEstimator` 从无 Prompt 的路由/Token/重放包络产生 `COST_ESTIMATED`、`COST_ESTIMATE_UNAVAILABLE` 与 `COST_BUDGET_WARNING`。`TOKEN_USAGE`/`COST_USAGE`、`RunResult` 和 Checkpoint 公开并保留 Token、费用、尝试账本与完整性。`SessionManager.run_agent()`/`resume_agent()` 接受可选同步或异步 `RunEventCallback`，按公开流顺序把实时事件投影给应用；内置 ReAct Loop 会先持久化再暴露事件。`2.0.0a6`的 `RunEventReplay.page()` 只读取已经持久化的事件，返回 `RunEventPage` 和下一游标，不执行模型/工具，原始事件内容由调用者负责授权和脱敏。`SessionManager.agent_usage()` 返回不含 Prompt/输出的 `AgentUsageSummary`，按 Agent 汇总多个 Session 的 Token、费用与完整性，默认排除归档 Session。`customer_support_agent()` 和 `coding_agent()` 只构建可完全覆盖的普通 Definition，不绑定模型、工具或权限。详见[Agent Runtime](./agents.md)与[Session](./sessions.md)。

`2.0.0a4`另有独立的 `AgentDefinition.emit_tool_call_deltas=True`：它在模型流中持久化 `MODEL_TOOL_CALL_DELTA` 原始工具参数片段，不会由 `emit_text_deltas` 自动开启。默认 CLI/TUI 安全投影隐藏 Call ID、工具名和参数；原始 RunEvent 的读取权限仍由应用控制。

`RunEventReplay.projected_page()` 返回 `ProjectedRunEventPage`，默认调用 `SafeRunEventProjector`；也可传入满足 `RunEventProjector` 的应用投影器。输出必须是 JSON 兼容对象，否则以 `RunStoreError` 失败关闭。原始 `page()` 仍可用于已授权的底层消费。

`FieldPolicyRunEventProjector` 配合 `RunEventFieldPolicy` 提供默认拒绝的声明式顶层字段允许/固定掩码策略。规则以精确 `RunEventType`（或值字符串）为键，`"*"` 仅作为回退。`NestedFieldRunEventProjector` 配合 `RunEventPathRule`/`RunEventPathAction`，可从嵌套对象或数组路径复制、重命名或固定掩码到新的嵌套对象；任意计算仍使用普通 `RunEventProjector`。

`AgentDefinition.emit_output_blocks=True` 显式持久化默认编码器认可的图片/音频模型输出。`ModelOutputEventEncoder` 可替换；`StandardMultimodalEventEncoder` 产生 `MODEL_OUTPUT_BLOCK` 并限制内联大小，编码失败以 `MODEL_OUTPUT_BLOCK_FAILED` / `OUTPUT_EVENT_ERROR` 失败关闭。`MultimodalRunEventProjector` 通过 `MediaProjectionMode.METADATA`、`REFERENCES`、`CONTENT` 分离元数据、URL 与实际内联内容披露，非媒体事件使用可替换 fallback。默认 CLI/TUI 不请求媒体内容。

## 8. Workflow 协议

状态：`Implemented`（Phase 4 本地顺序执行与节点边界恢复）；显式有界异步 DAG 并行为`2.0.0a4`的 `Experimental` 能力。

外部边界暂停同样位于`2.0.0a4`：向 `LocalWorkflowEngine(pause_source=...)` 注入 `WorkflowPauseSource`，或使用内置 `WorkflowPauseController.request_pause(run_id)` / `clear(run_id)`。请求按 Run ID 隔离，当前节点/批完成后才暂停，已完成或失败的执行不转为暂停；清除请求不自动恢复。现有 `start()` / `resume()` 和 Checkpoint 格式不变。TUI 已接入本界面恢复任务的暂停按钮；CLI 与跨进程控制已进入 a5，见下文 SQLite 请求源。

`2.0.0a4`还提供 `WorkflowNodeInvoker`、`InlineWorkflowNodeInvoker` 和 `ThreadedWorkflowNodeInvoker`。通过 `LocalWorkflowEngine(node_invoker=...)` 为全部内置 Workflow 前端及恢复入口替换节点调用策略；默认 Inline，可显式把同步处理器移到线程。线程取消会等待同步调用退出，再传播取消并保留不确定 Checkpoint；同步调用需要自身的 I/O 超时。该策略不写入 Checkpoint，恢复时由应用重新装配。

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

`DagWorkflowDefinition`、`StateGraphDefinition` 和 `PythonWorkflowDefinition` 使用相同引擎，并可通过共享微内核上的 `WorkflowRegistry` 按版本和 Scope 注册。节点返回 `WorkflowNodeResult` 以更新状态、选择下一节点或请求暂停。`LocalWorkflowEngine` 支持边界取消，并通过可替换 `WorkflowStore` 写入事件和检查点；内置内存与 JSONL 实现。`2.0.0a4` 新增的独立 `WorkflowCheckpointCatalog.list_checkpoints()` 返回不含 Input/State/Output/Scope/Metadata 值的 `WorkflowCheckpointSummary`，不修改稳定 `WorkflowStore` 合约；`load_workflow_entry()` / `load_workflow_entries()` 仅在应用显式授权后导入开发者 `module:attribute` Definition，并按名称与版本建立 Catalog。恢复只承诺已完成节点边界，不恢复任意 Python 指令栈。不确定节点执行保留 `RESUMING` 并拒绝自动重放。`2.0.0a4`可通过 `LocalWorkflowEngine(max_parallel_nodes=N)` 显式开启有界异步 DAG 前沿并行，默认 `N=1`。`agent_workflow_node()` 与 `workflow_start_tool()` / `workflow_resume_tool()` 已提供双向公共协议适配；`2.0.0a5`新增单向显式审批桥（见下文）；反向自动级联和嵌套 Workflow 尚未实现。详见[Workflow 与节点恢复](./workflows.md)。

`2.0.0a5`（针对性回归通过）另提供 `SQLiteWorkflowPauseController(state_root)`，实现 `WorkflowPauseSource.is_pause_requested(run_id)`，并提供 `request_pause(run_id)` / `clear(run_id)`。它不改变引擎或 Checkpoint 协议；读取失败抛出 `WorkflowPauseControlError`，不静默继续节点。CLI 通过 `workflow-resume --enable-pause-control` 显式接入，三个独立命令负责请求、状态与清除。`AnyWorkflowPauseSource(*sources)` 支持有序只读 OR 组合，TUI 以默认关闭的选项组合本界面控制器和 SQLite 源；任务结束仅清除本界面请求。清除不恢复，状态不证明进程存活；详见 [跨进程暂停](./workflows.md)。

Workflow 审批桥补充（`2.0.0a5`，针对性回归通过）：`ResumableAgentLoop` 是可选的子 Run 恢复协议；`approval_agent_workflow_node()` 使用同一 `RunStore` 校验 `AgentWorkflowApproval` 引用，并通过宿主回调取得精确调用授权。`WorkflowNodeResult(pause=True, suspend=True)` 保留当前节点未完成并产生 `NODE_SUSPENDED`。普通 `pause=True` 和旧适配器不变；反向自动级联仍待实现；界面接线见`2.0.0a6`说明，详见 [Workflow 审批级联](./workflows.md)。

`2.0.0a6`（针对性回归通过）另提供 `WorkflowApprovalAssemblyContext`、`WorkflowApprovalFactory`、`WorkflowApprovalResumeError`、`open_workflow_approval_entry()` 与 `resume_workflow_approval()`。工厂返回异步上下文管理器，显式接收 Store 和本次授权对象；协调服务在装配前后检查精确关联/完整检查点，向父流程恢复注入一次授权并始终清理。Python 宿主自行授权代码和执行；CLI `checkpoint workflow-approve-resume` 要求三项独立确认。此服务不是沙箱或跨 Store 原子事务，详见 [审批恢复工厂](./workflows.md)。

## 9. 工具协议

审批宿主接口（`2.0.0a5`，针对性回归通过）：`review_workflow_approvals()` 返回只读 `WorkflowApprovalReview` 与 `WorkflowApprovalLinkStatus`，不授予权限。`WorkflowApprovalGrants.grant(reference, scope=..., permissions=..., ttl_seconds=300)` 创建内存一次性授权，其可调用对象可显式传入审批节点的 `approval_context`；消费后不退回，支持 `revoke()` / `clear()`。a5 的 CLI/TUI 仅提供只读关联查询；`2.0.0a6`的 CLI 工厂接线见上文，TUI 已接入同一工厂服务（针对性回归通过）。

状态：`Implemented`（Phase 3 工具执行基础）。

```python
class ToolPolicy(Protocol):
    async def evaluate(
        self,
        binding: ToolBinding,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolPolicyDecision: ...
```

`ToolRegistry` 在统一注册表中按版本和 Scope 注册 `ToolBinding`。`ToolExecutor.execute()` 依次解析、校验、执行策略、处理超时/取消并写入审计。默认 `PermissionPolicy` 检查本地授予的权限，`SideEffectApprovalPolicy` 对写入、破坏性和外部副作用要求调用 ID 逐次批准。工具 Definition 不持有执行策略，默认执行器不重试。`python_tool()`、`http_tool()`、`command_tool()`、`mcp_tool()`、`sandbox_command_tool()`、`McpClient`、`McpStdioTransport`、`McpStreamableHttpTransport` 和 `discover_mcp_bindings()` 已实现；`2.0.0a4`新增 `McpLegacyClient` 与 `McpLegacyStreamableHttpTransport`。旧版服务器主动请求、MRTR 自动输入交换和订阅流仍为 `Planned`。详见[工具注册、策略与执行](./tools.md)。

## 10. 沙箱协议

状态：`Implemented`（统一本地协议、Docker/OCI 与显式授权本地开发模式）。

```python
class SandboxProvider(Protocol):
    async def open(
        self,
        spec: SandboxSpec,
        *,
        cancellation: CancellationToken | None = None,
    ) -> SandboxHandle: ...
```

`SandboxHandle.execute()` 接收无 Shell 的 `SandboxCommand` 并返回 `SandboxResult`，`close()` 收敛容器或本地 Handle。`DockerSandboxProvider` 默认断网、只读根文件系统、drop capabilities、禁止提权、限制 CPU/内存/PID，并在关闭或不确定执行错误后删除容器。`UnsafeLocalSandboxProvider` 不是安全沙箱，只接受 `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)` 产生的运行时对象；它不会成为 Docker 失败后的回退。Provider 通过 `SandboxRegistry` 进入共享注册表。nsjail/Wasm 的新协议适配仍为 `Planned`，Remote Sandbox 为 `Reserved`。详见[沙箱与本地执行](./sandbox.md)。

## 11. 工程装配协议

状态：编码、解码、安全预览和本地版本库为 `Implemented`；`2.0.0a4` 的离线依赖规划与通用插件确认生命周期为 `Experimental`，宿主锁目录驱动的 Sandbox 包安装已包含于 `2.0.0a4`。在线来源发现、自动锁定和自动升级为 `Planned`。

```python
code = encode_composition(manifest)
manifest = decode_composition(code)
preview = inspect_composition(code)
CompositionStore(".wagent/compositions").save(manifest, alias="stable")

environment = CompositionEnvironment("3.11.9", "2.0.0a3")
resolver = StaticCompositionDependencyResolver(plugin_candidates)
plan = plan_composition(manifest, environment, resolver)

catalog = load_plugin_install_catalog("install-lock.json")
install_plan = plan_plugin_installations(plan, catalog)  # 仍然完全离线
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
# 这是第二条、独立的插件代码加载授权边界：
batch = await load_installed_plugin_references(
    manager,
    (InstalledPluginReference(result),),
)
```

解码、预览、依赖规划与安装规划不访问网络、不安装依赖、不加载插件、不执行代码。Manifest 拒绝秘密值、绝对本地路径、内嵌代码和 `UnsafeLocalSandbox` 授权；Codec 设有压缩与解压大小边界。`CompositionDependencyResolver` 与 `PackageInstaller` 均可替换。默认安装器只接受宿主目录声明的精确版本、完整 SHA-256 wheel 闭包和来源映射，使用调用者选择的 `SandboxProvider`，并在加载前复验内容树。`PluginInstallAuthorization` 绑定完整请求摘要；安装成功不会授予 `load_installed_plugin_references()` 的代码加载权。在线 Catalog、锁文件生成、自动升级与同名插件热迁移未实现。

## 12. 测试与评测 API

状态：`Experimental`（`2.0.0a2`）。

`ScriptedModelProvider` 提供有限、确定性、无网络的模型 Turn；`RecordingModelProvider` 和 `ReplayModelProvider` 通过 `JsonlModelCassette` 完成显式敏感内容授权下的完整 Turn 录制与顺序回放。`load_evaluation_dataset()` 从有界严格 JSON 或 `builtin:` 引用加载版本与推荐 Scorer，`load_evaluation_cases()` 保留只取 Cases 的兼容接口。`EvaluationSuite`/`EvaluationSuiteRegistry` 是可替换普通数据与注册表；内置客服/编码套件可通过 `evaluation_suite_to_dict()` 或 `wagent benchmark export` 导出。`LocalEvaluationRunner` 对返回公开 `RunResult` 的异步目标顺序执行用例，支持 `ExactTextScorer`、`ContainsTextScorer`、声明式 `CaseContractScorer` 和自定义 `EvaluationScorer`。`EvaluationReport`/`JsonEvaluationReporter` 汇总通过率、Token/费用与完整性、延迟、错误和工具结果；报告默认不持久化 Prompt、Metadata、输出或异常正文。CLI/TUI 的模型调用、工具代码导入和权限分别授权。详见[本地测试、模型回放与评测](./testing-evaluation.md)。

## 13. 兼容接口

状态：`Implemented`（`LegacyAgentAdapter`）/ `Deprecated`（1.x 抽象）。

`LegacyAgentAdapter` 将 1.x `BaseAgent.arun()` 包装为 Workflow 节点。兼容层只做显式文本参数和结果转换，不模拟不存在的流式、工具、Token 或 Checkpoint 能力；非文本输入必须由调用方提供 `prompt_mapper`。
