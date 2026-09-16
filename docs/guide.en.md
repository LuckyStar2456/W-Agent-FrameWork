# W-Agent user guide

English | [简体中文](./guide.md)

## 1. Check capability status first

The current stable PyPI release is 1.5.2; repository version `2.0.0a1` implements the plugin microkernel. IOC, AOP, configuration, lifecycle, resilience, observability, and skill sandboxes remain `Implemented`. The model protocol, routing, ReAct loop, workflows, Docker sandbox, composition codes, and TUI remain `Planned`.

“Current usage” examples work with 1.x. “Planned usage” defines the target experience and is not an executable API today.

## 2. Install the current release

```bash
pip install wagent-framework
```

Optional capabilities:

```bash
pip install "wagent-framework[fastapi]"
pip install "wagent-framework[langchain]"
pip install "wagent-framework[opentelemetry]"
pip install "wagent-framework[wasm]"
```

Current 1.x metadata supports Python 3.9+. The next-generation runtime targets Python 3.11+.

## 3. Current 1.x agent

Status: `Implemented`.

```python
import asyncio

from w_agent import AgentComponent, BaseAgent, BeanFactory


@AgentComponent(name="echo_agent")
class EchoAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return prompt


async def main() -> None:
    factory = BeanFactory()
    factory.register_bean("echo_agent", EchoAgent())
    agent = await factory.get_bean("echo_agent")
    print(await agent.arun("hello"))


asyncio.run(main())
```

`BaseAgent` currently defines only `arun(prompt)` and does not provide model integration, a tool loop, or durable sessions.

## 4. Current configuration management

Status: `Implemented`.

```python
from w_agent import DynamicConfigManager

config = DynamicConfigManager()
config.set("agent.timeout", 30)
timeout = config.get("agent.timeout")
```

Property binding:

```python
class Settings:
    timeout = 0


settings = Settings()
config.bind("agent.timeout", settings, "timeout")
```

## 5. Current event bus

Status: `Implemented`.

```python
from w_agent import Event, EventBus

bus = EventBus()


@bus.on("job.completed")
async def on_completed(event: Event) -> None:
    print(event.payload)


await bus.emit(Event("job.completed", {"id": "job-1"}))
```

The 1.x event bus is not the planned typed run-event and pipeline API. A compatibility adapter will bridge it during migration.

## 6. Current skill sandboxes

Status: `Implemented`.

Wasm and nsjail backends fail closed when real isolation is unavailable. The Wasm SDK is not installed on native Windows; Windows users can use WSL2. The planned Docker/OCI sandbox for coding agents is not implemented.

Never treat ordinary subprocess execution as a safe fallback for an unavailable sandbox backend.

## 7. Planned open composition

Status: `Planned`. This example shows only the target experience:

```python
from w_agent import Application, OpenAIProvider, ReactAgentLoop

app = Application()
app.register(OpenAIProvider(name="primary", endpoint="..."))
app.register(ReactAgentLoop(name="react"))

result = await app.agent("coding").run("fix the failing test")
```

The same composition may come from decorators, YAML, or Python entry points; every path enters the same registry.

## 8. Planned endpoint probing

Status: `Planned`.

```text
wagent probe https://example.com/v1 --mode safe
wagent probe https://example.com/v1 --mode active
wagent probe https://example.com/v1 --mode capability
```

- `safe`: network, authentication, and metadata checks without intentional model cost.
- `active`: sends a minimal text request and requires confirmation.
- `capability`: probes streaming, tools, structured output, and multimodality and requires confirmation.

## 9. Planned sandbox selection

Status: `Planned`.

Coding agents use Docker/OCI by default. A developer may explicitly enable `UnsafeLocalSandbox` for host execution, but the CLI and TUI must show the risk, and a composition code can never enable that authority on the user's behalf.

## 10. Planned portable project composition

Status: `Planned`.

```text
wagent composition export --name my-coding-stack --version 1.2.0
wagent composition import <composition-code>
```

Import first shows the composition name, version, core requirement, plugin dependencies, permissions, and sandbox policy. Missing dependencies may be installed and plugins loaded only after user confirmation. Codes contain no secrets.

## 11. Planned TUI

Status: `Planned`.

```text
wagent tui
```

The TUI will cover configuration validation, model probing, plugin management, profile selection, conversations, workflow state, checkpoint recovery, sandbox authorization, and event inspection. It uses public Python APIs and needs no hosted backend.

## 12. Next steps

- Architecture and extension points: [Architecture](./architecture.en.md)
- Delivery order: [Roadmap](./roadmap.en.md)
- Plugin authors: [Developer guide](./developer.en.md)
- Migrating from 1.x: [Migration guide](./migration-1x.en.md)
