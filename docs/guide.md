# W-Agent 使用指南

[English](./guide.en.md) | 简体中文

## 1. 先确认能力状态

当前 PyPI 稳定版为 1.5.2，最新 Alpha 为 `2.0.0a3`；main 在该发布之后继续加入 Workflow Checkpoint 恢复、离线装配依赖计划、通用插件确认生命周期、Responses/vLLM 模型适配、验证前缀的文本流恢复和调用前 Token 估算。当前源码已实现插件微内核、模型与工具基础、单 Agent ReAct、Token/费用预算、本地 Session 与 Workflow、Agent/Workflow 适配、客服/编码模板、Docker/显式授权本地 Sandbox、工程装配编码/版本库，以及实验性 CLI/TUI/评测。并行/嵌套 Workflow、在线插件来源目录与包安装仍为 `Planned`。

1.x 示例对应当前 PyPI 版本；Phase 2A 示例对应仓库源码并要求 Python 3.11+。“计划用法”用于约束后续实现，不是当前可执行 API。

## 2. 安装当前版本

```bash
pip install wagent-framework
```

安装已发布 Alpha：

```bash
pip install --pre wagent-framework==2.0.0a3
```

可选能力：

```bash
pip install "wagent-framework[fastapi]"
pip install "wagent-framework[langchain]"
pip install "wagent-framework[opentelemetry]"
pip install "wagent-framework[models]"
pip install "wagent-framework[wasm]"
```

当前 1.x 元数据支持 Python 3.9+。下一代运行时目标为 Python 3.11+。

## 3. 当前 1.x Agent

状态：`Implemented`。

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

`BaseAgent` 当前只定义 `arun(prompt)`，不提供模型接入、工具循环或持久化 Session。需要复用旧 Agent 时，可通过 `LegacyAgentAdapter(old_agent).workflow_node("legacy")` 接入新 Workflow；该桥只传递文本和最终结果。

## 4. 当前配置管理

状态：`Implemented`。

```python
from w_agent import DynamicConfigManager

config = DynamicConfigManager()
config.set("agent.timeout", 30)
timeout = config.get("agent.timeout")
```

对象属性绑定：

```python
class Settings:
    timeout = 0


settings = Settings()
config.bind("agent.timeout", settings, "timeout")
```

## 5. 当前事件总线

状态：`Implemented`。

```python
from w_agent import Event, EventBus

bus = EventBus()


@bus.on("job.completed")
async def on_completed(event: Event) -> None:
    print(event.payload)


await bus.emit(Event("job.completed", {"id": "job-1"}))
```

1.x EventBus 不是下一代的类型化运行事件与 Pipeline API；迁移时将通过适配器衔接。

## 6. 当前技能沙箱

状态：`Implemented`。

Wasm 与 nsjail 后端在真实隔离不可用时失败关闭。Wasm SDK 当前不在 Windows 原生环境安装；Windows 用户可使用 WSL2。下一代 `DockerSandboxProvider` 已实现，但需要本机 Docker CLI/Daemon 与可用镜像；旧 Wasm/nsjail 类尚未接入新 Provider 协议。

不要把沙箱后端不可用后的普通子进程执行当作安全回退。

## 7. 计划中的开放式装配

状态：`Planned`。以下示例只表达目标体验：

```python
from w_agent import Application, OpenAIProvider, ReactAgentLoop

app = Application()
app.register(OpenAIProvider(name="primary", endpoint="..."))
app.register(ReactAgentLoop(name="react"))

result = await app.agent("coding").run("修复失败的测试")
```

同一装配也可以由装饰器、YAML 或 Python entry point 提供，最终进入同一个注册表。

## 8. 当前模型协议与探测 API

状态：Python API、OpenAI-compatible Provider、通用 HTTP 映射层、OpenAI Responses/vLLM 专用适配、厂商模板、收集式/逐事件透传执行器、显式文本前缀流恢复、显式注册安全探测服务，以及 CLI/TUI 无凭据 L1 和配置化 Provider 探测入口为 `Implemented`/`Experimental`；Provider 原生游标续传为 `Planned`。

自定义 Provider 实现 `list_models()`、`resolve()` 和 `stream()` 后可注册到 `ModelRegistry`。路由和安全端点嗅探使用公开 API：

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

主动 Provider 探测可能产生费用，必须为单次调用明确授权：

```python
from w_agent import ModelProviderProbe, ProbeMode

result = await ModelProviderProbe().probe(
    "local",
    provider,
    mode=ProbeMode.ACTIVE,
    allow_active=True,
)
```

Anthropic、Gemini、Ollama、Qwen-native、DeepSeek、GLM、Qwen-compatible 和 Turbo 模板可以通过 `builtin_provider_template_registry()` 装配。Qwen 同时支持原生 DashScope 与兼容入口；Turbo 模板指 Turbo AI/SIAM.AI，必须提供部署地址。详见 [HTTP Provider 与厂商模板](./provider-templates.md)。

执行路由决定时使用独立 `ModelExecutor`。默认只调用一次；只有显式提高 `InvocationPolicy.max_attempts_per_route` 或 `max_routes` 才会重试或切换备用路由。`invoke()` 返回完整收集结果；`stream()` 实时输出标准事件，并在首个事件对调用者可见后禁止重试或故障转移：

```python
execution = executor.stream(request)
async for event in execution:
    print(event)

assert execution.response is not None
```

