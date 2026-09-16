from pathlib import Path

import pytest

from w_agent import BeanFactory


async def test_scan_register_inject_run_and_destroy(tmp_path: Path):
    source = tmp_path / "components.py"
    source.write_text(
        """
from w_agent import AgentComponent, BaseAgent, PostConstruct, PreDestroy, ServiceComponent

@ServiceComponent
class GreetingService:
    initialized = False
    destroyed = False

    @PostConstruct
    async def initialize(self):
        type(self).initialized = True

    @PreDestroy
    async def destroy(self):
        type(self).destroyed = True

    def greet(self, name):
        return f\"Hello, {name}!\"

@AgentComponent(name=\"demo_agent\")
class DemoAgent(BaseAgent):
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service

    async def arun(self, prompt):
        return self.greeting_service.greet(prompt)
""",
        encoding="utf-8",
    )

    factory = BeanFactory()
    assert set(factory.scan_and_register(tmp_path)) == {"greetingservice", "demo_agent"}
    await factory.initialize_singletons()

    agent = await factory.get_bean("demo_agent")
    service = await factory.get_bean("greetingservice")
    assert service.initialized
    assert await agent.arun("World") == "Hello, World!"

    await factory.destroy_singletons()
    assert service.destroyed


async def test_scanner_async_api(tmp_path: Path):
    from w_agent import ParallelASTScanner

    (tmp_path / "component.py").write_text(
        "from w_agent import ServiceComponent\n@ServiceComponent\nclass Service: pass\n",
        encoding="utf-8",
    )
    result = await ParallelASTScanner(scan_paths=[tmp_path]).scan()
    assert [component.name for component in result.components] == ["service"]
