"""SQLite journals for exact OpenAI Responses event continuation.

Journals contain model output, including tool arguments and inline media. They
are local application data, not encrypted storage. Authentication headers are
bound by digest rather than stored directly.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .http_provider import HttpStreamFrame
from .types import ModelStreamProtocolError


@dataclass(frozen=True, slots=True)
class ResponsesCheckpoint:
    stream_id: str
    response_id: str
    sequence: int
    event_offset: int
    frames: tuple[HttpStreamFrame, ...]


class ResponsesCheckpointStore(Protocol):
    """Replaceable journal selected explicitly by the host.

    Frames and cursors must be committed before returning. A binding mismatch or
    changed frame at the same generation/sequence must fail, never overwrite.
    ``load`` returns the ordered frame prefix ending at the cursor's sequence.
    """

    def create(self, binding: str, response_id: str) -> str: ...

    def append(self, stream_id: str, sequence: int, frame: HttpStreamFrame) -> None: ...

    def cursor(self, stream_id: str, sequence: int, event_offset: int) -> str: ...

    def load(self, cursor: str, binding: str) -> ResponsesCheckpoint: ...


class SqliteResponsesCheckpointStore:
    """Durable opaque cursors, with one stored wire frame per generation/sequence.

    The caller owns the database lifecycle. Cursors remain valid until explicit
    deletion; the upstream response can expire sooner. Each operation uses its
    own connection so newly constructed providers/processes can use the journal.
    """

    def __init__(
        self, path: str | Path, *, max_frames_per_stream: int = 100_000,
        max_frame_bytes: int = 32 * 1024 * 1024,
        max_stream_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.path = Path(path).resolve()
        if str(path) == ":memory:":
            raise ValueError("checkpoints require a persistent SQLite path")
        for value in (max_frames_per_stream, max_frame_bytes, max_stream_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("checkpoint limits must be positive integers")
        self.max_frames_per_stream = max_frames_per_stream
        self.max_frame_bytes = max_frame_bytes
        self.max_stream_bytes = max_stream_bytes
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            objects = connection.execute(
                "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if application_id == 0 and version == 0 and not objects:
                connection.execute("PRAGMA application_id=1465008976")
                connection.execute("PRAGMA user_version=1")
                connection.execute("""CREATE TABLE responses_streams (
                    stream_id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                    response_id TEXT NOT NULL, frame_count INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0
                )""")
                connection.execute("""CREATE TABLE responses_frames (
                    stream_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (stream_id, sequence)
                )""")
                connection.execute("""CREATE TABLE responses_cursors (
                    cursor TEXT PRIMARY KEY, stream_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL, event_offset INTEGER NOT NULL,
                    UNIQUE (stream_id, sequence, event_offset)
                )""")
            elif application_id != 1465008976 or version != 1:
                raise ValueError("not a supported Responses checkpoint database")
            self._validate_schema(connection)

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        expected = {
            "responses_streams": [("stream_id", "TEXT", 0, 1), ("binding", "TEXT", 1, 0),
                                  ("response_id", "TEXT", 1, 0), ("frame_count", "INTEGER", 1, 0),
                                  ("total_bytes", "INTEGER", 1, 0)],
            "responses_frames": [("stream_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
                                 ("payload", "TEXT", 1, 0)],
            "responses_cursors": [("cursor", "TEXT", 0, 1), ("stream_id", "TEXT", 1, 0),
                                  ("sequence", "INTEGER", 1, 0), ("event_offset", "INTEGER", 1, 0)],
        }
        objects = connection.execute(
            "SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if set(objects) != {(name, "table") for name in expected}:
            raise ValueError("checkpoint database has an unexpected schema")
        for table, columns in expected.items():
            actual = [(row[1], row[2], row[3], row[5]) for row in connection.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                raise ValueError("checkpoint database has incompatible columns")
        indexes = connection.execute("PRAGMA index_list(responses_cursors)").fetchall()
        if not any(
            row[2] == 1 and row[3] == "u" and
            [value[2] for value in connection.execute("SELECT * FROM pragma_index_info(?)", (row[1],))]
            == ["stream_id", "sequence", "event_offset"] for row in indexes
        ):
            raise ValueError("checkpoint database lacks unique cursor positions")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, binding: str, response_id: str) -> str:
        stream_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO responses_streams (stream_id,binding,response_id) VALUES (?, ?, ?)",
                (stream_id, binding, response_id),
            )
        return stream_id

    def append(self, stream_id: str, sequence: int, frame: HttpStreamFrame) -> None:
        if (
            isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0
            or frame.data.get("sequence_number") != sequence
        ):
            raise ModelStreamProtocolError("checkpoint frame sequence is invalid")
        payload = json.dumps(
            {"data": dict(frame.data), "event": frame.event},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        size = len(payload.encode("utf-8"))
        if size > self.max_frame_bytes:
            raise ModelStreamProtocolError("checkpoint frame byte limit exceeded")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored = connection.execute(
                "SELECT payload FROM responses_frames WHERE stream_id=? AND sequence=?",
                (stream_id, sequence),
            ).fetchone()
            if stored is not None:
                if stored[0] != payload:
                    raise ModelStreamProtocolError("resumed frame conflicts with journal")
                return
            totals = connection.execute(
                "SELECT frame_count,total_bytes FROM responses_streams WHERE stream_id=?",
                (stream_id,),
            ).fetchone()
            if totals is None:
                raise ModelStreamProtocolError("unknown checkpoint generation")
            if totals[0] >= self.max_frames_per_stream or totals[1] + size > self.max_stream_bytes:
                raise ModelStreamProtocolError("checkpoint generation storage limit exceeded")
            connection.execute("INSERT INTO responses_frames VALUES (?, ?, ?)", (stream_id, sequence, payload))
            connection.execute(
                "UPDATE responses_streams SET frame_count=frame_count+1,total_bytes=total_bytes+? WHERE stream_id=?",
                (size, stream_id),
            )

    def cursor(self, stream_id: str, sequence: int, event_offset: int) -> str:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO responses_cursors VALUES (?, ?, ?, ?)",
                (uuid4().hex, stream_id, sequence, event_offset),
            )
            row = connection.execute(
                "SELECT cursor FROM responses_cursors "
                "WHERE stream_id=? AND sequence=? AND event_offset=?",
                (stream_id, sequence, event_offset),
            ).fetchone()
        return row[0]

    def load(self, cursor: str, binding: str) -> ResponsesCheckpoint:
        with self._connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT s.stream_id,s.response_id,c.sequence,c.event_offset,s.binding "
                "FROM responses_cursors c JOIN responses_streams s "
                "ON s.stream_id=c.stream_id WHERE c.cursor=?", (cursor,),
            ).fetchone()
            if row is None or row[4] != binding:
                raise ModelStreamProtocolError("unknown cursor or request binding mismatch")
            if (
                not isinstance(row[1], str) or not row[1]
                or not isinstance(row[2], int) or row[2] < 0
                or not isinstance(row[3], int) or row[3] < 1
            ):
                raise ModelStreamProtocolError("checkpoint record is invalid")
            payloads = connection.execute(
                "SELECT sequence,payload FROM responses_frames WHERE stream_id=? "
                "AND sequence<=? ORDER BY sequence", (row[0], row[2]),
            ).fetchall()
        frames = []
        if not payloads or payloads[-1][0] != row[2]:
            raise ModelStreamProtocolError("checkpoint frame prefix is missing")
        for sequence, payload in payloads:
            try:
                value = json.loads(payload)
                frame = HttpStreamFrame(value["data"], value["event"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ModelStreamProtocolError("checkpoint frame record is invalid") from exc
            if sequence < 0 or frame.data.get("sequence_number") != sequence:
                raise ModelStreamProtocolError("checkpoint frame sequence is invalid")
            frames.append(frame)
        return ResponsesCheckpoint(*row[:4], tuple(frames))

    def delete(self, cursor: str) -> bool:
        """Delete the entire generation addressed by a cursor, including siblings."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stream_id FROM responses_cursors WHERE cursor=?", (cursor,),
            ).fetchone()
            if row is None:
                return False
            for table in ("responses_cursors", "responses_frames", "responses_streams"):
                connection.execute(f"DELETE FROM {table} WHERE stream_id=?", row)
        return True
