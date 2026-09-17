"""Shell-free local command tool template with bounded captured output."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from w_agent.models import ToolDefinition

from .types import ToolBinding, ToolExecutionContext, ToolSideEffect


CommandArgumentBuilder = Callable[[Mapping[str, Any]], Sequence[str]]


class CommandToolError(RuntimeError):
    """A local command could not produce a valid tool result."""


class CommandOutputTooLarge(CommandToolError):
    """A command exceeded the configured stdout or stderr limit."""


class CommandExitError(CommandToolError):
    """A command exited with a non-zero status while checking was enabled."""


def command_tool(
    name: str,
    description: str,
    input_schema: Mapping[str, Any],
    *,
    executable: str | Path,
    argument_builder: CommandArgumentBuilder,
    base_arguments: Sequence[str] = (),
    cwd: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
    inherit_environment: bool = True,
    check: bool = True,
    max_output_bytes: int = 1_048_576,
    encoding: str = "utf-8",
    side_effect: ToolSideEffect = ToolSideEffect.EXTERNAL,
    required_permissions: frozenset[str] = frozenset({"process.execute"}),
) -> ToolBinding:
    """Create a command binding that never invokes a shell.

    ``argument_builder`` returns individual argv values. They are passed to
    ``create_subprocess_exec`` without interpolation, so shell metacharacters
    remain ordinary argument content.
    """

    executable_text = str(executable)
    resolved_cwd = None if cwd is None else str(Path(cwd).resolve())
    base = _validate_argv(base_arguments)
    if not name.strip() or not executable_text.strip():
        raise ValueError("command tool name and executable must not be empty")
    if max_output_bytes <= 0:
        raise ValueError("command output limit must be positive")
    definition = ToolDefinition(name, description, dict(input_schema))

    async def handler(
        arguments: Mapping[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        if context.cancellation is not None:
            context.cancellation.raise_if_cancelled()
        built = _validate_argv(argument_builder(arguments))
        process_environment = dict(os.environ) if inherit_environment else {}
        process_environment.update(environment or {})
        creationflags = 0x08000000 if os.name == "nt" else 0
        process = await asyncio.create_subprocess_exec(
            executable_text,
            *base,
            *built,
            cwd=resolved_cwd,
            env=process_environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        try:
            stdout, stderr = await _bounded_communicate(
                process,
                max_output_bytes,
            )
        except asyncio.CancelledError:
            await _terminate(process)
            raise
        if check and process.returncode != 0:
            raise CommandExitError(f"command exited with status {process.returncode}")
        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode(encoding, errors="replace"),
            "stderr": stderr.decode(encoding, errors="replace"),
        }

    return ToolBinding(
        definition,
        handler,
        side_effect,
        required_permissions,
        metadata={"adapter": "command", "executable": executable_text},
    )


def _validate_argv(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) for value in result):
        raise TypeError("command argument_builder must return strings")
    if any("\0" in value for value in result):
        raise ValueError("command arguments must not contain NUL bytes")
    return result


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
    except Exception:
        await _terminate(process)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _read_bounded(
    stream: asyncio.StreamReader,
    limit: int,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise CommandOutputTooLarge("command output exceeded its byte limit")
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
