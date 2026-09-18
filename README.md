# W-Agent

[English](./README_EN.md) | 简体中文

W-Agent 是一个面向本地开发者的 Python 开源 Agent 开发框架。它的目标不是提供托管平台或固定 Harness，而是提供稳定、可扩展的协议与可自由装配的模块，让开发者能够替换模型、路由、Agent Loop、Workflow、工具、状态、沙箱和界面实现。

当前稳定发布版本是 `1.5.2`，最新 Alpha 为 `2.0.0a3`；仓库 main 已继续开发未发布的 post-`2.0.0a3` 能力。1.x 工程底座继续保留，微内核、模型、工具、单 Agent 与本地 Workflow 基础已经实现，其余下一代能力按路线图分阶段交付。文档使用明确状态标记，避免把规划能力或未发布源码描述为已发布能力。

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

以下 Phase 1 能力在当前 main 源码中为 `Implemented`：

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
- 严格配置化 Provider 的独立无副作用装配，以及 CLI/TUI 安全目录检查与显式授权主动生成探测。
- 可替换传输的 OpenAI-compatible Chat Completions Provider，适用于声明兼容接口的本地或远程服务。
- 可插拔的通用 HTTP 请求映射层与 JSON/SSE/NDJSON 传输。
- Anthropic、Gemini、Ollama、Qwen 原生模板，以及 DeepSeek、GLM、Qwen-compatible、Turbo AI/SIAM.AI 模板注册表。
- 同时支持完整收集和逐事件透传的 `ModelExecutor`；默认单次调用，可显式启用有界重试/故障转移，并记录不含 Prompt 的逐尝试 Token/失败审计。
- 注册即安全探测的 `ModelRegistrationProbeService` 与外部路由健康桥接；直接调用 `ModelRegistry.register()` 仍保持无副作用。
- 工具 Definition/Binding/Registry 分层、Python/HTTP/无 Shell 命令模板、MCP 绑定与 2026-07-28 stdio/Streamable HTTP 客户端、参数校验、权限/逐调用审批、超时/取消和 Prompt-free 审计。
- 可替换 `AgentLoop` 协议与有界单 Agent `ReactAgentLoop`，覆盖模型→工具→结果→模型闭环、严格 Token 预算、JSONL RunEvent/尝试账本记录和审批断点恢复。
- 应用提供的版本化价格表、普通/缓存输入与输出费用计量、失败关闭的 Run 费用预算，以及 Session/Checkpoint/评测费用可见性。
- 统一 `WorkflowRegistry`、可替换 `WorkflowEngineProtocol` 与 `LocalWorkflowEngine`，支持静态 DAG、状态图、Python 入口、节点事件、取消，以及内存/JSONL 节点边界暂停恢复。
- 统一 `SandboxProvider`/`SandboxRegistry`、Docker/OCI 生命周期后端、显式运行时授权的 `UnsafeLocalSandboxProvider`，以及受工具策略保护的 `sandbox_command_tool()`。
- Agent/Workflow 双向适配器，以及可完全覆盖的客服/RAG 与编码 Agent 模板。
- `CompositionManifest` 的确定性编码、安全预览，以及冲突安全的本地版本和别名管理。
- 本地 Session 创建/列表/归档、JSON 持久化、跨 Run 文本上下文与审批恢复协调。
- 严格本地 JSON 装配的文本 Agent CLI/TUI 运行入口，使用环境变量凭据引用、逐次调用确认、可见 Token/费用预算与计量。
- 确定性脚本化 Model Provider、显式授权的 JSONL 录制/顺序回放，以及本地评测运行器与脱敏 JSON 报告。

当前 `BaseAgent` 仍是简单的 1.x 抽象；`LegacyAgentAdapter` 已能把它严格桥接为文本 Workflow 节点，新的 ReAct Runtime 独立提供。当前 main 已有可替换的离线装配依赖计划，以及独立 YAML 插件引用的安全预览、确认加载和 TUI 卸载；在线来源目录/包安装、专用 OpenAI Responses 与 vLLM 差异适配、模型跨流恢复、多模态/工具事件通用回放、并行或嵌套 Workflow 仍为 `Planned`，不能当作现成功能使用。Docker 后端已有模拟 CLI 生命周期测试，但不代表当前机器已安装或启动 Docker；厂商模板经过模拟传输测试，也不代表所有远程型号已经在线验证。

