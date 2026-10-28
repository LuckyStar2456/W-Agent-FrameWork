"""Explicit local index host template; edit settings and review before loading.

No database/collection creation, model download or calls at import/setup. This
example is unverified; hosts own actual model dimensions, accounting and access.
"""

from contextlib import asynccontextmanager

from w_agent import KnowledgeIndexHostBinding, QdrantVectorSearch, QdrantVectorWriter, ollama_text_embedder


@asynccontextmanager
async def index_catalog():
    writer = QdrantVectorWriter(QdrantVectorSearch("http://localhost:6333", "manual"))
    # Replace with a model already available in your local service and its exact
    # output dimension. No model is installed/pulled by this template.
    embedder = ollama_text_embedder("http://localhost:11434", "REPLACE_WITH_YOUR_MODEL", 768)
    yield {
        "prepare": KnowledgeIndexHostBinding(writer, embedder, "my-model-preprocessing-r1", 768),
        "execute": KnowledgeIndexHostBinding(writer),
    }
    # Default HTTP transports close each request; custom persistent resources
    # should be managed with async context managers/try-finally by your factory.
