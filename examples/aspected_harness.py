"""Source-only M3 example: python -m examples.aspected_harness."""

import asyncio

from w_agent import (
    ApplicationContext, Aspect, Around, Before, Finally, PreDestroy,
    ServiceComponent, compile_decorated,
)


@Aspect("trace", component="harness", methods=("stream",))
class Trace:
    def __init__(self):
        self.events = []

    @Before
    def before(self, invocation):
        self.events.append(f"start:{invocation.method}")

    @Around
    async def around(self, invocation, proceed):
        async for item in proceed():
            yield item.upper()

    @Finally
    def finished(self, invocation, outcome):
        self.events.append(f"finish:{outcome.status}")


@ServiceComponent("harness")
class CustomHarness:
    def __init__(self):
        self.closed = False

    async def stream(self, text):
        for word in text.split():
            yield word

    @PreDestroy
    def close(self):
        self.closed = True


async def run_demo():
    async with ApplicationContext(compile_decorated([CustomHarness, Trace])) as app:
        harness, trace = app.resolve("harness"), app.resolve("trace")
        output = [word async for word in harness.stream("hello harness")]
    return output, trace.events, harness.closed


if __name__ == "__main__":
    print(asyncio.run(run_demo()))
