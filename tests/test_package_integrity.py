from collections import Counter
from pathlib import Path

import w_agent


def test_public_exports_are_present_and_unique():
    assert not [name for name in w_agent.__all__ if not hasattr(w_agent, name)]
    assert not [name for name, count in Counter(w_agent.__all__).items() if count > 1]


def test_parallel_delivery_apis_are_available_from_package_root():
    expected = {
        "OptionalDocumentKnowledgeParser", "prepare_traced_knowledge_import",
        "BM25KnowledgeRetriever", "HybridKnowledgeRetriever",
        "knowledge_workflow_node", "knowledge_evaluation_target",
        "SQLiteKnowledgePreparationStore", "retry_knowledge_build_batch",
        "ResponsesCheckpointStore", "OpenAIResponsesResumableProvider",
        "McpClientHandlers", "McpDuplexStdioTransport",
        "NsJailSandboxProvider", "ProviderSkillSandbox",
        "PluginReplacementPlan", "PluginReplacementError",
        "PluginReplacementSession", "MediaDisplay", "TerminalMediaDisplay",
        "export_recorded_media", "KnowledgeImportStore", "SQLiteKnowledgeImportStore",
        "KnowledgeSyncPlan", "execute_knowledge_sync", "SQLiteKnowledgeSyncJournal",
        "KnowledgeSyncImportRequest", "KnowledgeSyncPrepareRequest", "KnowledgeSyncExecuteRequest",
        "import_local_knowledge_sync", "prepare_local_knowledge_sync", "execute_local_knowledge_sync",
        "SQLiteServiceUsageLedger", "ObservedSharedBudgetController", "aggregate_service_usage",
        "ObservedKnowledgeRetriever", "ObservedKnowledgeReranker",
    }
    assert expected <= set(w_agent.__all__)


def test_all_package_modules_compile():
    package_root = Path(w_agent.__file__).parent
    assert package_root.is_dir()
    failures = []
    for source_file in package_root.rglob("*.py"):
        try:
            compile(
                source_file.read_text(encoding="utf-8"),
                str(source_file),
                "exec",
            )
        except Exception as exc:
            failures.append(f"{source_file}: {exc}")
    assert not failures, "\n".join(failures)


def test_sensitive_logging_module_is_importable():
    from w_agent.logging.sensitive_filter import SensitiveDataFilter

    assert SensitiveDataFilter.filter("Authorization: Bearer secret") == (
        "Authorization: Bearer ***"
    )
