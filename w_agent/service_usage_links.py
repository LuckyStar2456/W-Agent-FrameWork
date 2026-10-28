"""Optional immutable Run/Session-to-operation links, not per-Run accounting."""

from __future__ import annotations

import asyncio
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from w_agent.knowledge_sqlite import _worker
from w_agent.service_usage import ServiceUsageError, _label
from w_agent.vector_retrieval import _timeout


def _run_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("usage link requires a bounded Run/Session identifier")


def _capacity(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 100000:
        raise ValueError("invalid usage link capacity")


@dataclass(frozen=True, slots=True)
class ServiceUsageRunLink:
    """A host correlation claim, not evidence that a Run started or completed."""

    session_id: str
    run_id: str
    operation_id: str

    def __post_init__(self) -> None:
        _run_id(self.session_id)
        _run_id(self.run_id)
        _label(self.operation_id)

    def to_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id, "run_id": self.run_id, "operation_id": self.operation_id}


class ServiceUsageLinkStore(Protocol):
    """Immutable Run identity mapping, with explicitly authorized insertion."""

    async def bind(self, link: ServiceUsageRunLink, *, confirm_write: bool = False) -> None: ...

    async def get(self, run_id: str) -> ServiceUsageRunLink | None: ...

    async def for_session(self, session_id: str) -> tuple[ServiceUsageRunLink, ...]: ...

    async def for_operation(self, operation_id: str) -> tuple[ServiceUsageRunLink, ...]: ...


class InMemoryServiceUsageLinkStore:
    def __init__(self, *, max_links: int = 10000) -> None:
        _capacity(max_links)
        self.max_links = max_links
        self._links: dict[str, ServiceUsageRunLink] = {}
        self._lock = asyncio.Lock()

    async def bind(self, link: ServiceUsageRunLink, *, confirm_write: bool = False) -> None:
        _write_request(link, confirm_write)
        async with self._lock:
            existing = self._links.get(link.run_id)
            if existing is not None:
                if existing != link:
                    raise ServiceUsageError("service-usage-link-conflict")
                return
            if len(self._links) >= self.max_links:
                raise ServiceUsageError("service-usage-link-capacity-exceeded")
            self._links[link.run_id] = link

    async def get(self, run_id: str) -> ServiceUsageRunLink | None:
        _run_id(run_id)
        async with self._lock:
            return self._links.get(run_id)

    async def for_session(self, session_id: str) -> tuple[ServiceUsageRunLink, ...]:
        _run_id(session_id)
        async with self._lock:
            return tuple(sorted((link for link in self._links.values() if link.session_id == session_id), key=lambda link: link.run_id))

    async def for_operation(self, operation_id: str) -> tuple[ServiceUsageRunLink, ...]:
        _label(operation_id)
        async with self._lock:
            return tuple(sorted((link for link in self._links.values() if link.operation_id == operation_id), key=lambda link: link.run_id))


def _write_request(link: ServiceUsageRunLink, confirmed: bool) -> None:
    if confirmed is not True or not isinstance(link, ServiceUsageRunLink):
        raise ServiceUsageError("service-usage-link-write-not-authorized")


_APP_ID = 0x5753554C
_SCHEMA = {
    "usage_link_limits": "CREATE TABLE usage_link_limits (singleton INTEGER PRIMARY KEY, max_links INTEGER NOT NULL)",
    "usage_run_links": "CREATE TABLE usage_run_links (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, operation_id TEXT NOT NULL)",
}
_COLUMNS = ", ".join(f"CASE WHEN length(CAST({column} AS BLOB)) <= 128 THEN {column} END" for column in ("session_id", "run_id", "operation_id"))


