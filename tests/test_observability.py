import asyncio
import inspect

from w_agent.observability.logging import LogEnable
from w_agent.observability.metrics import track


async def test_log_decorator_preserves_and_awaits_async_function():
    calls = []

    @LogEnable(log_args=False, log_result=False, log_duration=False)
    async def operation():
        await asyncio.sleep(0)
        calls.append("done")
        return "ok"

    assert inspect.iscoroutinefunction(operation)
    assert await operation() == "ok"
    assert calls == ["done"]


async def test_metrics_decorator_preserves_async_function():
    @track
    async def operation():
        await asyncio.sleep(0)
        return "ok"

    assert inspect.iscoroutinefunction(operation)
    assert await operation() == "ok"
