"""Typed-by-convention event and pipeline dispatcher for plugins."""

from __future__ import annotations

import inspect
from builtins import ExceptionGroup
from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable

from .registry import Registration


Listener = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class EventStop:
    """Ask serial dispatch to stop and return ``value``."""

    value: Any = None


class EventDispatcher:
    """Dispatch broadcast, first-result, serial, and pipeline events."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}
        self._lock = RLock()

    def on(self, event: str, listener: Listener) -> Registration:
        """Register one listener and return a disposal handle."""

        if not event or not event.strip():
            raise ValueError("event name must not be empty")
        if not callable(listener):
            raise TypeError("event listener must be callable")
        with self._lock:
            self._listeners.setdefault(event, []).append(listener)

        def dispose() -> None:
            with self._lock:
                listeners = self._listeners.get(event)
                if not listeners:
                    return
                try:
                    listeners.remove(listener)
                except ValueError:
                    return
                if not listeners:
                    self._listeners.pop(event, None)

        return Registration(dispose)

    def listeners(self, event: str) -> tuple[Listener, ...]:
        """Return a stable listener snapshot for an event."""

        with self._lock:
            return tuple(self._listeners.get(event, ()))

    async def publish(self, event: str, payload: Any = None) -> None:
        """Run every listener and aggregate failures after broadcast."""

        failures: list[Exception] = []
        for listener in self.listeners(event):
            try:
                await _await_if_needed(listener(payload))
            except Exception as exc:  # noqa: BLE001 - aggregate plugin failures
                failures.append(exc)
        if failures:
            raise ExceptionGroup(f"event {event!r} listeners failed", failures)

    async def first(self, event: str, payload: Any = None) -> Any:
        """Return the first listener result that is not ``None``."""

        for listener in self.listeners(event):
            result = await _await_if_needed(listener(payload))
            if result is not None:
                return result
        return None

    async def serial(self, event: str, payload: Any = None) -> tuple[Any, ...] | Any:
        """Run listeners in order, stopping when one returns ``EventStop``."""

        results: list[Any] = []
        for listener in self.listeners(event):
            result = await _await_if_needed(listener(payload))
            if isinstance(result, EventStop):
                return result.value
            results.append(result)
        return tuple(results)

    async def pipeline(
        self,
        event: str,
        payload: Any,
        terminal: Callable[[Any], Any],
    ) -> Any:
        """Run a middleware pipeline whose listeners explicitly delegate."""

        listeners = self.listeners(event)

        async def invoke(index: int, current: Any) -> Any:
            if index == len(listeners):
                return await _await_if_needed(terminal(current))

            delegated = False

            async def next_handler(next_payload: Any = current) -> Any:
                nonlocal delegated
                if delegated:
                    raise RuntimeError("pipeline next() may be called only once")
                delegated = True
                return await invoke(index + 1, next_payload)

            return await _await_if_needed(listeners[index](current, next_handler))

        return await invoke(0, payload)


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
