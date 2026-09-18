# W-Agent user guide

English | [简体中文](./guide.md)

## 1. Check capability status first

The current stable PyPI release is 1.5.2 and the latest alpha is `2.0.0a3`; main subsequently adds workflow-checkpoint recovery, offline composition dependency planning, confirmed general-plugin lifecycle operations, Responses/vLLM model adapters, verified-prefix text-stream recovery, and pre-call token estimation. Current source implements the plugin microkernel, model/tool foundations, single-agent ReAct, token/cost budgets, local sessions and workflows, agent/workflow adapters, support/coding templates, Docker/explicitly authorized local sandboxes, composition encoding/version storage, and experimental CLI/TUI/evaluation. Parallel/nested workflows, online plugin source catalogs, and package installation remain `Planned`.

The 1.x examples match the current PyPI release. Phase 2A examples use repository source and require Python 3.11+. “Planned usage” defines the target experience and is not an executable API today.

## 2. Install the current release

```bash
pip install wagent-framework
```

Install the published alpha with:

```bash
pip install --pre wagent-framework==2.0.0a3
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

`BaseAgent` currently defines only `arun(prompt)` and does not provide model integration, a tool loop, or durable sessions. Reuse an old agent in a current workflow with `LegacyAgentAdapter(old_agent).workflow_node("legacy")`; this bridge carries text and a final result only.

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

Wasm and nsjail backends fail closed when real isolation is unavailable. The Wasm SDK is not installed on native Windows; Windows users can use WSL2. The next-generation `DockerSandboxProvider` is implemented but requires a local Docker CLI/daemon and usable image. Legacy Wasm/nsjail classes are not yet connected to the new provider contract.

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

Status: the Python API, OpenAI-compatible provider, generic HTTP mapping layer, dedicated OpenAI Responses/vLLM handling, vendor templates, collecting/event-pass-through executors, explicit text-prefix stream recovery, explicit register-and-safe-probe service, and credential-free L1 plus configured provider CLI/TUI probe entry points are `Implemented`/`Experimental`; provider-native cursor continuation remains `Planned`.

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

Use the separate `ModelExecutor` to execute a route decision. The default performs one call; retry or fallback happens only after explicitly raising `InvocationPolicy.max_attempts_per_route` or `max_routes`. `invoke()` returns a fully collected result; `stream()` yields standard events in real time and prohibits retry or failover after the first event becomes visible:

```python
execution = executor.stream(request)
async for event in execution:
    print(event)

assert execution.response is not None
```

For a non-generating safety probe immediately after registration, use `ModelRegistrationProbeService.register()`; direct `ModelRegistry.register()` never initiates network I/O. See [Models, routing, and endpoint probing](./model-routing.en.md#invocation-retry-and-failover).

The current CLI performs credential-free L1 probing without a request body:

```text
wagent probe https://example.com/v1
```

Configured provider probes use the same strict configuration:

```text
wagent provider-probe --config .wagent/config.json --mode safe
wagent provider-probe --config .wagent/config.json --mode active --confirm-active-probe
```

`safe` invokes the provider catalog contract without generating content. Some compatible providers use a static catalog, so a safe success does not necessarily prove the remote generation path. `active` sends a minimal request capped at 8 output tokens and verifies generation plus stream termination; it may incur cost and requires per-run confirmation. `capability` performs the same active check and then reports L6/L7 declarations while explicitly noting that no vendor-specific active verifier is installed.

## 9. Current tool-execution API

Status: the Python-function template, scoped registration, argument validation, permission/per-call approval, timeout, cancellation, and audit are `Implemented`.

```python
from w_agent import ToolCall, ToolExecutor, ToolRegistry, python_tool


def lookup(query: str) -> str:
    return f"result for {query}"


tools = ToolRegistry()
tools.register_binding(python_tool(lookup))
result = await ToolExecutor(tools).execute(
    ToolCall("lookup-1", "lookup", {"query": "W-Agent"})
)
```

The default policy automatically executes only calls that need no approval. Write, destructive, and external effects require the local application to approve the specific call ID. See [Tool registration, policy, and execution](./tools.en.md).

The same runtime also includes `http_tool()`, shell-free `command_tool()`, and `mcp_tool()`. HTTP requires `network.http`, commands require `process.execute`, and MCP requires `mcp.call` by default. All three default to external effects and per-call approval. The command adapter is not a sandbox.

## 10. Current single-agent ReAct loop

Status: public run/loop contracts, a bounded ReAct/tool loop, and an in-process event stream are `Implemented`.

```python
from w_agent import AgentDefinition, ReactAgentLoop, RunContext

