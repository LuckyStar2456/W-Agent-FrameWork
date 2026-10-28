"""Explicit bounded local text imports; no persistence, embedding or file execution.

The root and its ancestors must be trusted and quiescent. Path checks are not an
OS sandbox or an atomic filesystem snapshot, especially across concurrent moves.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

from w_agent.knowledge_context import KnowledgeDocument, _documents, _text
from w_agent.knowledge_ingestion import _json, _label
from w_agent.knowledge_sqlite import _worker
from w_agent.vector_retrieval import _integer


class KnowledgeFileImportError(RuntimeError):
    """Fixed messages omit paths, bodies and trusted parser exception details."""


class KnowledgeFileTextParser(Protocol):
    """Trusted synchronous parser, called with bounded bytes in the import worker.

    parser_key is a host version label, not verified implementation identity.
    Implementations are not isolated and may have arbitrary side effects.
    """

    parser_key: str

    def parse(self, data: bytes, *, relative_path: str) -> str: ...


@dataclass(frozen=True, slots=True)
class Utf8KnowledgeFileParser:
    """Strict UTF-8, strip one initial BOM, preserve CR/LF, reject NUL."""

    parser_key: str = field(default="utf8-sig-text-v1", init=False)

    def parse(self, data: bytes, *, relative_path: str) -> str:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("knowledge text contains NUL")
        return text


def _relative(value: str, *, allow_root: bool = False) -> None:
    if allow_root and value == ".":
        return
    if (not isinstance(value, str) or not value or len(value.encode("utf-8")) > 2048
            or any(ord(char) < 32 or ord(char) == 127 or char in "\\:*?<>|\"" for char in value)):
        raise ValueError("knowledge relative path is invalid")
    if any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in value.split("/")):
        raise ValueError("knowledge relative path is invalid")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("knowledge file digest is invalid")


def _document_id(path: str, raw_digest: str, text_digest: str, parser_key: str) -> str:
    return str(UUID(bytes=hashlib.sha256(_json([
        "wagent-knowledge-file-v1", path, raw_digest, text_digest, parser_key,
    ]).encode("utf-8")).digest()[:16]))


@dataclass(frozen=True, slots=True)
class KnowledgeFileRecord:
    """Raw/parsed fingerprints, not an archived original or chunk-offset map."""

    relative_path: str = field(repr=False)
    raw_digest: str
    raw_bytes: int
    text_digest: str
    text_bytes: int
    document_id: str | None

    def __post_init__(self) -> None:
        _relative(self.relative_path)
        _digest(self.raw_digest)
        _digest(self.text_digest)
        for size in (self.raw_bytes, self.text_bytes):
            if type(size) is not int or not 0 <= size <= 1024 * 1024:
                raise ValueError("knowledge file byte count is invalid")
        if self.document_id is not None and (
            not isinstance(self.document_id, str) or str(UUID(self.document_id)) != self.document_id
        ):
            raise ValueError("knowledge file document ID is invalid")

    def to_dict(self) -> dict:
        return {"relative_path": self.relative_path, "raw_digest": self.raw_digest,
                "raw_bytes": self.raw_bytes, "text_digest": self.text_digest,
                "text_bytes": self.text_bytes, "document_id": self.document_id}


@dataclass(frozen=True, slots=True)
class KnowledgeTextImport:
    """Immutable parsed documents and portable source records; nothing auto-saved."""

    parser_key: str
    documents: tuple[KnowledgeDocument, ...] = field(repr=False)
    records: tuple[KnowledgeFileRecord, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _label(self.parser_key)
        _documents(self.documents, 1024, 16 * 1024 * 1024)
        if not isinstance(self.records, tuple) or len(self.records) > 1024:
            raise ValueError("knowledge file records are invalid")
        paths: list[str] = []
        identities: list[str] = []
        by_id = {item.document_id: item for item in self.documents}
        for record in self.records:
            if not isinstance(record, KnowledgeFileRecord):
                raise ValueError("knowledge file record is invalid")
            paths.append(record.relative_path)
            if record.document_id is None:
                continue
            identities.append(record.document_id)
            document = by_id.get(record.document_id)
            if (document is None
                    or record.document_id != _document_id(record.relative_path, record.raw_digest, record.text_digest, self.parser_key)
                    or document.source != "local:" + record.relative_path
                    or document.title != PurePosixPath(record.relative_path).name
                    or _sha(document.text.encode("utf-8")) != record.text_digest
                    or len(document.text.encode("utf-8")) != record.text_bytes):
                raise ValueError("knowledge file record does not match its document")
        if paths != sorted(set(paths)) or identities != [item.document_id for item in self.documents]:
            raise ValueError("knowledge file records must be unique, ordered and complete")
        if (sum(item.raw_bytes for item in self.records) > 16 * 1024 * 1024
                or sum(item.text_bytes for item in self.records) > 16 * 1024 * 1024):
            raise ValueError("knowledge file records exceed byte limit")

    def to_manifest_json(self) -> str:
        """Expose relative paths/hashes, not bodies, absolute roots or credentials."""
        return _json({"format": "wagent-knowledge-text-import-v1", "parser_key": self.parser_key,
                      "records": [item.to_dict() for item in self.records]})

    @property
    def digest(self) -> str:
        return _sha(self.to_manifest_json().encode("utf-8"))


class KnowledgeFileImporter(Protocol):
    """Replaceable import capability, independent from snapshot/vector storage."""

    async def load(self, paths: tuple[str, ...], *, confirm_read: bool = False) -> KnowledgeTextImport: ...


def _reject_link(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise ValueError("knowledge file links are unsupported")


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True, slots=True)
class LocalTextKnowledgeImporter:
    """Small explicit local template; not a sandbox, watcher or directory mirror.

    No I/O at construction. Directory expansion is opt-in through selected paths;
    recursion and hidden entries are off by default. Trusted parsers are borrowed.
    """

    root: Path = field(repr=False)
    parser: KnowledgeFileTextParser = field(default_factory=Utf8KnowledgeFileParser, repr=False)
    suffixes: tuple[str, ...] = (".txt", ".md")
    recursive: bool = False
    include_hidden: bool = False
    max_files: int = 128
    max_entries: int = 4096
    max_depth: int = 16
    max_file_bytes: int = 1024 * 1024
    max_total_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.root, (str, Path)) or not str(self.root).strip():
            raise ValueError("knowledge import requires a root")
        object.__setattr__(self, "root", Path(os.path.abspath(self.root)))
        _label(self.parser.parser_key)
        if not callable(getattr(self.parser, "parse", None)):
            raise ValueError("knowledge import parser is invalid")
        if type(self.recursive) is not bool or type(self.include_hidden) is not bool:
            raise ValueError("knowledge import switches must be boolean")
        if (not isinstance(self.suffixes, tuple) or not 1 <= len(self.suffixes) <= 32
                or any(not isinstance(item, str) or not 2 <= len(item) <= 32 or not item.startswith(".")
                       or not item[1:].isascii() or not item[1:].isalnum() or item != item.lower() for item in self.suffixes)
                or len(set(self.suffixes)) != len(self.suffixes)):
            raise ValueError("knowledge import suffixes are invalid")
        for value, maximum in ((self.max_files, 1024), (self.max_entries, 65536), (self.max_depth, 64),
                               (self.max_file_bytes, 1024 * 1024), (self.max_total_bytes, 16 * 1024 * 1024)):
            _integer(value, maximum)

    def _checked(self, relative: str) -> tuple[Path, os.stat_result]:
        current = self.root
        info = current.lstat()
        _reject_link(info)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("knowledge import root must be a directory")
        if relative != ".":
            for part in relative.split("/"):
                current = current / part
                info = current.lstat()
                _reject_link(info)
                if not self.include_hidden and (
                    part.startswith(".") or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
                ):
                    raise ValueError("knowledge hidden path was not enabled")
        return current, info

    async def load(
        self, paths: tuple[str, ...], *, confirm_read: bool = False,
        previous: KnowledgeTextImport | None = None,
    ) -> KnowledgeTextImport:
        """Read the full selection; optionally reuse parsing of unchanged bytes.

        previous is trusted host-owned state, not a signed cache. Every selected
        file is still read and hashed. Unselected old files are not carried over.
        Change parser_key whenever the parser implementation/configuration changes.
        """
        if confirm_read is not True:
            raise KnowledgeFileImportError("knowledge-file-read-not-authorized")
        try:
            if previous is not None and not isinstance(previous, KnowledgeTextImport):
                raise ValueError
            if not isinstance(paths, tuple) or len(paths) > 1024:
                raise ValueError
            for path in paths:
                _relative(path, allow_root=True)
            if len(set(paths)) != len(paths):
                raise ValueError
        except Exception:
            raise KnowledgeFileImportError("knowledge-file-selection-invalid") from None
        return await _worker(lambda: self._load(paths, previous))

    def _load(self, paths: tuple[str, ...], previous: KnowledgeTextImport | None = None) -> KnowledgeTextImport:
        try:
            parser_key = self.parser.parser_key
            _label(parser_key)
            cached = {item.relative_path: item for item in previous.records} if previous is not None and previous.parser_key == parser_key else {}
            cached_documents = {item.document_id: item for item in previous.documents} if previous is not None else {}
            if not paths:
                return KnowledgeTextImport(parser_key, (), ())
            # Check ancestors too: resolve() alone would silently follow a link.
            for parent in reversed((self.root, *self.root.parents)):
                _reject_link(parent.lstat())
            selected: dict[str, tuple[Path, os.stat_result]] = {}
            pending = [(path, 0, True) for path in reversed(sorted(paths))]
            visited: set[str] = set()
            entries = 0
            while pending:
                relative, depth, explicit = pending.pop()
                if relative in visited:
                    continue
                visited.add(relative)
                _relative(relative, allow_root=True)
                path, info = self._checked(relative)
                if stat.S_ISDIR(info.st_mode):
                    if depth > self.max_depth:
                        raise ValueError("knowledge import depth limit")
                    children = []
                    with os.scandir(path) as directory:
                        for entry in directory:
                            entries += 1
                            if entries > self.max_entries:
                                raise ValueError("knowledge import entry limit")
                            if not self.include_hidden and entry.name.startswith("."):
                                continue
                            child_info = entry.stat(follow_symlinks=False)
                            if not self.include_hidden and getattr(child_info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2):
                                continue
                            is_directory = stat.S_ISDIR(child_info.st_mode)
                            if is_directory and not self.recursive:
                                continue
                            if not is_directory and Path(entry.name).suffix.lower() not in self.suffixes:
                                continue
                            child = entry.name if relative == "." else relative + "/" + entry.name
                            children.append((child, depth + 1, False))
                    pending.extend(reversed(sorted(children)))
                elif stat.S_ISREG(info.st_mode):
                    if path.suffix.lower() not in self.suffixes:
                        if explicit:
                            raise ValueError("knowledge import suffix unsupported")
                        continue
                    selected[relative] = (path, info)
                    if len(selected) > self.max_files or info.st_size > self.max_file_bytes:
                        raise ValueError("knowledge import file limit")
                else:
                    raise ValueError("knowledge import requires regular files")
            if sum(info.st_size for _, info in selected.values()) > self.max_total_bytes:
                raise ValueError("knowledge import total limit")
            documents, records = [], []
            raw_total = text_total = 0
            for relative, (_, original) in sorted(selected.items()):
                path, current = self._checked(relative)
                if _stamp(current) != _stamp(original):
                    raise ValueError("knowledge import source changed")
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                descriptor = os.open(path, flags)
                try:
                    with os.fdopen(descriptor, "rb", closefd=False) as source:
                        before = os.fstat(descriptor)
                        if not stat.S_ISREG(before.st_mode) or _stamp(before) != _stamp(original):
                            raise ValueError("knowledge import source changed")
                        data = source.read(min(self.max_file_bytes, self.max_total_bytes - raw_total) + 1)
                        if _stamp(os.fstat(descriptor)) != _stamp(before):
                            raise ValueError("knowledge import source changed")
                finally:
                    os.close(descriptor)
                if len(data) != original.st_size or len(data) > self.max_file_bytes:
                    raise ValueError("knowledge import file limit")
                raw_total += len(data)
                if raw_total > self.max_total_bytes:
                    raise ValueError("knowledge import total limit")
                raw_digest = _sha(data)
                old = cached.get(relative)
                if old is not None and old.raw_digest == raw_digest and old.raw_bytes == len(data) and old.document_id is not None:
                    text = cached_documents[old.document_id].text
                else:
                    # Blank inputs have no retained text document, so reparse.
                    text = self.parser.parse(data, relative_path=relative)
                _text(text, self.max_file_bytes, empty=True)
                if "\x00" in text:
                    raise ValueError("knowledge import text contains NUL")
                encoded = text.encode("utf-8")
                text_total += len(encoded)
                if text_total > self.max_total_bytes:
                    raise ValueError("knowledge import parsed total limit")
                text_digest = _sha(encoded)
                identity = _document_id(relative, raw_digest, text_digest, parser_key) if text.strip() else None
                if identity is not None:
                    documents.append(KnowledgeDocument(identity, text, "local:" + relative, path.name))
                records.append(KnowledgeFileRecord(relative, raw_digest, len(data), text_digest, len(encoded), identity))
            return KnowledgeTextImport(parser_key, tuple(documents), tuple(records))
        except Exception:
            raise KnowledgeFileImportError("knowledge-file-import-failed") from None
