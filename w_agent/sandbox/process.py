"""Bounded shell-free subprocess runner shared by sandbox providers."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from w_agent.models import CancellationToken

from .types import (
    SandboxExecutionError,
    SandboxOutputTooLarge,
    SandboxResult,
    SandboxTimeoutError,
)


class LocalProcessRunner:
    async def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        inherit_environment: bool = True,
        timeout: float = 30,
        max_output_bytes: int = 1_048_576,
        cancellation: CancellationToken | None = None,
    ) -> SandboxResult:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        process_environment = dict(os.environ) if inherit_environment else {}
        process_environment.update(environment or {})
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=None if cwd is None else str(cwd),
                env=process_environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise SandboxExecutionError("sandbox executable could not start") from exc
        cancellation_task = None
        if cancellation is not None:
            cancellation_task = asyncio.create_task(cancellation.wait())
        communicate_task = asyncio.create_task(
            _bounded_communicate(process, max_output_bytes)
        )
        try:
            async with asyncio.timeout(timeout):
                if cancellation_task is None:
                    stdout, stderr = await communicate_task
                else:
                    done, _ = await asyncio.wait(
                        (communicate_task, cancellation_task),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if cancellation_task in done:
                        communicate_task.cancel()
                        await _terminate(process)
                        await asyncio.gather(
                            communicate_task,
                            return_exceptions=True,
                        )
                        raise asyncio.CancelledError
                    stdout, stderr = await communicate_task
        except TimeoutError as exc:
            communicate_task.cancel()
            await _terminate(process)
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise SandboxTimeoutError("sandbox command timed out") from exc
        except SandboxOutputTooLarge:
            communicate_task.cancel()
            await _terminate(process)
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise
        except asyncio.CancelledError:
            communicate_task.cancel()
            await _terminate(process)
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise
        except Exception as exc:
            communicate_task.cancel()
            await _terminate(process)
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise SandboxExecutionError("sandbox command failed") from exc
        finally:
            if cancellation_task is not None:
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)
        return SandboxResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )


async def _bounded_communicate(
    process: asyncio.subprocess.Process,
    limit: int,
) -> tuple[bytes, bytes]:
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, limit))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, limit))
    wait_task = asyncio.create_task(process.wait())
    tasks = (stdout_task, stderr_task, wait_task)
    try:
        stdout, stderr, _ = await asyncio.gather(*tasks)
        return stdout, stderr
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _read_bounded(stream: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise SandboxOutputTooLarge("sandbox output exceeded its byte limit")
        chunks.append(chunk)


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        process.kill()
        await process.wait()
