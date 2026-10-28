"""Explicit local knowledge operations shared by CLI and TUI; no model calls."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Literal

from w_agent.knowledge_context import KeywordKnowledgeRetriever, _text
from w_agent.knowledge_files import LocalTextKnowledgeImporter, _digest
from w_agent.knowledge_ingestion import Utf8KnowledgeTextSplitter, _json, _label
from w_agent.knowledge_parsers import OptionalDocumentKnowledgeParser
from w_agent.knowledge_provenance import prepare_traced_knowledge_import
from w_agent.knowledge_sqlite import KnowledgeStoreError, SQLiteKnowledgeSnapshotStore


@dataclass(frozen=True, slots=True)
class LocalKnowledgeRequest:
    """Capture one operation and its independent, one-use UI confirmations.

    Import without confirm_write is an in-memory preview. No DB is opened for
    that preview. Creation additionally requires write permission. This is not
    an authorization sandbox; callers own trusted local files and directories.
    """

    action: Literal["import", "list", "search"]
    database: Path = field(repr=False)
    namespace: str | None = None
    version: str | None = None
    root: Path | None = field(default=None, repr=False)
    paths: tuple[str, ...] = field(default=(), repr=False)
    recursive: bool = False
    chunk_bytes: int = 4096
    query: str | None = field(default=None, repr=False)
    limit: int = 4
    confirm_read: bool = False
    confirm_write: bool = False
    confirm_create: bool = False
    include_text: bool = False
    document_formats: bool = False
    expected_preview_digest: str | None = None

    def __post_init__(self) -> None:
        if self.action not in ("import", "list", "search"):
            raise ValueError("unknown knowledge operation")
        for value in (self.recursive, self.confirm_read, self.confirm_write, self.confirm_create, self.include_text, self.document_formats):
            if type(value) is not bool:
                raise ValueError("knowledge confirmations must be booleans")
        if not self.confirm_read:
            raise ValueError("knowledge read requires explicit confirmation")
        # Validate all action options before touching either source or database.
        store = SQLiteKnowledgeSnapshotStore(self.database)
        object.__setattr__(self, "database", store.database_path)
        if self.namespace is not None:
            _label(self.namespace)
        if self.action in ("import", "search"):
            _label(self.namespace)
            _label(self.version)
        elif self.version is not None:
            raise ValueError("catalog does not take a version")
        if self.action == "import":
            if self.expected_preview_digest is not None:
                _digest(self.expected_preview_digest)
                if not self.confirm_write:
                    raise ValueError("preview digest lock requires a write")
            if (not isinstance(self.root, (str, Path)) or not str(self.root).strip()
                    or not isinstance(self.paths, tuple) or not self.paths
                    or len(self.paths) > 1024 or any(not isinstance(path, str) for path in self.paths)):
                raise ValueError("import requires a root and selected relative paths")
            Utf8KnowledgeTextSplitter(self.chunk_bytes)
            object.__setattr__(self, "root", Path(self.root).absolute())
            if self.confirm_create and not self.confirm_write:
                raise ValueError("database creation requires write confirmation")
            if self.query is not None or self.include_text:
                raise ValueError("import summaries do not expose bodies")
        else:
            if (self.root is not None or self.paths or self.recursive
                    or self.confirm_create or self.confirm_write or self.chunk_bytes != 4096
                    or self.document_formats or self.expected_preview_digest is not None):
                raise ValueError("read-only knowledge operation cannot import or write")
        if self.action == "search":
            _text(self.query, 4096)
            if type(self.limit) is not int or not 1 <= self.limit <= 128:
                raise ValueError("knowledge result limit must be between 1 and 128")
        elif self.query is not None or self.include_text or self.limit != 4:
            raise ValueError("search options require a search operation")


async def manage_local_knowledge(request: LocalKnowledgeRequest) -> dict[str, object]:
    """Execute captured options; return a JSON-compatible, body-free default view.

    Storage exceptions preserve may_have_written. Cancellation can follow a
    completed write: inspect the exact version instead of blindly retrying.
    No raw import manifest is persisted, no embedding/index/backend is invoked.
    """
    if not isinstance(request, LocalKnowledgeRequest):
        raise TypeError("a LocalKnowledgeRequest is required")
    store = SQLiteKnowledgeSnapshotStore(request.database)
    if request.action == "import":
        parser_options = {}
        if request.document_formats:
            parser = OptionalDocumentKnowledgeParser()
            parser_options = {"parser": parser, "suffixes": parser.suffixes}
        imported = await LocalTextKnowledgeImporter(
            request.root, recursive=request.recursive, **parser_options,
        ).load(request.paths, confirm_read=True)
        traced = prepare_traced_knowledge_import(
            request.namespace, request.version, imported, chunk_bytes=request.chunk_bytes,
        )
        snapshot = traced.snapshot
        # Bind the exact prepared contents and the destination selected for review.
        preview_digest = hashlib.sha256(_json([
            "wagent-knowledge-preview-v1", str(request.database), str(request.root),
            sorted(request.paths), request.recursive, request.document_formats, traced.digest,
        ]).encode("utf-8")).hexdigest()
        if request.expected_preview_digest is not None and preview_digest != request.expected_preview_digest:
            raise KnowledgeStoreError("knowledge-preview-conflict")
        if request.confirm_write:
            try:
                if request.confirm_create:
                    await store.initialize(confirm_create=True)
                await store.save(snapshot, confirm_write=True)
            except KnowledgeStoreError as error:
                # Creation is a separate transaction: even a rejected save may
                # follow successful file/schema creation. Never report rollback.
                raise KnowledgeStoreError(
                    error.code, may_have_written=error.may_have_written or request.confirm_create,
                ) from None
        return {
            "operation": "import", "state": "saved" if request.confirm_write else "preview",
            "namespace": snapshot.namespace, "version": snapshot.version,
            "digest": snapshot.digest, "files": len(imported.records),
            "documents": len(imported.documents), "chunks": len(snapshot.documents),
            "import_manifest_digest": imported.digest,
            "preview_digest": preview_digest, "trace_digest": traced.digest,
            "preview_locked": request.expected_preview_digest is not None,
            "trace_persisted": False,
            "manifest_persisted": False,
        }
    if request.action == "list":
        entries = await store.list_snapshots(request.namespace)
        return {
            "operation": "list", "body_integrity_verified": False,
            "versions": [
                {"namespace": item.namespace, "version": item.version,
                 "digest": item.digest, "payload_bytes": item.payload_bytes}
                for item in entries
            ],
        }
    snapshot = await store.load(request.namespace, request.version)
    matches = await KeywordKnowledgeRetriever(snapshot.as_document_store()).retrieve(
        request.query, limit=request.limit,
    )
    return {
        "operation": "search", "namespace": snapshot.namespace, "version": snapshot.version,
        "digest": snapshot.digest, "body_integrity_verified": True,
        "text_included": request.include_text,
        "matches": [
            {"id": item.document_id, "source": item.source, "title": item.title,
             **({"text": item.text} if request.include_text else {})}
            for item in matches
        ],
    }
