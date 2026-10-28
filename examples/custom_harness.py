"""Offline custom Harness using only the public application container API.

Copy this file alongside an installation containing the new application API,
or run it from source. The published 2.0.0 package does not include this API.
No model requests, sandbox commands, file writes or default ReAct loop run.
"""

from __future__ import annotations

import asyncio

from w_agent import (
    ApplicationOperation,
    ApplicationProject,
    BorrowedComponent,
    ComponentDefinition,
    ComponentRef,
    compile_assembly,
)


class CustomModel:
    """A developer-defined offline model contract, not an OpenAI request."""

    async def compose(self, question: str, *, dialect: str) -> str:
        return f"{dialect}:{question}"


class NormalizeTool:
    def apply(self, text: str) -> str:
        return text.strip().upper()


class MemoryJournal:
    def __init__(self) -> None:
        self.entries: list[str] = []
        self.closed = False

    def save(self, result: str) -> None:
        if self.closed:
            raise RuntimeError("journal is closed")
        self.entries.append(result)

    def close(self) -> None:
        self.closed = True


class CustomHarness:
    """User algorithm with injected model, ordinary tool, storage and options."""

    def __init__(self, model, tool, journal, options):
        self.model = model
        self.tool = tool
        self.journal = journal
        self.options = options

    async def run(self, question: str) -> str:
        text = await self.model.compose(question, dialect=self.options["dialect"])
        result = self.tool.apply(text)
        self.journal.save(result)
        return result


def create_project() -> ApplicationProject:
    """Use this same explicit entry from Python, CLI or the Application TUI page."""
    plan = compile_assembly([
        ComponentDefinition("model", CustomModel),
        ComponentDefinition("tool", NormalizeTool),
        ComponentDefinition("journal", MemoryJournal, dispose=MemoryJournal.close),
        BorrowedComponent("options", {"dialect": "local"}),
        ComponentDefinition(
            "harness", CustomHarness,
            dependencies={
                "model": ComponentRef("model"),
                "tool": ComponentRef("tool"),
                "journal": ComponentRef("journal"),
                "options": ComponentRef("options"),
            },
            scope="run",
        ),
    ])
    return ApplicationProject(plan, {"run": ApplicationOperation("harness")})


async def run_demo() -> tuple[str, tuple[str, ...], bool]:
    async with create_project().open() as application:
        journal = application.context.resolve("journal")
        result = await application.invoke("run", "hello")
        entries = tuple(journal.entries)
    return result, entries, journal.closed


if __name__ == "__main__":
    output, recorded, closed = asyncio.run(run_demo())
    print(output)
    print(f"records={len(recorded)} journal_closed={closed}")
