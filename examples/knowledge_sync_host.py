"""Editable local-service host for explicitly approved knowledge synchronization.

本地服务装配模板；导入不联网、不创建集合、不拉取模型。执行前请审查配置。
The dedicated collection must already exist. This is not a sandbox or a live
service acceptance result. Existing snapshot-bound indexes are not migrated.
"""

from contextlib import asynccontextmanager

from w_agent import (
    KnowledgeIndexHostBinding,
    QdrantVectorSearch,
    QdrantVectorWriter,
    ollama_text_embedder,
)


# Replace the model, dimension and revision label together after checking the
# actual local model. A host label does not authenticate model identity.
EMBEDDING_MODEL = "REPLACE_WITH_YOUR_INSTALLED_MODEL"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_REVISION = "my-local-model-preprocessing-r1"


@asynccontextmanager
async def sync_catalog():
    """Borrow clients; the CLI/TUI owns independent load/query/write approvals.

    The collection must be exclusive to this mutable sync lineage: stale point
    deletion removes all named vectors/payload and can invalidate old versions.
    Keep every participant on the same journal; it is not a remote lease.
    """
    writer = QdrantVectorWriter(
        QdrantVectorSearch("http://localhost:6333", "dedicated_manual_sync")
    )
    embedder = ollama_text_embedder(
        "http://localhost:11434", EMBEDDING_MODEL, EMBEDDING_DIMENSIONS
    )
    yield {
        "prepare": KnowledgeIndexHostBinding(
            writer, embedder, EMBEDDING_REVISION, EMBEDDING_DIMENSIONS
        ),
        "execute": KnowledgeIndexHostBinding(writer),
    }
    # Bundled HTTP transports close each request. If replacing them with pooled
    # clients, close those clients in this factory's finally/context-manager.
