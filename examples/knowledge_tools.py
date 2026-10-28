"""Local-only tool factory for explicit module:attribute loading.

Copy into the host project's import path. No model, index, file or network
operation occurs on import or factory construction. Records are sample data,
not a real business policy. External retrievers should keep the EXTERNAL effect.
"""

from w_agent import (
    InMemoryKnowledgeDocumentStore,
    KnowledgeDocument,
    KeywordKnowledgeRetriever,
    ToolBinding,
    ToolSideEffect,
    knowledge_search_tool,
)


def build_tools() -> tuple[ToolBinding, ...]:
    """Return an explicitly local, permission-gated knowledge-search binding."""
    store = InMemoryKnowledgeDocumentStore((
        KnowledgeDocument(
            "sample-refund-v1",
            "示例退货期限为七天。Sample returns window: seven days. Not a real policy.",
            "sample:refund-v1", "示例退货说明 / Sample returns policy",
        ),
    ))
    return (knowledge_search_tool(
        KeywordKnowledgeRetriever(store), side_effect=ToolSideEffect.READ,
    ),)
