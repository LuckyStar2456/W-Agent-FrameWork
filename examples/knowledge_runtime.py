"""Explicit CLI/TUI host factory for local sample knowledge; not business policy.

本地知识装配示例，内容仅作演示，不是实际业务规则。
"""

from contextlib import asynccontextmanager

from w_agent import (
    InMemoryKnowledgeDocumentStore,
    KnowledgeDocument,
    KeywordKnowledgeRetriever,
    LocalKnowledgeBinding,
)


@asynccontextmanager
async def knowledge_catalog():
    store = InMemoryKnowledgeDocumentStore((
        KnowledgeDocument("demo-return", "Demonstration only: sample returns take seven days.",
                          "sample:returns", "Sample returns"),
        KnowledgeDocument("demo-code", "Demonstration only: obtain authorization before running project commands.",
                          "sample:coding", "Sample coding guide"),
    ))
    yield {"manual": LocalKnowledgeBinding(KeywordKnowledgeRetriever(store))}
