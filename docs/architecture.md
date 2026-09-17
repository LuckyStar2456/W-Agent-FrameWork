# W-Agent 架构设计

[English](./architecture.en.md) | 简体中文

## 1. 定位

W-Agent 是面向本地开发者的开放式 Agent 框架，不是托管平台，也不是固定 Harness。框架提供模块组合所需的稳定协议、生命周期和默认模板，开发者拥有模型、路由、Agent Loop、Workflow、工具、状态、沙箱和界面的最终控制权。

稳定版 1.5.2 已实现 IOC、AOP、配置、生命周期、弹性、安全与可观测性底座。当前 `2.0.0a1` 源码已经实现 Phase 1 微内核和 Phase 2A 模型基础；本文其余部分同时描述已实现能力和 `Planned` 的后续架构，未标记 `Implemented` 的能力不得宣称已经提供。

## 2. 设计原则

1. **协议稳定，策略开放**：公共协议保持兼容，具体实现可以替换或扩展。
2. **默认实现无特权**：官方插件只使用第三方插件也能使用的接口。
3. **组合优于继承**：Agent 由能力装配形成，不要求继承庞大的框架基类。
4. **显式优于隐式**：依赖、作用域、版本、失败模式和副作用必须可见。
5. **异步优先**：模型流、工具、Workflow 和运行时使用异步协议，同步 API 仅作为边界便捷层。
6. **失败关闭**：沙箱、权限和依赖不可用时拒绝高风险操作，不静默降低安全等级。
7. **本地优先**：不引入租户、计费或云控制面概念；远程能力通过普通插件接入。
8. **状态诚实**：文档严格区分已实现、计划、保留、实验和弃用能力。

## 3. 总体分层

```text
┌────────────────────────────────────────────────────────────┐
│ Applications: CustomerSupport / Coding / User Composition  │
├────────────────────────────────────────────────────────────┤
│ Runtime: Agent Loop / Workflow / Session / Checkpoint      │
├────────────────────────────────────────────────────────────┤
│ Capabilities: Model / Router / Tool / RAG / Sandbox        │
├────────────────────────────────────────────────────────────┤
│ Microkernel: Plugin / Registry / Lifecycle / Scope / Event │
├────────────────────────────────────────────────────────────┤
│ Adapters: Storage / Telemetry / CLI / TUI / Evaluation     │
└────────────────────────────────────────────────────────────┘
```

高层模块只能依赖稳定协议或低层服务定义，不依赖某个具体 Provider。组合模板可以选择具体实现，但具体实现不能反向成为核心协议的一部分。

## 4. 微内核边界

微内核只拥有五类职责，状态为 `Implemented`（`2.0.0a1`）：

### 4.1 Plugin Lifecycle

插件使用统一生命周期：

```text
DISCOVERED → RESOLVING → LOADING → ACTIVE
                         ↘ FAILED
ACTIVE → QUIESCING → UNLOADING → DISPOSED
```

- `RESOLVING` 校验 API 版本、依赖、冲突和作用域。
- `LOADING` 创建服务和注册效果。
- `QUIESCING` 停止接收新工作并等待受影响操作进入安全点。
- `UNLOADING` 以确定性规则撤销注册和释放资源。
- 加载失败不得留下半注册服务。

### 4.2 Unified Registry

显式 Python 装配、装饰器、YAML 配置和 Python entry point 全部产生同一种 `PluginSpec`，进入统一注册表。注册操作返回可撤销句柄；卸载插件时，由该插件拥有的注册全部撤销。

插件清单至少包含名称、版本、核心 API 版本、提供能力、必需依赖、可选依赖、冲突项和默认作用域。版本不兼容、依赖缺失和能力冲突必须尽早报错。

### 4.3 Dependency Resolution

能力采用三个角色：

- **Definition**：稳定协议和数据类型。
- **Provider**：协议的具体实现。
- **Consumer**：通过协议使用能力的 Agent、工具或其他插件。

Consumer 依赖 Definition，不依赖具体 Provider。当前 `PluginManager` 在卸载 Provider 插件时先级联卸载依赖它的活跃 Consumer。任意注册被直接撤销后的自动卸载，以及 Provider 恢复后的自动重新装载为 `Planned`。

### 4.4 Scope

内置作用域层级：

```text
Application → Workspace → Session → Agent → Run → Step
```

W-Agent 不内置 Tenant。`ScopePath` 允许插件增加自定义作用域维度，但本地开发者不需要租户概念。下层可以覆盖上层注册；作用域内服务不能隐式泄漏到父作用域。