## 下一代模块图

```text
应用与模板       客服模板 / 编码模板 / 用户自定义装配
运行时           Agent Loop / Workflow / Session / Checkpoint
能力             Models / Router / Tools / RAG / Memory / Sandbox
微内核           Plugin / Registry / Lifecycle / Scope / Events
基础设施         Storage / Telemetry / CLI / TUI / Evaluation
```

下一代 API 直接从 `w_agent` 导出，不引入 `w_agent.v2` 命名空间。已实现的最小兼容层保留必要的 1.x Agent 复用路径。

## 安装现有版本

```bash
pip install wagent-framework
```

安装最新 Alpha：

```bash
pip install --pre wagent-framework==2.0.0a3
```

可选依赖：

```bash
pip install "wagent-framework[fastapi,langchain,opentelemetry]"
pip install "wagent-framework[models]"
pip install "wagent-framework[wasm]"
pip install "wagent-framework[tui]"
```

PyPI 1.x 支持 Python 3.9+；`2.0.0a3`、当前 main 源码与后续 2.x 版本要求 Python 3.11+。

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

这段代码只展示 1.x 兼容用法，不会自动接入新的 ReAct、模型或工具运行时。

## 本地开发体验

当前源码已提供：

```text
wagent init
wagent profile list
wagent probe <endpoint>
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent doctor
wagent tui
wagent composition export
wagent composition inspect|save|list
wagent session create|list|show|archive|unarchive
wagent run "hello" --confirm-model-call --json
wagent evaluate cases.json --confirm-model-call --report report.json
```

CLI 和 TUI 只调用公开 Python API。当前 CLI/TUI 基础标记为 `Experimental`：已覆盖初始化、模板列表、安全/主动端点探测、装配管理/离线预览与依赖计划、本地 Session 生命周期、需逐次确认的配置化 Agent 运行与 Token 汇总、Agent/Workflow Checkpoint 脱敏列表、Catalog 工具选择、独立代码加载确认、权限授予、精确 Call ID 审批恢复、精确版本 Workflow 恢复、通用插件无导入预览/确认加载/TUI 卸载、脱敏实时 RunEvent，以及 CLI/TUI 隐私安全本地评测。Workflow 恢复、离线依赖计划与通用插件操作属于 main 的未发布能力；插件包安装/升级仍为 `Planned`。

## 工程装配分享

`Implemented`：开发者可以给框架装配命名和版本化，导出为可复制编码，并在无网络、无导入、无执行的阶段完成校验和风险预览。本地 Store 支持多版本与别名且拒绝静默覆盖冲突内容。当前 main 还能通过可替换 Resolver 和显式候选清单生成环境/插件离线计划；计划不会自动安装包、生成加载引用或替用户确认代码执行。

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
- [工具注册、策略与执行](./docs/tools.md)
- [Agent Runtime 与 ReAct Loop](./docs/agents.md)
- [Session 生命周期与跨 Run 上下文](./docs/sessions.md)
- [本地配置化 Agent Runtime](./docs/local-runtime.md)
- [Workflow 与节点恢复](./docs/workflows.md)
- [沙箱与本地执行](./docs/sandbox.md)
- [CLI 与 TUI](./docs/tui.md)
- [本地测试、模型回放与评测](./docs/testing-evaluation.md)
- [1.x 迁移](./docs/migration-1x.md)

## 明确不做

- 不提供 W-Agent 托管平台或云控制面。
- 首版不内置租户、组织、计费和 SaaS 管理系统。
- 不把某一种 ReAct、Workflow 或模型协议写死为唯一实现。
- 不在未经确认的情况下自动安装、升级或执行第三方插件。

## 许可证

本项目采用 [MIT 许可证](./LICENSE)。
