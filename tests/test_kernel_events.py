from builtins import ExceptionGroup

import pytest

from w_agent import EventDispatcher, EventStop


@pytest.mark.asyncio
async def test_event_modes_and_listener_disposal():
    events = EventDispatcher()
    heard = []
    first_registration = events.on(
        "notice", lambda payload: heard.append(("a", payload))
    )
    events.on("notice", lambda payload: heard.append(("b", payload)))

    await events.publish("notice", 1)
    first_registration.dispose()
    await events.publish("notice", 2)

    assert heard == [("a", 1), ("b", 1), ("b", 2)]

    events.on("choice", lambda _payload: None)
    events.on("choice", lambda payload: payload * 2)
    assert await events.first("choice", 3) == 6

    events.on("serial", lambda payload: payload)
    events.on("serial", lambda payload: EventStop(payload + 1))
    events.on("serial", lambda _payload: pytest.fail("serial should have stopped"))
    assert await events.serial("serial", 5) == 6


@pytest.mark.asyncio
async def test_pipeline_wraps_and_rewrites_downstream_payload():
    events = EventDispatcher()
    order = []

    async def outer(payload, next_handler):
        order.append(f"outer:{payload}")
        result = await next_handler(payload + 1)
        order.append("outer:end")
        return result + 10

    async def inner(payload, next_handler):
        order.append(f"inner:{payload}")
        return await next_handler(payload * 2)

    events.on("transform", outer)
    events.on("transform", inner)

    result = await events.pipeline("transform", 2, lambda value: value + 3)

    assert result == 19
    assert order == ["outer:2", "inner:3", "outer:end"]


@pytest.mark.asyncio
async def test_pipeline_rejects_calling_next_twice():
    events = EventDispatcher()

    async def invalid(payload, next_handler):
        await next_handler(payload)
        return await next_handler(payload)

    events.on("invalid", invalid)

    with pytest.raises(RuntimeError, match="only once"):
        await events.pipeline("invalid", 1, lambda value: value)


@pytest.mark.asyncio
async def test_publish_runs_remaining_listeners_and_aggregates_failures():
    events = EventDispatcher()
    heard = []

    def fail(_payload):
        raise ValueError("broken")

    events.on("notice", fail)
    events.on("notice", lambda payload: heard.append(payload))

    with pytest.raises(ExceptionGroup) as error:
        await events.publish("notice", "value")

    assert heard == ["value"]
    assert isinstance(error.value.exceptions[0], ValueError)