当前 Registry 可以创建不可变 `RegistryView` 快照。将快照绑定到 Run、让插件更新只影响新 Run，以及活跃 Run 的静默点迁移为 `Planned`。

### 4.5 Events and Pipelines

事件用于松耦合通知，Pipeline 用于可组合拦截。首版计划提供：

- `publish`：广播通知。
- `first`：首个明确结果胜出。
- `serial`：顺序执行，可提前结束。
- `pipeline`：监听器显式调用下一层，可包裹或中止执行。

当前 `EventDispatcher` 实现进程内扩展事件，事件处理器注册由插件生命周期管理。Phase 3 已增加独立的进程内 RunEvent；持久化事件存储及其与实时事件的分离仍为 `Planned`。

## 5. 稳定且可扩展的协议

公共协议采用类型化核心字段加命名空间扩展：

```python
ModelRequest(
    messages=messages,
    temperature=0.2,
    extensions={"vendor.reasoning_effort": "high"},
)
```

适配器必须声明扩展字段是消费、透传还是拒绝。标准字段无法支持时默认报错，禁止静默丢弃。运行上下文采用受控可变设计：核心字段通过正式状态转换 API 修改，插件只能直接写入自己的命名空间。

已经实现的协议包括 `PluginSpec`、`PluginHandle`、`Registry`、`RegistryView`、`ScopePath`、`Contribution`、`Registration`、`EventDispatcher`、模型/路由协议、工具协议，以及 `AgentDefinition`、`AgentLoop`、`RunContext`、`RunEvent` 和 `RunResult`。后续 `Planned` 协议包括：

- 持久化 `Session`、`AgentHandle` 和恢复句柄。
- `WorkflowDefinition`、`WorkflowEngine`、`Checkpoint`。
- `SandboxRequest`、`SandboxHandle`、`SandboxProvider`。

## 6. 模型、路由与探测

状态：Phase 2A 协议、注册表、路由和探测框架，以及 Phase 2B OpenAI-compatible Provider、通用 HTTP 映射层、首批厂商模板、收集式/透传调用执行器和显式注册安全探测服务为 `Implemented`；OpenAI Responses/vLLM 差异适配与跨流恢复为 `Planned`。

模型协议能够表达 OpenAI、Anthropic、Gemini、OpenAI-compatible、Ollama、vLLM 和自定义 Provider 所需能力。当前已提供 OpenAI-compatible Chat Completions Provider、可拆换请求映射/流解码/传输的通用 HTTP Provider，以及 Anthropic、Gemini、Ollama、Qwen、DeepSeek、GLM 和 Turbo 模板。多模态、工具调用、结构化输出、Reasoning、Prompt Cache 等通过能力声明暴露，不采用最低共同特性集；模板不会根据模型名称猜测能力。

路由顺序为：安全与用户策略过滤、能力匹配、健康过滤、评分和选择。Python 策略与 YAML 规则编译成相同的 `RoutingPolicy`。每次选择生成可观察的 `RouteDecision`，记录候选、过滤原因、得分和最终选择。调用属于独立的 `ModelExecutor` Consumer；它可以收集完整流或实时透传事件，按显式策略执行超时、重试与故障转移，且透传后禁止静默重放，不反向污染路由策略。

当前接口探测实现 L1 URL/DNS/TCP/TLS/HTTP、L2 Provider 访问、L3 模型目录和显式授权的 L4/L5 生成/流协议检查，并提供缓存与通用周期调度器。`ModelRegistrationProbeService` 提供可选的“注册即安全探测”装配路径，并把新鲜结果映射到外部路由健康状态；底层注册表不执行 I/O。L6/L7 当前只报告声明并标记未主动验证，CLI/TUI 入口为 `Planned`。可能产生费用的主动探测必须传入 `allow_active=True`。

详细设计见[模型、路由与接口探测](./model-routing.md)。

## 7. Agent Runtime

状态：公开 Run/Loop 协议、有界单 Agent ReAct、进程内/JSONL 事件存储和审批恢复为 `Implemented`；完整 Session 生命周期和通用回放为 `Planned`。

Agent Runtime 定义 Run 生命周期、上下文、事件、取消、预算和结果，不规定唯一推理策略。首版提供一个可用 ReAct 模板，用户可以：

- 替换整个 `AgentLoop`。
- 在 Loop 阶段间插入 Pipeline。
- 增加步骤类型。
- 动态选择下一步。
- 从 Agent 调用 Workflow。

