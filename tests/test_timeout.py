import asyncio

import pytest

from w_agent.exceptions.framework_errors import LLMTimeoutError
from w_agent.resilience.timeout import call_with_timeout


async def test_regular_call_returns_value():
    async def operation():
        return "ok"

    assert await call_with_timeout(operation(), 0.1) == "ok"


async def test_regular_call_times_out():
    async def operation():
        await asyncio.sleep(0.05)

    with pytest.raises(LLMTimeoutError, match="exceeded timeout"):
        await call_with_timeout(operation(), 0.001)


async def test_stream_applies_per_chunk_timeout():
    async def stream():
        yield 1
        await asyncio.sleep(0.05)
        yield 2

    received = []
    with pytest.raises(LLMTimeoutError, match="no chunk"):
        async for chunk in call_with_timeout(stream(), 1.0, 0.001):
            received.append(chunk)
    assert received == [1]


async def test_stream_returns_all_chunks():
    async def stream():
        yield 1
        yield 2

    result = [chunk async for chunk in call_with_timeout(stream(), 1.0, 0.1)]
    assert result == [1, 2]
