# W-Agent

[English](./README_EN.md) | 简体中文

W-Agent 是一个面向本地开发者的 Python 开源 Agent 开发框架。它的目标不是提供托管平台或固定 Harness，而是提供稳定、可扩展的协议与可自由装配的模块，让开发者能够替换模型、路由、Agent Loop、Workflow、工具、状态、沙箱和界面实现。

当前稳定发布版本是 `1.5.2`；仓库主线已进入 `2.0.0a1` 开发阶段。1.x 工程底座继续保留，Phase 1 微内核和 Phase 2A 模型基础已经实现，其余下一代能力按路线图分阶段交付。文档使用明确状态标记，避免把规划能力描述为现有能力。

## 状态标记

| 标记 | 含义 |
|---|---|
| `Implemented` | 源码已经存在，并有相应测试或可执行入口 |
| `Planned` | 已决定实现，已进入明确路线图 |
| `Reserved` | 协议或扩展点会保留，但尚未承诺实现版本 |
| `Experimental` | 可以试用，但接口与行为可能变化 |
| `Deprecated` | 仅为迁移保留，不再扩展 |

## 项目定位

W-Agent 遵循以下原则：

- 核心协议稳定且可扩展，具体策略全部可替换。
- 内置实现只使用公开扩展接口，不享有私有能力。
- 显式 Python 装配、装饰器、配置文件和 Python entry point 最终进入同一个注册表。
- Agent Loop 与 Workflow 互通但不强行合并。
- 本地开发优先，不内置租户、计费或托管控制面。
- 默认执行不可信代码时使用沙箱；宿主机执行必须由用户明确授权。
- 已实现、计划实现和仅保留设计的能力必须在文档中区分。

## 当前能力

以下能力在 1.5.2 源码中为 `Implemented`：

- `BaseAgent.arun()` 基础抽象。
- IOC 容器、组件扫描、生命周期与依赖注入。
- AOP、重试、断路器、超时和舱壁隔离。
- 动态配置、事件总线、健康检查、日志、指标和链路追踪。
- Wasm 与 nsjail 技能沙箱，后端不可用时失败关闭。
- Skill 加载、签名校验、MCP JWT 认证、Redis 分布式锁。
- LangChain 工具适配、FastAPI 示例集成和测试辅助设施。

以下 Phase 1 能力在当前 `2.0.0a1` 源码中为 `Implemented`：

- `PluginSpec`、装饰器、YAML 引用与 Python entry point 发现。
- 统一、版本感知、分作用域的能力注册表与不可变快照。
- 插件依赖解析、生命周期、失败回滚、级联卸载和可撤销注册。
- `Application → Workspace → Session → Agent → Run → Step` 作用域。
- `publish`、`first`、`serial` 和 `pipeline` 事件模式。

以下 Phase 2A 能力在当前源码中也为 `Implemented`：

- Provider 中立的消息、能力、请求、响应和严格流事件协议。
- 统一 `ModelRegistry`、可替换 `ModelProvider` 和协作式取消令牌。
- 可解释的 Python 加权路由与安全 YAML 路由规则。
- L1 端点可达性嗅探、L2/L3 Provider 检查、显式授权的 L4/L5 主动探测、缓存和周期调度器。
- 可替换传输的 OpenAI-compatible Chat Completions Provider，适用于声明兼容接口的本地或远程服务。
- 可插拔的通用 HTTP 请求映射层与 JSON/SSE/NDJSON 传输。
- Anthropic、Gemini、Ollama、Qwen 原生模板，以及 DeepSeek、GLM、Qwen-compatible、Turbo AI/SIAM.AI 模板注册表。

当前 `BaseAgent` 仍是简单抽象；专用 OpenAI Responses 与 vLLM 差异适配、自动故障转移、标准 ReAct Loop、Workflow、Checkpoint、Docker 编码沙箱、工程装配编码和 TUI 仍为 `Planned`，不能当作现成功能使用。厂商模板经过模拟传输测试，但不代表所有远程型号已经在线验证。

## 下一代模块图

```text
应用与模板       客服模板 / 编码模板 / 用户自定义装配
运行时           Agent Loop / Workflow / Session / Checkpoint
能力             Models / Router / Tools / RAG / Memory / Sandbox
微内核           Plugin / Registry / Lifecycle / Scope / Events
基础设施         Storage / Telemetry / CLI / TUI / Evaluation
```

下一代 API 将直接从 `w_agent` 导出，不引入 `w_agent.v2` 命名空间。1.x API 只通过最小兼容层继续工作。

## 安装现有版本

```bash
pip install wagent-framework
```

可选依赖：

```bash
pip install "wagent-framework[fastapi,langchain,opentelemetry]"
pip install "wagent-framework[models]"
pip install "wagent-framework[wasm]"
```

PyPI 1.x 支持 Python 3.9+；当前 `2.0.0a1` 源码要求 Python 3.11+。

## 1.x 最小示例

```python
import asyncio

from w_agent import AgentComponent, BaseAgent, BeanFactory


@AgentComponent(name="hello_agent")
class HelloAgent(BaseAgent):
    async def arun(self, prompt: str) -> str:
        return f"Hello, {prompt}!"


async def main() -> None:
    factory = BeanFactory()
    factory.register_bean("hello_agent", HelloAgent())
    agent = await factory.get_bean("hello_agent")
    print(await agent.arun("W-Agent"))


asyncio.run(main())
```

这段代码是 1.x 兼容用法，不代表下一代 Agent Runtime 已实现。

## 计划中的本地开发体验

以下命令为 `Planned`，当前版本尚未全部提供：

```text
wagent init
wagent config validate
wagent plugins list
wagent profile resolve
wagent probe
wagent doctor
wagent run
wagent tui
wagent composition export
wagent composition import
```

CLI 与 TUI 将只调用公开 Python API。TUI 计划覆盖模型配置与探测、插件管理、Profile 选择、交互运行、Workflow 状态、Checkpoint 恢复、沙箱确认和事件查看。

## 工程装配分享

`Planned`：开发者可以给自己的框架装配命名并进行版本化，然后导出一段可复制的编码。其他开发者导入后先预览、校验和解析依赖，再明确确认安装或加载。

装配编码只携带可移植清单，不携带密钥，不默认打包任意源码，也不会在导入时自动执行不可信插件。详细设计见[工程装配分享](./docs/project-sharing.md)。

## 文档

- [文档索引](./docs/README.md)
- [架构设计](./docs/architecture.md)
- [路线图与能力状态](./docs/roadmap.md)
- [使用指南](./docs/guide.md)
- [开发者指南](./docs/developer.md)
- [API 状态与规划](./docs/api.md)
- [插件系统](./docs/plugin-system.md)
- [模型、路由与接口探测](./docs/model-routing.md)
- [HTTP Provider 与厂商模板](./docs/provider-templates.md)
- [沙箱与本地执行](./docs/sandbox.md)
- [CLI 与 TUI](./docs/tui.md)
- [1.x 迁移](./docs/migration-1x.md)

## 明确不做

- 不提供 W-Agent 托管平台或云控制面。
- 首版不内置租户、组织、计费和 SaaS 管理系统。
- 不把某一种 ReAct、Workflow 或模型协议写死为唯一实现。
- 不在未经确认的情况下自动安装、升级或执行第三方插件。

## 许可证

本项目采用 [MIT 许可证](./LICENSE)。
