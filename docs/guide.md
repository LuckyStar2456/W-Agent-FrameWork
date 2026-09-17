# W-Agent 使用指南

[English](./guide.en.md) | 简体中文

## 1. 先确认能力状态

当前 PyPI 稳定版为 1.5.2；仓库 `2.0.0a1` 已实现插件微内核、模型基础、通用 HTTP Provider、首批厂商模板、收集/透传执行、Python 探测 API、工具执行基础、单 Agent ReAct Loop，以及本地 DAG/状态图/Python Workflow。完整 Session、并行/嵌套 Workflow、Docker 沙箱、工程装配编码和 TUI 仍为 `Planned`。

1.x 示例对应当前 PyPI 版本；Phase 2A 示例对应仓库源码并要求 Python 3.11+。“计划用法”用于约束后续实现，不是当前可执行 API。

## 2. 安装当前版本

```bash
pip install wagent-framework
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

`BaseAgent` 当前只定义 `arun(prompt)`，不提供模型接入、工具循环或持久化 Session。

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

Wasm 与 nsjail 后端在真实隔离不可用时失败关闭。Wasm SDK 当前不在 Windows 原生环境安装；Windows 用户可使用 WSL2。编码 Agent 计划使用的 Docker/OCI Sandbox 尚未实现。

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

状态：Python API、OpenAI-compatible Provider、通用 HTTP 映射层、首批厂商模板、收集式/逐事件透传执行器和显式注册安全探测服务为 `Implemented`；CLI/TUI 入口、OpenAI Responses、vLLM 差异适配与跨流恢复为 `Planned`。

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

以下 CLI 体验仍为 `Planned`：

```text
wagent probe https://example.com/v1 --mode safe
wagent probe https://example.com/v1 --mode active
wagent probe https://example.com/v1 --mode capability
```

- `safe`：网络、Provider 访问和模型目录，不主动产生模型生成费用。
- `active`：发送最小文本请求，需要用户确认。
- `capability`：当前 Python API 只报告 L6/L7 声明并标记未主动验证；主动验证器为 `Planned`。

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

## 12. 计划中的沙箱选择

状态：`Planned`。

编码 Agent 默认使用 Docker/OCI。开发者可以明确启用 `UnsafeLocalSandbox` 在宿主机执行，但 CLI/TUI 必须显示风险，而且装配编码不能替用户开启该授权。

## 13. 计划中的工程装配分享

状态：`Planned`。

```text
wagent composition export --name my-coding-stack --version 1.2.0
wagent composition import <composition-code>
```

导入先显示装配名称、版本、核心版本要求、插件依赖、权限和沙箱策略。只有用户确认后才能安装缺失依赖或加载插件。编码不包含密钥。

## 14. 计划中的 TUI

状态：`Planned`。

```text
wagent tui
```

TUI 将支持配置校验、模型探测、插件管理、Profile 选择、对话、Workflow 状态、Checkpoint 恢复、沙箱授权和事件查看。它使用公开 Python API，不依赖后台托管服务。

## 15. 下一步

- 架构与扩展点：[架构设计](./architecture.md)
- 实现顺序：[路线图](./roadmap.md)
- 插件作者：[开发者指南](./developer.md)
- Workflow 开发：[Workflow 与节点恢复](./workflows.md)
- 从 1.x 迁移：[迁移指南](./migration-1x.md)
