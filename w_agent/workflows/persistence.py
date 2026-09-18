"""Append-only workflow events and crash-aware node checkpoints."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol

from w_agent.kernel import ScopePath

from .types import (
    WorkflowCheckpoint,
    WorkflowCheckpointSummary,
    WorkflowCheckpointStatus,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowKind,
)


class WorkflowStoreError(RuntimeError):
    """Persistent workflow state is invalid, conflicting, or unavailable."""


class WorkflowResumeConflictError(WorkflowStoreError):
    """A node checkpoint is already claimed and must not be replayed."""


class WorkflowStore(Protocol):
    async def append(self, event: WorkflowEvent) -> None: ...

    async def events(self, run_id: str) -> tuple[WorkflowEvent, ...]: ...

    async def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None: ...

    async def load_checkpoint(
        self,
        run_id: str,
    ) -> WorkflowCheckpoint | None: ...

    async def claim_checkpoint(self, run_id: str) -> WorkflowCheckpoint: ...

    async def delete_checkpoint(self, run_id: str) -> None: ...


class WorkflowCheckpointCatalog(Protocol):
    """Optional discovery capability kept separate from the stable run store."""

    async def list_checkpoints(self) -> tuple[WorkflowCheckpointSummary, ...]: ...


class InMemoryWorkflowStore:
    """Deterministic workflow store for embedding and tests."""

    def __init__(self) -> None:
        self._events: dict[str, list[WorkflowEvent]] = {}
        self._checkpoints: dict[str, WorkflowCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: WorkflowEvent) -> None:
        async with self._lock:
            events = self._events.setdefault(event.run_id, [])
            if event.sequence != len(events) + 1:
                raise WorkflowStoreError(
                    f"workflow event sequence {event.sequence} does not follow "
                    f"{len(events)}"
                )
            events.append(event)

    async def events(self, run_id: str) -> tuple[WorkflowEvent, ...]:
        async with self._lock:
            return tuple(self._events.get(run_id, ()))

    async def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        async with self._lock:
            self._checkpoints[checkpoint.run_id] = checkpoint

    async def load_checkpoint(
        self,
        run_id: str,
    ) -> WorkflowCheckpoint | None:
        async with self._lock:
            return self._checkpoints.get(run_id)

    async def list_checkpoints(self) -> tuple[WorkflowCheckpointSummary, ...]:
        async with self._lock:
            return tuple(
                WorkflowCheckpointSummary.from_checkpoint(checkpoint)
                for checkpoint in sorted(
                    self._checkpoints.values(),
                    key=lambda item: item.run_id,
                )
            )

    async def claim_checkpoint(self, run_id: str) -> WorkflowCheckpoint:
        async with self._lock:
            checkpoint = self._checkpoints.get(run_id)
            if checkpoint is None:
                raise WorkflowStoreError(f"workflow run {run_id!r} has no checkpoint")
            if checkpoint.status not in {
                WorkflowCheckpointStatus.READY,
                WorkflowCheckpointStatus.PAUSED,
            }:
                raise WorkflowResumeConflictError(
                    f"workflow run {run_id!r} checkpoint is already claimed"
                )
            claimed = replace(
                checkpoint,
                status=WorkflowCheckpointStatus.RESUMING,
            )
            self._checkpoints[run_id] = claimed
            return claimed

    async def delete_checkpoint(self, run_id: str) -> None:
        async with self._lock:
            self._checkpoints.pop(run_id, None)


class JsonlWorkflowStore:
    """Filesystem store for one local owner, with durable event appends."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.runs_root = self.root / "workflows"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    async def append(self, event: WorkflowEvent) -> None:
        await asyncio.to_thread(self._append_sync, event)

    async def events(self, run_id: str) -> tuple[WorkflowEvent, ...]:
        return await asyncio.to_thread(self._events_sync, run_id)

    async def save_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        await asyncio.to_thread(self._save_checkpoint_sync, checkpoint)

    async def load_checkpoint(
        self,
        run_id: str,
    ) -> WorkflowCheckpoint | None:
        return await asyncio.to_thread(self._load_checkpoint_sync, run_id)

    async def list_checkpoints(self) -> tuple[WorkflowCheckpointSummary, ...]:
        return await asyncio.to_thread(self._list_checkpoints_sync)

    async def claim_checkpoint(self, run_id: str) -> WorkflowCheckpoint:
        return await asyncio.to_thread(self._claim_checkpoint_sync, run_id)

    async def delete_checkpoint(self, run_id: str) -> None:
        await asyncio.to_thread(self._delete_checkpoint_sync, run_id)

    def _run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run_id):
            raise ValueError("workflow run id is not safe for local persistence")
        path = (self.runs_root / run_id).resolve()
        if path.parent != self.runs_root:
            raise ValueError("workflow run path escapes the store root")
        return path

    def _append_sync(self, event: WorkflowEvent) -> None:
        with self._lock:
            run_dir = self._run_dir(event.run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            path = run_dir / "events.jsonl"
            current = self._events_sync(event.run_id)
            if event.sequence != len(current) + 1:
                raise WorkflowStoreError(
                    f"workflow event sequence {event.sequence} does not follow "
                    f"{len(current)}"
                )
            payload = json.dumps(
                _event_to_data(event),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(payload + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def _events_sync(self, run_id: str) -> tuple[WorkflowEvent, ...]:
        with self._lock:
            path = self._run_dir(run_id) / "events.jsonl"
            if not path.exists():
                return ()
            try:
                events = tuple(
                    _event_from_data(json.loads(line))
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise WorkflowStoreError(
                    f"workflow run {run_id!r} has an invalid event log"
                ) from exc
            for expected, event in enumerate(events, 1):
                if event.sequence != expected or event.run_id != run_id:
                    raise WorkflowStoreError(
                        f"workflow run {run_id!r} has a corrupt event log"
                    )
            return events

    def _save_checkpoint_sync(self, checkpoint: WorkflowCheckpoint) -> None:
        with self._lock:
            path = self._run_dir(checkpoint.run_id) / "checkpoint.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(path, _checkpoint_to_data(checkpoint))

    def _load_checkpoint_sync(
        self,
        run_id: str,
    ) -> WorkflowCheckpoint | None:
        with self._lock:
            path = self._run_dir(run_id) / "checkpoint.json"
            if not path.exists():
                return None
            try:
                checkpoint = _checkpoint_from_data(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise WorkflowStoreError(
                    f"workflow run {run_id!r} has an invalid checkpoint"
                ) from exc
            if checkpoint.run_id != run_id:
                raise WorkflowStoreError(
                    f"workflow run {run_id!r} checkpoint identity differs"
                )
            return checkpoint

    def _list_checkpoints_sync(self) -> tuple[WorkflowCheckpointSummary, ...]:
        with self._lock:
            summaries: list[WorkflowCheckpointSummary] = []
            for run_dir in sorted(self.runs_root.iterdir(), key=lambda path: path.name):
                if not run_dir.is_dir() or not (run_dir / "checkpoint.json").is_file():
                    continue
                checkpoint = self._load_checkpoint_sync(run_dir.name)
                if checkpoint is not None:
                    summaries.append(
                        WorkflowCheckpointSummary.from_checkpoint(checkpoint)
                    )
            return tuple(summaries)

    def _claim_checkpoint_sync(self, run_id: str) -> WorkflowCheckpoint:
        with self._lock:
            checkpoint = self._load_checkpoint_sync(run_id)
            if checkpoint is None:
                raise WorkflowStoreError(f"workflow run {run_id!r} has no checkpoint")
            if checkpoint.status not in {
                WorkflowCheckpointStatus.READY,
                WorkflowCheckpointStatus.PAUSED,
            }:
                raise WorkflowResumeConflictError(
                    f"workflow run {run_id!r} checkpoint is already claimed"
                )
            claimed = replace(
                checkpoint,
                status=WorkflowCheckpointStatus.RESUMING,
            )
            self._save_checkpoint_sync(claimed)
            return claimed

    def _delete_checkpoint_sync(self, run_id: str) -> None:
        with self._lock:
            path = self._run_dir(run_id) / "checkpoint.json"
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _event_to_data(event: WorkflowEvent) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sequence": event.sequence,
        "type": event.type.value,
        "run_id": event.run_id,
        "session_id": event.session_id,
        "created_at": event.created_at.isoformat(),
        "data": _json_value(event.data),
    }


def _event_from_data(data: Mapping[str, Any]) -> WorkflowEvent:
    if data.get("schema_version") != 1:
        raise WorkflowStoreError("unsupported workflow event schema version")
    return WorkflowEvent(
        int(data["sequence"]),
        WorkflowEventType(str(data["type"])),
        str(data["run_id"]),
        _mapping(data.get("data", {}), "workflow event data"),
        session_id=_optional_string(data.get("session_id")),
        created_at=datetime.fromisoformat(str(data["created_at"])),
    )


def _checkpoint_to_data(checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
    return {
        "schema_version": checkpoint.schema_version,
        "run_id": checkpoint.run_id,
        "workflow_name": checkpoint.workflow_name,
        "workflow_version": checkpoint.workflow_version,
        "kind": checkpoint.kind.value,
        "scope": [[part.kind, part.value] for part in checkpoint.scope],
        "input": _json_value(checkpoint.input),
        "state": _json_value(checkpoint.state),
        "outputs": _json_value(checkpoint.outputs),
        "completed_nodes": list(checkpoint.completed_nodes),
        "remaining_nodes": list(checkpoint.remaining_nodes),
        "current_node": checkpoint.current_node,
        "graph_steps": checkpoint.graph_steps,
        "resume_count": checkpoint.resume_count,
        "session_id": checkpoint.session_id,
        "metadata": _json_value(checkpoint.metadata),
        "status": checkpoint.status.value,
    }


def _checkpoint_from_data(data: Mapping[str, Any]) -> WorkflowCheckpoint:
    if data.get("schema_version") != 1:
        raise WorkflowStoreError("unsupported workflow checkpoint schema version")
    scope_data = data["scope"]
    if not isinstance(scope_data, list):
        raise WorkflowStoreError("workflow checkpoint scope must be a list")
    pairs: list[tuple[str, str]] = []
    for pair in scope_data:
        if not isinstance(pair, list) or len(pair) != 2:
            raise WorkflowStoreError("workflow checkpoint scope is invalid")
        pairs.append((str(pair[0]), str(pair[1])))
    return WorkflowCheckpoint(
        run_id=str(data["run_id"]),
        workflow_name=str(data["workflow_name"]),
        workflow_version=str(data["workflow_version"]),
        kind=WorkflowKind(str(data["kind"])),
        scope=ScopePath.from_pairs(pairs),
        input=data.get("input"),
        state=_mapping(data.get("state", {}), "workflow state"),
        outputs=_mapping(data.get("outputs", {}), "workflow outputs"),
        completed_nodes=_strings(data.get("completed_nodes", [])),
        remaining_nodes=_strings(data.get("remaining_nodes", [])),
        current_node=_optional_string(data.get("current_node")),
        graph_steps=int(data.get("graph_steps", 0)),
        resume_count=int(data.get("resume_count", 0)),
        session_id=_optional_string(data.get("session_id")),
        metadata=_mapping(data.get("metadata", {}), "workflow metadata"),
        status=WorkflowCheckpointStatus(str(data["status"])),
        schema_version=int(data["schema_version"]),
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowStoreError(f"{label} must be an object")
    return value


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise WorkflowStoreError("workflow node collection must be a list")
    return tuple(str(item) for item in value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"value {type(value).__name__} is not JSON serializable")
