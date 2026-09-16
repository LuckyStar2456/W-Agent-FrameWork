# W-Agent user guide

English | [简体中文](./guide.md)

## 1. Check capability status first

The current stable PyPI release is 1.5.2; repository version `2.0.0a1` implements the plugin microkernel and Phase 2A model foundation. IOC, AOP, configuration, lifecycle, resilience, observability, skill sandboxes, model protocols, routing policies, and Python probe APIs are `Implemented`. Concrete first-party model adapters, the ReAct loop, workflows, Docker sandbox, composition codes, and TUI remain `Planned`.

The 1.x examples match the current PyPI release. Phase 2A examples use repository source and require Python 3.11+. “Planned usage” defines the target experience and is not an executable API today.

## 2. Install the current release

```bash
pip install wagent-framework
```

Optional capabilities:

```bash
pip install "wagent-framework[fastapi]"
pip install "wagent-framework[langchain]"
pip install "wagent-framework[opentelemetry]"
pip install "wagent-framework[models]"
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

## 8. Current model and probe APIs

Status: the Python API, OpenAI-compatible provider, generic HTTP mapping layer, and initial vendor templates are `Implemented`; CLI/TUI entry points and dedicated OpenAI Responses/vLLM differences are `Planned`.

After a custom provider implements `list_models()`, `resolve()`, and `stream()`, it can register with `ModelRegistry`. Routing and safe endpoint sniffing use public APIs:

```python
from w_agent import (
    EndpointProbe,
    ModelRegistry,
    ModelRouter,
    OpenAICompatibleProvider,
    YamlRoutingPolicy,
)

models = ModelRegistry()
provider = OpenAICompatibleProvider(
    name="local",
    base_url="http://127.0.0.1:11434/v1",
    default_model="my-model",
)
models.register("local", provider, version="1.0.0")

policy = YamlRoutingPolicy.from_yaml("preferred_providers: [local]")
decision = await ModelRouter(models, policy).route(request)
reachability = await EndpointProbe().probe("https://example.com/v1")
```

Active provider probes may incur cost and require per-call authorization:

```python
from w_agent import ModelProviderProbe, ProbeMode

result = await ModelProviderProbe().probe(
    "local",
    provider,
    mode=ProbeMode.ACTIVE,
    allow_active=True,
)
```

Anthropic, Gemini, Ollama, Qwen-native, DeepSeek, GLM, Qwen-compatible, and Turbo templates can be assembled through `builtin_provider_template_registry()`. Qwen has both native DashScope and compatible entry points. The Turbo template means Turbo AI/SIAM.AI and requires a deployment URL. See [HTTP providers and vendor templates](./provider-templates.en.md).

The following CLI experience remains `Planned`:

```text
wagent probe https://example.com/v1 --mode safe
wagent probe https://example.com/v1 --mode active
wagent probe https://example.com/v1 --mode capability
```

- `safe`: network, provider access, and model-catalog checks without intentional generation cost.
- `active`: sends a minimal text request and requires confirmation.
- `capability`: the current Python API reports L6/L7 declarations as not actively verified; active verifiers are `Planned`.

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
