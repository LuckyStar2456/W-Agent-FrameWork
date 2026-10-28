"""Source-only M2 example: python -m examples.annotated_harness."""

from __future__ import annotations

import asyncio
import sys
from typing import Annotated

from w_agent import (
    AgentComponent, ApplicationContext, Bean, Configuration, PostConstruct,
    PreDestroy, RepositoryComponent, Value, compile_decorated, scan_components,
)


@RepositoryComponent("journal")
class Journal:
    def __init__(self):
        self.entries: list[str] = []
        self.closed = False

    @PreDestroy
    def close(self):
        self.closed = True


class CustomModel:
    def __init__(self, dialect: str):
        self.dialect = dialect

    async def compose(self, text: str) -> str:
        return f"{self.dialect}:{text.upper()}"


@Configuration("models")
class Models:
    @Bean(name="custom-model")
    def model(self, dialect: Annotated[str, Value("model.dialect", required=True)]) -> CustomModel:
        return CustomModel(dialect)


@AgentComponent("harness", scope="run")
class CustomHarness:
    def __init__(self, model: CustomModel, journal: Journal):
        self.model, self.journal = model, journal
        self.ready = False

    @PostConstruct
    def initialize(self):
        self.ready = True

    async def run(self, text: str) -> str:
        assert self.ready
        result = await self.model.compose(text)
        self.journal.entries.append(result)
        return result


async def run_demo() -> tuple[str, tuple[str, ...], bool]:
    plan = compile_decorated(scan_components(sys.modules[__name__]),
                             values={"model": {"dialect": "LOCAL"}})
    async with ApplicationContext(plan) as app:
        journal = app.resolve("journal")
        async with app.scope("run", "demo") as run:
            result = await run.resolve("harness").run("hello")
    return result, tuple(journal.entries), journal.closed


if __name__ == "__main__":
    print(asyncio.run(run_demo()))