当前 `ReactAgentLoop` 通过公开 `ModelExecutor`、`ToolRegistry` 和 `ToolExecutorProtocol` 完成模型→工具→结果→模型闭环，实施步骤/工具调用预算并在工具需要审批时安全停止。`RunStore` 在事件可见前追加记录；`JsonlRunStore` 支持重启后从审批边界恢复且不重复之前的模型请求。副作用执行前原子 claim，状态不确定时拒绝自动重放。模型调用目前采用收集模式；Agent 逐 Token 事件、完整 Session 投影和通用恢复仍为后续工作。详见[Agent Runtime 与 ReAct Loop](./agents.md)。

## 8. Workflow

Agent Loop 与 Workflow 共享 `RunContext`、事件、取消和结果协议，但保持独立实现。Workflow 支持三种前端：静态 DAG、有状态图和 Python 控制流；它们编译或适配到统一 Workflow Engine 协议。

首版 Checkpoint 仅保证节点边界和显式 `checkpoint()` 位置恢复，不承诺恢复任意 Python 指令位置。首版支持暂停、恢复、取消和节点完成后的状态持久化。嵌套 Workflow、多 Agent 编排和分布式调度为 `Reserved`。

## 9. Tools

状态：Python 函数工具模板、统一注册、策略与执行基础为 `Implemented`；HTTP/MCP/命令行/远程适配和沙箱绑定为 `Planned` 或 `Reserved`。

工具定义、执行、权限和结果彼此分离：

```text
ToolDefinition → Policy Pipeline → ToolExecutor → ToolResult
```

当前已提供 Python 函数模板：工具调用包含稳定调用 ID、参数和作用域；Binding 声明权限与副作用，执行 Context 携带取消和由本地应用授予的批准。参数校验、权限、逐调用审批、超时、取消和 Prompt-free 审计在执行路径中强制生效，不能只依赖提示词或工具可见性。默认不重试工具调用。HTTP/MCP/命令行与远程执行器后续通过相同公开协议接入。

详细设计见[工具注册、策略与执行](./tools.md)。

## 10. Sandbox

首版默认编码环境采用 Docker/OCI。nsjail 和 Wasm 延续各自适用场景，Remote Sandbox 保留协议。Windows 通过 Docker Desktop 或 WSL2 使用隔离后端。

`UnsafeLocalSandbox` 是明确命名的开发模式。它只能由用户主动启用，CLI/TUI 必须展示宿主机执行风险，授权不得由导入的工程装配编码自动开启。安全后端不可用时，默认失败关闭。

详细设计见[沙箱与本地执行](./sandbox.md)。

## 11. 工程装配分享

开发者可以将插件、版本约束、配置、路由、Workflow 引用和沙箱策略组成命名、版本化的 `CompositionManifest`，导出为带模式版本和校验值的可复制编码。

编码不包含密钥，不默认嵌入任意源码，不自动授予本地执行权。导入流程必须先解码、校验、预览依赖与风险，再由用户确认安装和加载。详细设计见[工程装配分享](./project-sharing.md)。

## 12. CLI、TUI 与评测

CLI 和 Textual TUI 都通过公开 Python API 使用框架，不形成私有控制面。首版覆盖初始化、配置校验、插件检查、模型探测、Profile 解析、运行、Checkpoint 恢复、沙箱授权和事件查看。

本地评测提供 Mock、测试上下文、事件录制与回放、模板基准任务，以及 Token、费用、延迟和工具成功率统计。在线评测平台不属于项目目标。

## 13. 1.x 兼容

下一代公共 API 直接覆盖 `w_agent` 顶层导出，不创建 `w_agent.v2`。`BaseAgent.arun()` 等必要 1.x 接口通过最小兼容适配器继续运行，但不会承载新的模型、Workflow 或插件特性。迁移细节见[1.x 迁移](./migration-1x.md)。

## 14. 非目标与保留能力

明确非目标：

- 托管 Agent 服务、云控制面、租户、组织和计费。
- 未经确认自动安装、更新或运行第三方代码。
- 将官方 ReAct 或 Workflow 实现设为不可替换的内核。

`Reserved`：

- 进程外多语言插件 SDK。
- Remote Sandbox 官方 Provider。
- 多 Agent、委派和人工协作协议。
- 分布式 Workflow 调度。
- 装配编码签名与信任网络。
- 完整在线评测和远程运行面板。