@dataclass(frozen=True, slots=True)
class SQLiteServiceUsageLinkStore:
    """Dedicated explicit local database; never auto-creates on reads/binds.

    No record IDs, payloads, prices, timestamps, prompts or paths are stored.
    Each Run maps to one immutable Session/operation, not necessarily exclusively
    to an operation: many Runs may share one operation's aggregate accounting.
    """

    database_path: Path = field(repr=False)
    max_links: int = 10000
    timeout: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (str, Path)) or not str(self.database_path).strip() or str(self.database_path) == ":memory:":
            raise ValueError("service usage links require a local file")
        _capacity(self.max_links)
        _timeout(self.timeout)
        object.__setattr__(self, "database_path", Path(self.database_path).absolute())

    def _connect(self, mode: str) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.database_path.as_uri()}?mode={mode}", uri=True,
                             timeout=self.timeout, isolation_level=None)
        try:
            db.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            db.close()
            raise
        return db

    def _check(self, db: sqlite3.Connection) -> None:
        objects = db.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name").fetchall()
        if (db.execute("PRAGMA application_id").fetchone()[0] != _APP_ID
                or db.execute("PRAGMA user_version").fetchone()[0] != 1
                or objects != [("table", name, _SCHEMA[name]) for name in sorted(_SCHEMA)]
                or db.execute("SELECT singleton, max_links FROM usage_link_limits").fetchall() != [(1, self.max_links)]):
            raise ServiceUsageError("service-usage-link-database-unsupported")

    async def initialize(self, *, confirm_create: bool = False) -> None:
        if confirm_create is not True:
            raise ServiceUsageError("service-usage-link-create-not-authorized")
        await _worker(self._initialize)

    def _initialize(self) -> None:
        try:
            with closing(self._connect("rwc")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' LIMIT 1").fetchone():
                    if db.execute("PRAGMA application_id").fetchone()[0] or db.execute("PRAGMA user_version").fetchone()[0]:
                        raise ServiceUsageError("service-usage-link-database-unsupported")
                    db.execute(f"PRAGMA application_id = {_APP_ID}")
                    db.execute("PRAGMA user_version = 1")
                    for statement in _SCHEMA.values():
                        db.execute(statement)
                    db.execute("INSERT INTO usage_link_limits VALUES (1, ?)", (self.max_links,))
                self._check(db)
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-link-create-failed-inspect-store") from None

    async def bind(self, link: ServiceUsageRunLink, *, confirm_write: bool = False) -> None:
        _write_request(link, confirm_write)
        await _worker(lambda: self._bind(link))

    def _bind(self, link: ServiceUsageRunLink) -> None:
        try:
            with closing(self._connect("rw")) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._check(db)
                row = db.execute(f"SELECT {_COLUMNS} FROM usage_run_links WHERE run_id = ?", (link.run_id,)).fetchone()
                if row is not None:
                    if ServiceUsageRunLink(*row) != link:
                        raise ServiceUsageError("service-usage-link-conflict")
                    return
                if db.execute("SELECT count(*) FROM usage_run_links").fetchone()[0] >= self.max_links:
                    raise ServiceUsageError("service-usage-link-capacity-exceeded")
                db.execute("INSERT INTO usage_run_links VALUES (?, ?, ?)", (link.run_id, link.session_id, link.operation_id))
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-link-write-failed-inspect-store") from None

    async def get(self, run_id: str) -> ServiceUsageRunLink | None:
        _run_id(run_id)
        rows = await _worker(lambda: self._query("run_id", run_id))
        return rows[0] if rows else None

    async def for_session(self, session_id: str) -> tuple[ServiceUsageRunLink, ...]:
        _run_id(session_id)
        return await _worker(lambda: self._query("session_id", session_id))

    async def for_operation(self, operation_id: str) -> tuple[ServiceUsageRunLink, ...]:
        _label(operation_id)
        return await _worker(lambda: self._query("operation_id", operation_id))

    def _query(self, column: str, identity: str) -> tuple[ServiceUsageRunLink, ...]:
        if column not in {"run_id", "session_id", "operation_id"}:
            raise ServiceUsageError("service-usage-link-query-invalid")
        try:
            with closing(self._connect("ro")) as db:
                db.execute("BEGIN")
                self._check(db)
                rows = db.execute(f"SELECT {_COLUMNS} FROM usage_run_links WHERE {column} = ? ORDER BY run_id LIMIT ?",
                                  (identity, self.max_links + 1)).fetchall()
                if len(rows) > self.max_links:
                    raise ValueError("capacity exceeded")
                links = tuple(ServiceUsageRunLink(*row) for row in rows)
                if any(getattr(link, column) != identity for link in links):
                    raise ValueError("query identity mismatch")
                return links
        except ServiceUsageError:
            raise
        except Exception:
            raise ServiceUsageError("service-usage-link-read-failed") from None
