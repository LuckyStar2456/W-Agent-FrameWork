# W-Agent 使用指南

[English](./guide.en.md) | 简体中文

## 1. 先确认能力状态

当前 PyPI 版本为 1.5.2。IOC、AOP、配置、生命周期、弹性、观测和技能沙箱为 `Implemented`；下一代插件内核、模型协议、路由、ReAct、Workflow、Docker 沙箱、工程装配编码和 TUI 为 `Planned`。

本指南中的“当前用法”可以在 1.x 使用；“计划用法”用于约束后续实现，不是当前可执行 API。

## 2. 安装当前版本

```bash
pip install wagent-framework
```

可选能力：

```bash
pip install "wagent-framework[fastapi]"
pip install "wagent-framework[langchain]"
pip install "wagent-framework[opentelemetry]"
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

## 8. 计划中的模型探测

状态：`Planned`。

```text
wagent probe https://example.com/v1 --mode safe
wagent probe https://example.com/v1 --mode active
wagent probe https://example.com/v1 --mode capability
```

- `safe`：网络、鉴权和元数据，不主动产生模型费用。
- `active`：发送最小文本请求，需要用户确认。
- `capability`：探测流式、工具、结构化输出和多模态，需要用户确认。

## 9. 计划中的沙箱选择

状态：`Planned`。

编码 Agent 默认使用 Docker/OCI。开发者可以明确启用 `UnsafeLocalSandbox` 在宿主机执行，但 CLI/TUI 必须显示风险，而且装配编码不能替用户开启该授权。

## 10. 计划中的工程装配分享

状态：`Planned`。

```text
wagent composition export --name my-coding-stack --version 1.2.0
wagent composition import <composition-code>
```

导入先显示装配名称、版本、核心版本要求、插件依赖、权限和沙箱策略。只有用户确认后才能安装缺失依赖或加载插件。编码不包含密钥。

## 11. 计划中的 TUI

状态：`Planned`。

```text
wagent tui
```

TUI 将支持配置校验、模型探测、插件管理、Profile 选择、对话、Workflow 状态、Checkpoint 恢复、沙箱授权和事件查看。它使用公开 Python API，不依赖后台托管服务。

## 12. 下一步

- 架构与扩展点：[架构设计](./architecture.md)
- 实现顺序：[路线图](./roadmap.md)
- 插件作者：[开发者指南](./developer.md)
- 从 1.x 迁移：[迁移指南](./migration-1x.md)
