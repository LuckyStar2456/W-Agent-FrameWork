"""Offline annotated support Harness; no API keys, network or file writes."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import sys
from typing import Annotated

from w_agent import (
    AgentComponent, ApplicationOperation, ApplicationProject, Aspect, Before,
    Finally, PostConstruct, PreDestroy, RepositoryComponent, ServiceComponent,
    ToolComponent, Value, compile_decorated, scan_components,
)


@dataclass(frozen=True)
class SupportReply:
    answer: str
    source: str
    handoff: bool


@ServiceComponent("support_model")
class SupportModel:
    """Developer-owned protocol; deterministic stand-in, not a real LLM."""

    async def draft(self, question: str, *, tone: str, fact: str | None) -> SupportReply:
        if fact is None:
            return SupportReply("A human teammate should review this question.", "handoff", True)
        return SupportReply(f"{tone}: {fact}", "local-faq", False)


@ToolComponent("faq")
class FaqTool:
    def lookup(self, question: str) -> str | None:
        if "shipping" in question.casefold():
            return "Demo orders ship within two working days."
        return None


@RepositoryComponent("support_store")
class SupportJournal:
    def __init__(self):
        self.entries: list[SupportReply] = []
        self.lifecycle: list[str] = []
        self.closed = False

    @PostConstruct
    def open(self):
        self.lifecycle.append("store-open")

    def save(self, reply: SupportReply):
        if self.closed:
            raise RuntimeError("journal closed")
        self.entries.append(reply)
        self.lifecycle.append("reply-saved")

    @PreDestroy
    def close(self):
        self.closed = True
        self.lifecycle.append("store-closed")


@Aspect("support_trace", component="support", methods=("answer",))
class SupportTrace:
    def __init__(self):
        self.events: list[str] = []

    @Before
    def started(self, invocation):
        self.events.append(f"before:{invocation.method}")

    @Finally
    def finished(self, invocation, outcome):
        self.events.append(f"finally:{outcome.status}")


@AgentComponent("support", scope="run")
class SupportHarness:
    def __init__(
        self, model: SupportModel, faq: FaqTool, journal: SupportJournal,
        tone: Annotated[str, Value("support.tone", required=True)],
    ):
        self.model, self.faq, self.journal, self.tone = model, faq, journal, tone
        self.ready = False

    @PostConstruct
    def initialize(self):
        self.ready = True
        self.journal.lifecycle.append("harness-ready")

    async def answer(self, question: str) -> dict:
        if not self.ready:
            raise RuntimeError("harness not initialized")
        reply = await self.model.draft(question, tone=self.tone, fact=self.faq.lookup(question))
        self.journal.save(reply)
        return asdict(reply)

    @PreDestroy
    def close(self):
        self.ready = False
        self.journal.lifecycle.append("harness-closed")


def create_project() -> ApplicationProject:
    # Scanning sees only this already imported, explicitly selected module.
    plan = compile_decorated(scan_components(sys.modules[__name__]),
                             values={"support": {"tone": "Friendly"}})
    return ApplicationProject(plan, {"run": ApplicationOperation("support", "answer")}, name="support-demo")


async def run_demo() -> dict:
    async with create_project().open() as host:
        journal = host.context.resolve("support_store")
        trace = host.context.resolve("support_trace")
        reply = await host.invoke("run", "What is your shipping time?")
    return {"reply": reply, "lifecycle": journal.lifecycle, "trace": trace.events,
            "closed": journal.closed}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False))