loop = ReactAgentLoop(model_executor, tools, tool_executor)
result = await loop.run(AgentDefinition("assistant"), run_context)
```

The loop exposes tool definitions from the current scope to the model, executes calls, and sends normalized results into the next model turn. `max_steps` and `max_tool_calls` bound a run. A call requiring approval returns `StopReason.NEEDS_APPROVAL`, the pending call, and a checkpoint without executing it. With `JsonlRunStore`, a new process can call `resume()` from that boundary without repeating the earlier model request; uncertain side-effect state rejects automatic replay. See [Agent runtime and ReAct loop](./agents.en.md).

## 11. Current local workflows

Status: DAG, state-graph, and Python entry points plus node-boundary recovery are `Implemented`.

```python
from w_agent import (
    DagWorkflowDefinition,
    LocalWorkflowEngine,
    WorkflowContext,
    WorkflowNode,
)

workflow = DagWorkflowDefinition(
    "hello",
    (WorkflowNode("format", lambda context: f"hello {context.input}"),),
)
result = await LocalWorkflowEngine().start(
    workflow,
    WorkflowContext("workflow-1", input="W-Agent"),
)
```

Use `JsonlWorkflowStore` for durable local recovery. A node returning `WorkflowNodeResult(pause=True)` saves a checkpoint; a new process resumes with a definition of the same name, version, and kind. Recovery occurs only at node boundaries, and an interrupted node that may have produced effects is never repeated automatically. See [Workflows and node-boundary recovery](./workflows.en.md).

## 12. Current sandbox selection

Status: the unified provider, Docker/OCI, and explicitly authorized local execution are `Implemented`.

```python
from pathlib import Path

from w_agent import DockerSandboxProvider, SandboxCommand, SandboxSpec

provider = DockerSandboxProvider()
handle = await provider.open(
    SandboxSpec(Path.cwd(), image="python:3.11-slim")
)
try:
    result = await handle.execute(SandboxCommand(("python", "-V")))
finally:
    await handle.close()
```

Docker defaults to no network and bounded resources. Host execution first requires `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)`, constructing `UnsafeLocalSandboxProvider`, and explicitly selecting `SandboxNetwork.BRIDGE` plus read-write workspace access. Docker failure never falls back to local mode. See [Sandbox and local execution](./sandbox.en.md).

## 13. Current portable project compositions

Status: encoding, offline safety preview, storage, versions, and aliases are `Implemented`. Current main's offline dependency planning and general-plugin confirmation operations are `Experimental`; online source catalogs and package installation remain `Planned`.

```text
wagent composition export manifest.json
wagent composition inspect <composition-code>
wagent composition plan <composition-code> --inventory plugin-inventory.json --json
wagent composition save <composition-code> --alias stable
```

Preview shows the composition name, version, core requirement, plugin dependencies, permissions, and sandbox policy without network access, plugin imports, or code execution. Codes contain no secrets. `composition plan` checks environment and plugin constraints against an explicit candidate inventory and emits per-item actions. It never queries the network, installs a package, or grants plugin-load authority. Users may then separately review and load selected YAML references through `plugin inspect`, `plugin validate-load --confirm-plugin-code`, or the TUI Plugins screen. Automatic conversion of a plan into install/load references is not implemented.

## 14. Current TUI foundation

Status: the launchable local Textual foundation is `Experimental`.

```text
wagent tui
```

The TUI currently covers profiles, credential-free/configured provider probing, offline composition inspection/dependency planning, general-plugin preview/confirmed load/unload, local session lifecycle, configured text-agent runs, privacy-safe agent/workflow checkpoint listing, exact tool/workflow recovery, privacy-safe live events, and local evaluation. It uses public Python APIs and needs no hosted backend; workflow recovery, dependency planning, and general-plugin screens are unpublished main capabilities.

## 15. Current local evaluation

Status: the API, CLI, and TUI are `Experimental`.

```text
wagent evaluate cases.json --confirm-model-call --report report.json
```

Datasets use strict JSON. The CLI/TUI execute a configured agent sequentially, use disposable state by default, and expose input/output tokens, metering completeness, latency, errors, and tool outcomes. The TUI requires typing `EVALUATE` and never retains that authorization. Reports omit prompts and model outputs by default. See [Local testing, model replay, and evaluation](./testing-evaluation.en.md).

## 16. Next steps

- Architecture and extension points: [Architecture](./architecture.en.md)
- Delivery order: [Roadmap](./roadmap.en.md)
- Plugin authors: [Developer guide](./developer.en.md)
- Workflow development: [Workflows and node-boundary recovery](./workflows.en.md)
- Migrating from 1.x: [Migration guide](./migration-1x.en.md)
