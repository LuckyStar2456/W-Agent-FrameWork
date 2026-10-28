"""Optional application-owned workflow pause requests."""

from __future__ import annotations

from threading import Lock
from typing import Protocol


class WorkflowPauseSource(Protocol):
    """Fast boundary query; implementations do not execute workflows.

    Sources may use bounded local I/O. Failures must raise instead of silently
    returning False, which could execute a node despite an unreadable request.
    """

    def is_pause_requested(self, run_id: str) -> bool: ...


class WorkflowPauseController:
    """Thread-safe, process-local pause requests keyed by exact run ID.

    Requests remain set until explicitly cleared. Clearing a request does not
    resume a workflow. Share a controller only within one store's run namespace.
    """

    def __init__(self) -> None:
        self._requested: set[str] = set()
        self._lock = Lock()

    def request_pause(self, run_id: str) -> None:
        _validate_run_id(run_id)
        with self._lock:
            self._requested.add(run_id)

    def clear(self, run_id: str) -> None:
        _validate_run_id(run_id)
        with self._lock:
            self._requested.discard(run_id)

    def is_pause_requested(self, run_id: str) -> bool:
        _validate_run_id(run_id)
        with self._lock:
            return run_id in self._requested


class AnyWorkflowPauseSource:
    """Read-only, ordered OR composition of application-owned pause sources.

    Stops querying after the first positive response. Errors from a queried
    source propagate; sources are never cleared or otherwise managed here.
    Every source must address the same run namespace. This is not an atomic
    snapshot across sources and does not add execution ownership or polling.
    """

    def __init__(self, *sources: WorkflowPauseSource) -> None:
        if not sources:
            raise ValueError("at least one workflow pause source is required")
        if any(
            not callable(getattr(source, "is_pause_requested", None))
            for source in sources
        ):
            raise ValueError("workflow pause source needs an is_pause_requested method")
        self._sources = tuple(sources)

    def is_pause_requested(self, run_id: str) -> bool:
        _validate_run_id(run_id)
        for source in self._sources:
            requested = source.is_pause_requested(run_id)
            if not isinstance(requested, bool):
                raise TypeError("workflow pause source must return a bool")
            if requested:
                return True
        return False


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("workflow pause run id must not be empty")
