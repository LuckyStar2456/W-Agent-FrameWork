"""Invocation engines shared by context-managed sync, async and stream proxies."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Iterator

from .aspects import AspectError, InvocationOutcome


def combine(primary, failures):
    errors = ([primary] if primary is not None else []) + failures
    if not errors:
        return
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup("invocation and cleanup failed", errors) from None


async def drain(task):
    """Finish cleanup despite repeated waiter cancellation, then propagate it."""
    cancelled = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancelled = cancelled or error
        except BaseException:
            break
    try:
        result = task.result()
    except BaseException as failure:
        if cancelled is not None and not isinstance(failure, asyncio.CancelledError):
            combine(cancelled, [failure])
        raise
    if cancelled is not None:
        raise cancelled
    return result


def status(error, closed=False):
    if isinstance(error, (GeneratorExit,)) or closed:
        return "closed"
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    return "error" if error is not None else "success"


def sync_call(callback, *args):
    result = callback(*args)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise AspectError("synchronous advice cannot return an awaitable")
    return result


async def async_call(callback, *args):
    result = callback(*args)
    return await result if inspect.isawaitable(result) else result


class Proceed:
    """A single-use, lexical continuation, not an implicit retry facility."""

    def __init__(self, call):
        self.call, self.used, self.active = call, False, True
        self.result = None

    def __call__(self):
        if not self.active or self.used:
            raise AspectError("proceed is single-use and expires with its advice")
        self.used = True
        self.result = self.call()
        return self.result

    def expire(self):
        self.active = False
        if inspect.iscoroutine(self.result) and inspect.getcoroutinestate(self.result) != inspect.CORO_CLOSED:
            self.result.close()
            raise AspectError("asynchronous proceed must be fully awaited by its advice")


def finish_sync(advice, invocation, outcome, closers=()):
    failures = []
    for close in closers:
        try:
            sync_call(close)
        except BaseException as error:
            failures.append(error)
    hooks = []
    if outcome.status in ("error", "cancelled") and advice.on_error is not None:
        hooks.append((advice.on_error, outcome.error))
    if advice.finally_ is not None:
        hooks.append((advice.finally_, outcome))
    for hook, value in hooks:
        try:
            sync_call(hook, invocation, value)
        except BaseException as error:
            failures.append(error)
    return failures


async def finish_async(advice, invocation, outcome, closers=()):
    failures = []
    for close in closers:
        try:
            await async_call(close)
        except BaseException as error:
            failures.append(error)
    hooks = []
    if outcome.status in ("error", "cancelled") and advice.on_error is not None:
        hooks.append((advice.on_error, outcome.error))
    if advice.finally_ is not None:
        hooks.append((advice.finally_, outcome))
    for hook, value in hooks:
        try:
            await async_call(hook, invocation, value)
        except BaseException as error:
            failures.append(error)
    return failures


def invoke_sync(invocation, method, advices):
    def layer(index):
        if index == len(advices):
            return _target()
        advice, primary, result = advices[index], None, None
        proceed = Proceed(lambda: layer(index + 1))
        try:
            if advice.before is not None:
                sync_call(advice.before, invocation)
            result = (sync_call(advice.around, invocation, proceed)
                      if advice.around is not None else proceed())
            if advice.after is not None:
                sync_call(advice.after, invocation, result)
        except BaseException as error:
            primary = error
        finally:
            proceed.active = False
        failures = finish_sync(advice, invocation, InvocationOutcome(status(primary), result, primary))
        combine(primary, failures)
        return result

    def _target():
        result = method(*invocation.args, **invocation.kwargs)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise AspectError("declare kind='async' for an awaitable-returning method")
        return result

    return layer(0)


async def invoke_async(invocation, method, advices):
    async def layer(index):
        if index == len(advices):
            result = method(*invocation.args, **invocation.kwargs)
            return await result if inspect.isawaitable(result) else result
        advice, primary, result = advices[index], None, None
        owner = asyncio.current_task()

        async def advance():
            if asyncio.current_task() is not owner:
                raise AspectError("proceed cannot escape into another task")
            return await layer(index + 1)

        proceed = Proceed(advance)
        try:
            if advice.before is not None:
                await async_call(advice.before, invocation)
            result = (await async_call(advice.around, invocation, proceed)
                      if advice.around is not None else await proceed())
            proceed.expire()
            if advice.after is not None:
                await async_call(advice.after, invocation, result)
        except BaseException as error:
            primary = error
        try:
            proceed.expire()
        except BaseException as error:
            primary = error if primary is None else BaseExceptionGroup("advice continuation failed", [primary, error])
        outcome = InvocationOutcome(status(primary), result, primary)
        failures = await drain(asyncio.create_task(finish_async(advice, invocation, outcome)))
        combine(primary, failures)
        return result

    return await layer(0)


def stream_sync(invocation, method, advices):
    closed = {}

    def close_once(source):
        if source is None or id(source) in closed:
            return
        closed[id(source)] = source
        closer = getattr(source, "close", None)
        if closer is not None:
            sync_call(closer)

    def layer(index):
        advice = advices[index] if index < len(advices) else None
        source, primary, failures = None, None, []
        proceed = Proceed(lambda: layer(index + 1))
        try:
            if advice is not None and advice.before is not None:
                sync_call(advice.before, invocation)
            if advice is None:
                source = method(*invocation.args, **invocation.kwargs)
            elif advice.around is not None:
                source = sync_call(advice.around, invocation, proceed)
            else:
                source = proceed()
            if not isinstance(source, Iterator):
                raise AspectError("sync stream advice/target must return an iterator")
            for item in source:
                yield item
            close_once(source)
            close_once(proceed.result)
            if advice is not None and advice.after is not None:
                sync_call(advice.after, invocation, None)
        except BaseException as error:
            primary = error
        finally:
            proceed.active = False
            closers = (lambda: close_once(source), lambda: close_once(proceed.result))
            if advice is not None:
                failures = finish_sync(advice, invocation, InvocationOutcome(status(primary), error=primary), closers)
            else:
                for closer in closers:
                    try:
                        closer()
                    except BaseException as error:
                        failures.append(error)
        combine(None if isinstance(primary, GeneratorExit) else primary, failures)

    return layer(0)


def stream_async(invocation, method, advices):
    closed = {}

    async def close_once(source):
        if source is None or id(source) in closed:
            return
        closed[id(source)] = source
        closer = getattr(source, "aclose", None)
        if closer is not None:
            await async_call(closer)

    async def layer(index):
        advice = advices[index] if index < len(advices) else None
        source, primary, failures = None, None, []
        proceed = Proceed(lambda: layer(index + 1))
        try:
            if advice is not None and advice.before is not None:
                await async_call(advice.before, invocation)
            if advice is None:
                source = method(*invocation.args, **invocation.kwargs)
                if inspect.isawaitable(source):
                    source = await source
            elif advice.around is not None:
                source = await async_call(advice.around, invocation, proceed)
            else:
                source = proceed()
            if not isinstance(source, AsyncIterator):
                raise AspectError("stream advice/target must return an async iterator")
            async for item in source:
                yield item
            await close_once(source)
            await close_once(proceed.result)
            if advice is not None and advice.after is not None:
                await async_call(advice.after, invocation, None)
        except BaseException as error:
            primary = error
        finally:
            proceed.active = False

            async def cleanup():
                closers = (lambda: close_once(source), lambda: close_once(proceed.result))
                outcome = InvocationOutcome(status(primary), error=primary)
                if advice is not None:
                    return await finish_async(advice, invocation, outcome, closers)
                errors = []
                for closer in closers:
                    try:
                        await closer()
                    except BaseException as error:
                        errors.append(error)
                return errors

            failures = await drain(asyncio.create_task(cleanup()))
        combine(None if isinstance(primary, GeneratorExit) else primary, failures)

    return layer(0)