需要注册后立即执行无生成费用的安全探测时，使用 `ModelRegistrationProbeService.register()`；直接 `ModelRegistry.register()` 始终不发起网络请求。详见[模型、路由与接口探测](./model-routing.md#调用重试与故障转移)。

当前 CLI 可执行不带凭据和请求体的 L1 探测：

```text
wagent probe https://example.com/v1
```

配置化 Provider 探测使用同一严格配置：

```text
wagent provider-probe --config .wagent/config.json --mode safe
wagent provider-probe --config .wagent/config.json --mode active --confirm-active-probe
```

`safe` 调用 Provider 的目录协议且不生成内容；某些兼容 Provider 使用静态目录，因此安全成功不一定证明远程链路可用。`active` 发送最多 8 Token 的最小请求，验证生成和流终止协议，可能计费且必须逐次确认。`capability` 当前在完成相同主动探测后只报告 L6/L7 声明，并明确标记没有厂商专用主动验证器。

## 9. 当前工具执行 API

状态：Python 函数模板、作用域注册、参数校验、权限/逐调用审批、超时、取消与审计为 `Implemented`。

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

默认策略只自动执行无须批准的调用。写入、破坏性与外部副作用必须由本地应用为具体调用 ID 提供批准。详见[工具注册、策略与执行](./tools.md)。

同一运行时还提供 `http_tool()`、无 Shell 的 `command_tool()` 和 `mcp_tool()`。HTTP 默认需要 `network.http`，命令需要 `process.execute`，MCP 需要 `mcp.call`，三者默认均视为外部副作用并要求逐调用审批。命令适配器不是沙箱。

## 10. 当前单 Agent ReAct Loop

状态：公开 Run/Loop 协议、有界 ReAct/tool loop 和进程内事件流为 `Implemented`。

```python
from w_agent import AgentDefinition, ReactAgentLoop, RunContext

loop = ReactAgentLoop(model_executor, tools, tool_executor)
result = await loop.run(AgentDefinition("assistant"), run_context)
```

Loop 自动把当前 Scope 的工具 Definition 交给模型，执行工具并把标准结果回送下一轮模型。`max_steps` 和 `max_tool_calls` 限制运行；需要审批的工具返回 `StopReason.NEEDS_APPROVAL`、待处理调用和 Checkpoint，不会自动执行。配置 `JsonlRunStore` 后可在新进程中通过 `resume()` 从审批点继续，不重复之前的模型调用；不确定的副作用状态拒绝自动重放。详见[Agent Runtime 与 ReAct Loop](./agents.md)。

## 11. 当前本地 Workflow

状态：DAG、状态图、Python 入口和节点边界恢复为 `Implemented`。

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

生产式本地恢复使用 `JsonlWorkflowStore`。节点返回 `WorkflowNodeResult(pause=True)` 时会保存 Checkpoint；新进程使用相同名称、版本和类型的定义调用 `resume()`。恢复只发生在节点边界，节点执行中断后不会自动重复可能产生副作用的节点。详见[Workflow 与节点恢复](./workflows.md)。

## 12. 当前沙箱选择

状态：统一 Provider、Docker/OCI 和显式授权本地执行为 `Implemented`。

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

Docker 默认断网并限制资源。需要宿主执行时，必须先调用 `UnsafeLocalAuthorization.grant(..., acknowledge_host_access=True)`，再构造 `UnsafeLocalSandboxProvider`，并显式把 Spec 设为 `SandboxNetwork.BRIDGE` 与读写工作区；Docker 失败不会自动回退到本地模式。详见[沙箱与本地执行](./sandbox.md)。

## 13. 当前工程装配分享

状态：编码、离线安全预览、保存、版本与别名管理为 `Implemented`；当前 main 的离线依赖计划与通用插件确认操作为 `Experimental`；在线来源目录和包安装仍为 `Planned`。

```text
wagent composition export manifest.json
wagent composition inspect <composition-code>
wagent composition plan <composition-code> --inventory plugin-inventory.json --json
wagent composition save <composition-code> --alias stable
```

预览显示装配名称、版本、核心版本要求、插件依赖、权限和沙箱策略，并且不访问网络、不导入插件、不执行代码。编码不包含密钥。`composition plan` 通过显式候选清单检查环境和插件约束，并输出逐项动作；它不查询网络、不安装包，也不授予插件加载权。随后可独立使用 `plugin inspect` / `plugin validate-load --confirm-plugin-code` 或 TUI Plugins 页审查和加载用户选择的 YAML 引用。规划结果自动转为安装/加载引用仍未实现。

## 14. 当前 TUI 基础

状态：可启动的本地 Textual 基础为 `Experimental`。

```text
wagent tui
```

TUI 当前覆盖模板、无凭据/配置化 Provider 探测、离线装配检查/依赖计划、通用插件预览/确认加载/卸载、本地 Session 生命周期、配置化文本 Agent 运行、Agent/Workflow Checkpoint 脱敏列表、工具批准/精确恢复、脱敏实时事件和本地评测。它使用公开 Python API，不依赖后台托管服务；Workflow 恢复、依赖计划和通用插件页属于 main 的未发布能力。

## 15. 当前本地评测

状态：API、CLI 与 TUI 为 `Experimental`。

```text
wagent evaluate cases.json --confirm-model-call --report report.json
```

用例集是严格 JSON。CLI/TUI 顺序运行配置化 Agent，默认使用一次性状态，并显示输入/输出 Token、计量完整性、延迟、错误和工具结果。TUI 需要输入 `EVALUATE`，不会保存授权。报告默认排除 Prompt 与模型输出。详见[本地测试、模型回放与评测](./testing-evaluation.md)。

## 16. 下一步

- 架构与扩展点：[架构设计](./architecture.md)
- 实现顺序：[路线图](./roadmap.md)
- 插件作者：[开发者指南](./developer.md)
- Workflow 开发：[Workflow 与节点恢复](./workflows.md)
- 从 1.x 迁移：[迁移指南](./migration-1x.md)
