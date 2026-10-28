"""Dedicated insert-only named build storage; no vector copies or migrations."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

from w_agent.knowledge_builds import KnowledgeBuildError, KnowledgeIndexBuild, MAX_KNOWLEDGE_BUILD_BYTES, knowledge_build_from_json
from w_agent.knowledge_ingestion import _label
from w_agent.knowledge_sqlite import _worker
from w_agent.vector_retrieval import _timeout

_APPLICATION_ID = 0x57414B42
_TABLE = "CREATE TABLE knowledge_builds (name TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (name, version))"


@dataclass(frozen=True, slots=True)
class SQLiteKnowledgeBuildStore:
    """Trusted local database; named versions are immutable and explicit.

    Construction has no I/O. Parents must exist; cancellation drains workers but
    may follow a committed save. No implicit deletion, artifact copy or approval.
    """

    database_path: Path = field(repr=False)
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("knowledge build database requires a local path")
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())
        _timeout(self.timeout)

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                             timeout=self.timeout, isolation_level=None)
        try:
            db.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            db.close()
            raise
        return db

    @staticmethod
    def _check(db: sqlite3.Connection) -> None:
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'").fetchall()
                != [("table", "knowledge_builds", _TABLE)]):
            raise KnowledgeBuildError("knowledge-build-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise KnowledgeBuildError("knowledge-build-creation-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone() is None:
                    if db.execute("PRAGMA application_id").fetchone()[0] != 0 or db.execute("PRAGMA user_version").fetchone()[0] != 0:
                        raise KnowledgeBuildError("knowledge-build-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                    db.execute("PRAGMA user_version = 1")
                    db.execute(_TABLE)
                self._check(db)
        except KnowledgeBuildError:
            raise
        except Exception:
            raise KnowledgeBuildError("knowledge-build-initialization-failed") from None

    async def save(self, build: KnowledgeIndexBuild, *, confirm_write: bool = False) -> str:
        if confirm_write is not True or not isinstance(build, KnowledgeIndexBuild):
            raise KnowledgeBuildError("knowledge-build-save-not-authorized")
        await _worker(lambda: self._operate(build.name, build.version, build))
        return build.digest

    async def load(self, name: str, version: str) -> KnowledgeIndexBuild:
        _label(name)
        _label(version)
        return await _worker(lambda: self._operate(name, version))

    async def list_builds(self) -> tuple[KnowledgeIndexBuild, ...]:
        """Verify bounded entries in one read transaction, in name/version order."""
        return await _worker(self._list_builds)

    def _list_builds(self) -> tuple[KnowledgeIndexBuild, ...]:
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_builds").fetchone()
                if count > 1024 or size > 64 * 1024 * 1024:
                    raise KnowledgeBuildError("knowledge-build-catalog-limit-exceeded")
                entries = []
                for name, version, digest, payload in db.execute(
                    "SELECT name, version, digest, CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END "
                    "FROM knowledge_builds ORDER BY name, version", (MAX_KNOWLEDGE_BUILD_BYTES,),
                ):
                    build = knowledge_build_from_json(payload, expected_digest=digest)
                    if (build.name, build.version) != (name, version):
                        raise KnowledgeBuildError("knowledge-build-identity-mismatch")
                    entries.append(build)
                return tuple(entries)
        except KnowledgeBuildError:
            raise
        except Exception:
            raise KnowledgeBuildError("knowledge-build-catalog-read-failed") from None

    def _operate(self, name: str, version: str, build: KnowledgeIndexBuild | None = None) -> KnowledgeIndexBuild:
        try:
            with closing(self._connect("rw" if build is not None else "ro")) as db, db:
                db.execute("BEGIN IMMEDIATE" if build is not None else "BEGIN")
                self._check(db)
                row = db.execute(
                    "SELECT CASE WHEN length(CAST(payload AS BLOB)) <= ? THEN payload END, "
                    "CASE WHEN length(CAST(digest AS BLOB)) = 64 THEN digest END "
                    "FROM knowledge_builds WHERE name = ? AND version = ?", (MAX_KNOWLEDGE_BUILD_BYTES, name, version),
                ).fetchone()
                if row is not None:
                    existing = knowledge_build_from_json(row[0], expected_digest=row[1])
                    if existing.name != name or existing.version != version:
                        raise KnowledgeBuildError("knowledge-build-identity-mismatch")
                    if build is not None and existing != build:
                        raise KnowledgeBuildError("knowledge-build-version-conflict")
                    return existing
                if build is None:
                    raise KnowledgeBuildError("knowledge-build-not-found")
                payload = build.to_json()
                count, size = db.execute("SELECT count(*), coalesce(sum(length(CAST(payload AS BLOB))), 0) FROM knowledge_builds").fetchone()
                if count >= 1024 or size + len(payload.encode("utf-8")) > 64 * 1024 * 1024:
                    raise KnowledgeBuildError("knowledge-build-capacity-exceeded")
                db.execute("INSERT INTO knowledge_builds VALUES (?, ?, ?, ?)", (name, version, build.digest, payload))
                return build
        except KnowledgeBuildError:
            raise
        except Exception:
            raise KnowledgeBuildError("knowledge-build-store-operation-failed") from None
