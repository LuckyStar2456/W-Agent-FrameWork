"""Timeout helpers for regular and streaming LLM calls."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable

from w_agent.exceptions.framework_errors import LLMTimeoutError


async def _await_with_timeout(awaitable: Awaitable[Any], timeout: float) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise LLMTimeoutError(f"LLM call exceeded timeout {timeout}s") from exc


async def _iterate_with_timeout(
    stream: AsyncIterator[Any], total_timeout: float, partial_timeout: float
):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout
    iterator = stream.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise LLMTimeoutError(f"LLM stream exceeded timeout {total_timeout}s")
        chunk_timeout = min(partial_timeout, remaining)
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), timeout=chunk_timeout)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            if remaining <= partial_timeout:
                message = f"LLM stream exceeded timeout {total_timeout}s"
            else:
                message = f"LLM stream produced no chunk within {partial_timeout}s"
            raise LLMTimeoutError(message) from exc
        yield chunk


def call_with_timeout(coro, timeout: float, partial_timeout: float | None = None):
    """Apply a timeout to an awaitable or async stream.

    Regular usage remains ``await call_with_timeout(coro, timeout)``. Streaming
    usage is ``async for chunk in call_with_timeout(stream, total, partial)``.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if partial_timeout is None:
        return _await_with_timeout(coro, timeout)
    if partial_timeout <= 0:
        raise ValueError("partial_timeout must be positive")
    if not hasattr(coro, "__aiter__"):
        raise TypeError("partial_timeout requires an async iterator")
    return _iterate_with_timeout(coro, timeout, partial_timeout)
