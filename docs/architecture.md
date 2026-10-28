# W-Agent 架构设计

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./architecture.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

## 1. 定位

W-Agent 是借鉴 Spring IoC、DI、AOP 与生命周期思想的开放 Harness 开发框架，不是托管平台或固定 Harness。开发者通过注解、显式 Python 或配置定义自己的执行体系，拥有模型、路由、Agent Loop、Workflow、工具、状态、沙箱和界面的最终控制权。

当前架构以 [Harness 核心基线](./harness-core.md)为准：M0–M4 已完成阶段验收，IoC/DI/AOP 是新核心而非仅 1.x 兼容层。M5 的[三条教程](./harness-development.md)与[最终验收](./harness-acceptance.md)记录开发者交付；新核心尚未发布。下文的 2.0.0 模块说明保留历史发布边界。

| 新核心 | 责任 | 不负责 |
|---|---|---|
| `AssemblyPlan` 与三个编译入口 | 统一依赖、参数、作用域及切面定义 | 不导入配置指定代码、不创建对象 |
| `ApplicationContext` | 工厂所有权、DI、作用域、AOP、启动回滚与清理 | 不选择固定 Agent 算法 |
| `ApplicationPlugin` / Registry | 插件生命周期桥接、能力可见性；保留自定义 `scope_order` | 注册表不成为第二个对象容器 |
| `ApplicationProject` / `ApplicationHost` | 公开操作、运行/流任务及调用作用域 | 不监管未登记后台任务、不提供安全隔离 |
| `local_application.py` | 可替换的默认 Runtime/Workflow 装配 | 不限制用户模型与 Harness 协议 |
| CLI / TUI | 显式加载同一项目与 JSON/显示适配 | 不绕过授权、不维持私有装配分支 |

1.5.2 兼容底座已实现 IOC、AOP、配置、生命周期、弹性、安全与可观测性；2.0.0 已发布，制品与验证证据见[正式版记录](./acceptance-2026-10-01-stable-release.md)。本文同时描述已实现、实验性和 `Planned` 的后续架构；具体可用性与验收边界以[路线图](./roadmap.md)为准，不把 `Experimental` 称为稳定能力，也不把计划项称为已经提供。

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

当前 `EventDispatcher` 实现进程内扩展事件，事件处理器注册由插件生命周期管理。Phase 3 已增加独立的 RunEvent，并通过 `RunStore`/`JsonlRunStore` 在可见前持久化，与实时事件消费分离。`2.0.0a4`新增只读游标分页、可替换 JSON 脱敏投影、声明式顶层/嵌套字段策略、显式工具参数增量和显式图片/音频输出投影；通用新模态仍为 `Planned`。

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

已经实现的协议包括 `PluginSpec`、`PluginHandle`、`Registry`、`RegistryView`、`ScopePath`、`Contribution`、`Registration`、`EventDispatcher`、模型/路由协议、工具协议，Agent Run/Loop 协议，以及 Workflow Definition/Engine/Checkpoint 协议。后续 `Planned` 协议包括：

- 通用持久化 `AgentHandle` 和任意位置恢复句柄（本地 Session/审批与 Workflow 节点恢复已实现）。

## 6. 模型、路由与探测

状态：Phase 2A 协议、注册表、路由和探测框架，以及 Phase 2B OpenAI-compatible Provider、通用 HTTP 映射层、OpenAI Responses/vLLM 专用适配、厂商模板、收集式/透传调用执行器和显式注册安全探测服务为 `Implemented`；显式文本前缀恢复为 `Experimental`，Provider 原生游标协议/执行器接线位于`2.0.0a4`，内置厂商游标适配仍为 `Planned`。

模型协议能够表达 OpenAI、Anthropic、Gemini、OpenAI-compatible、Ollama、vLLM 和自定义 Provider 所需能力。当前已提供 OpenAI-compatible Chat Completions Provider、OpenAI Responses 映射、vLLM 专用扩展、可拆换请求映射/流解码/传输的通用 HTTP Provider，以及 Anthropic、Gemini、Ollama、Qwen、DeepSeek、GLM 和 Turbo 模板。多模态、工具调用、结构化输出、Reasoning、Prompt Cache 等通过能力声明暴露，不采用最低共同特性集；模板不会根据模型名称猜测能力。

路由顺序为：安全与用户策略过滤、能力匹配、健康过滤、评分和选择。Python 策略与 YAML 规则编译成相同的 `RoutingPolicy`。每次选择生成可观察的 `RouteDecision`，记录候选、过滤原因、得分和最终选择。调用属于独立的 `ModelExecutor` Consumer；它可以收集完整流或实时透传事件，按显式策略执行超时、重试与故障转移，且透传后禁止静默重放，不反向污染路由策略。

当前接口探测实现 L1 URL/DNS/TCP/TLS/HTTP、L2 Provider 访问、L3 模型目录和显式授权的 L4/L5 生成/流协议检查，并提供缓存与通用周期调度器。`ModelRegistrationProbeService` 提供可选的“注册即安全探测”装配路径，并把新鲜结果映射到外部路由健康状态；底层注册表不执行 I/O。CLI/TUI 已提供无凭据 L1 与配置化 Provider 安全/主动入口；主动模式需要单次确认。L6/L7 当前只报告声明并标记未主动验证。Provider 单独装配不执行 I/O，而 `safe` 是否访问远程目录由具体 Provider 的目录协议决定。

详细设计见[模型、路由与接口探测](./model-routing.md)。

## 7. Agent Runtime

状态：公开 Run/Loop 协议、有界单 Agent ReAct、进程内/JSONL 事件存储、审批恢复和本地 Session 生命周期为 `Implemented`；只读游标分页、可替换 JSON 脱敏投影、声明式顶层/嵌套字段策略和显式多模态输出投影在`2.0.0a4`。

Agent Runtime 定义 Run 生命周期、上下文、事件、取消、预算和结果，不规定唯一推理策略。首版提供一个可用 ReAct 模板，用户可以：

- 替换整个 `AgentLoop`。
- 在 Loop 阶段间插入 Pipeline。
- 增加步骤类型。
- 动态选择下一步。
- 从 Agent 调用 Workflow。

当前 `ReactAgentLoop` 通过公开 `ModelExecutor`、`ToolRegistry` 和 `ToolExecutorProtocol` 完成模型→工具→结果→模型闭环，实施步骤、工具调用、Run 级 Token 预算和基于应用版本化价格表的费用预算，并在工具需要审批时安全停止。可替换 `TokenEstimator` 位于中立请求与网络调用之间，提供调用前估算、输出额度收紧和软阈值事件；内核不绑定厂商 tokenizer，估算失败是否停止由 `TokenBudget.require_estimate` 明确决定。显式启用时，可替换 `CostEstimator` 再消费无 Prompt 的路由、重放上限与 Token 估算；默认 `PricingCostEstimator` 产生首选尝试和完整重试/故障转移费用包络，在模型生成请求前提供警告或硬停止。两类估算都不替代调用后的 Provider 实报核算。`emit_text_deltas` 显式启用时，Loop 使用公开安全模型流，把文本增量投影为先持久化后可见的 `MODEL_TEXT_DELTA`，默认收集模式不变；`emit_output_blocks` 独立控制已完成媒体块的持久化。`RunStore` 在事件可见前追加记录；`JsonlRunStore` 支持重启后从审批边界恢复且不重复之前的模型请求，累计 Token、费用、预算估算策略与尝试账本也随 Checkpoint 保存。副作用执行前原子 claim，状态不确定时拒绝自动重放。通用跨进程模型续流仍为后续工作。详见[Agent Runtime 与 ReAct Loop](./agents.md)。

`2.0.0a4`另把工具参数增量作为独立显式开关投影为原始 `MODEL_TOOL_CALL_DELTA`；默认界面只展示安全元数据，不展示工具名或参数。图片/音频输出通过独立显式开关、可替换编码器和三档披露投影进入 `MODEL_OUTPUT_BLOCK`。嵌套结构可通过声明式路径规则复制、重命名或固定掩码；任意业务转换继续使用自定义投影器。

`2.0.0a4`同时把回放投影抽象为 `RunEventProjector`。原始游标页和投影页分离；安全默认投影在回放层移除内容并验证 JSON 兼容性，CLI/TUI 不再先接收原始页。应用可以替换投影器，但仍负责原始 Store 的读取授权和业务字段公开策略。

声明式 `FieldPolicyRunEventProjector` 在此协议之上提供默认拒绝的事件类型/顶层字段允许与固定掩码；`NestedFieldRunEventProjector` 进一步提供对象/数组源路径到对象目标路径的复制、重命名和固定掩码。两者都不进入 Kernel 注册表，也不替代应用授权；任意计算保留给自定义实现。

`ModelOutputEventEncoder` 是 Agent Runtime 与持久化格式之间的可替换边界。默认实现只编码中立图片/音频块并限制内联大小；`MultimodalRunEventProjector` 再把元数据、引用和正文披露分离。外部 Blob Store、新模态和业务授权无需修改 Loop 核心。

`SessionManager` 在 Loop 外通过公开协议管理创建、列表、归档、跨 Run 文本投影和审批恢复，并提供内存/JSON Store。`agent_usage()` 按 Agent 名称从不可变 Run 摘要生成不含 Prompt/输出的跨 Session 用量、费用和完整性视图；归档纳入由调用者显式选择。它不读取 Loop 私有状态，也不把工具或多模态事件伪装成已回放内容。

## 8. Workflow

状态：顺序本地执行、三种前端、节点事件、节点边界恢复和 Agent 双向适配为 `Implemented`；显式有界异步 DAG 并行位于`2.0.0a4`，嵌套调度为 `Reserved`。

Agent Loop 与 Workflow 使用相似但独立的 Context、事件、取消和结果协议，避免把推理循环强行合并进编排器。`WorkflowRegistry` 通过共享微内核注册表按版本和 Scope 管理定义；`LocalWorkflowEngine` 接受静态 DAG、有状态图和 Python 处理器三种 `WorkflowDefinition`，通过同一个 `WorkflowEngineProtocol` 运行。`WorkflowStore` 可整体替换；内置 `InMemoryWorkflowStore` 与 `JsonlWorkflowStore`。

`agent_workflow_node()` 把固定 Agent 定义适配为节点；`workflow_start_tool()` 与 `workflow_resume_tool()` 把固定 Workflow 定义适配为标准工具，并复用权限、逐调用审批、取消和审计管线。两边都只依赖公开协议，不形成内核特权。Agent 审批断点与 Workflow 暂停不会自动级联恢复，调用者必须显式接管非完成状态。

Checkpoint 只保证节点边界恢复。执行节点前先 claim 为 `RESUMING`，节点完成后才写回 `READY` 或 `PAUSED`；进程若在节点执行中断，恢复会失败关闭，避免静默重复外部副作用。Python 入口在恢复时重新调用处理器，并携带持久化状态与 `resume_count`，不恢复任意 Python 指令位置或调用栈。`2.0.0a4`为 DAG 增加默认关闭的有界异步前沿并行；整批使用同一已提交快照，失败/冲突不自动重放。嵌套 Workflow、多 Agent 编排和分布式调度尚未实现。详见[Workflow 与节点恢复](./workflows.md)。

## 9. Tools

状态：Python、HTTP、无 Shell 命令、Sandbox 命令工具模板、MCP 绑定和 MCP 2026-07-28 stdio/Streamable HTTP 客户端，以及统一注册、策略与执行基础为 `Implemented`；MCP 2025 初始化协商处于`2.0.0a4`，旧版服务器主动请求、MRTR 自动交换与订阅流为 `Planned`。

工具定义、执行、权限和结果彼此分离：

```text
ToolDefinition → Policy Pipeline → ToolExecutor → ToolResult
```

当前已提供 Python 函数、固定端点 HTTP、无 Shell 本地命令、Sandbox 命令模板、任意 MCP Client 绑定，以及首方 MCP stdio/Streamable HTTP JSON/SSE 客户端。`McpClient` 为每个请求写入当前稳定协议元数据，支持有界分页发现和工具调用；`discover_mcp_bindings()` 只返回 Binding，不自动注册或授予权限。HTTP 实现固定端点、不跟随重定向、限制响应大小，并安全生成标准头与 `x-mcp-header`；stdio 实现无 Shell argv、换行 JSON-RPC、取消通知和有界关闭。`2.0.0a4`额外提供显式选择的 `McpLegacyClient` 与旧版 HTTP Session 传输。工具调用仍通过统一权限、逐调用审批、超时、取消和 Prompt-free 审计路径。旧版服务器主动请求、MRTR 自动输入交换和订阅流尚未实现。

详细设计见[工具注册、策略与执行](./tools.md)。

## 10. Sandbox

状态：统一协议/注册表、Docker/OCI 后端和显式授权本地后端为 `Implemented`；nsjail/Wasm 新协议适配为 `Planned`，Remote Sandbox 为 `Reserved`。

`DockerSandboxProvider` 创建生命周期归属明确的容器 Handle，默认关闭网络、使用只读根文件系统、drop capabilities、禁止提权并限制 CPU、内存和 PID；只挂载明确工作区，关闭或执行状态不确定时删除容器。镜像默认要求摘要或非 `latest` 标签。网络当前支持 `none` 与 `bridge`，细粒度 allowlist 尚未实现。

`UnsafeLocalSandboxProvider` 是明确命名的危险开发模式，不是安全沙箱。它只能接收 `UnsafeLocalAuthorization.grant()` 在当前进程生成的显式授权对象，授权不会由配置、插件或装配编码反序列化产生。安全后端不可用时不会自动切换到本地模式。本地模式要求显式选择 `SandboxNetwork.BRIDGE` 和读写工作区，拒绝无法兑现的断网/只读声明；它不执行容器资源隔离，只提供无 Shell argv、工作目录、超时、取消和输出上限。

详细设计见[沙箱与本地执行](./sandbox.md)。

## 11. 工程装配分享

开发者可以将插件、版本约束、配置、路由、Workflow 引用和沙箱策略组成命名、版本化的 `CompositionManifest`，导出为带模式版本和校验值的可复制编码。

当前已实现规范 Manifest、确定性编码/解码、大小与完整性校验、安全预览，以及冲突安全的本地版本/别名库。编码不包含密钥、绝对本地路径或任意源码，也不能授予本地执行权。预览、依赖计划和安装计划不访问网络、不导入插件。`2.0.0a4`的独立安装层读取宿主提供的精确 wheel/SHA-256 闭包与来源映射，形成绑定 Composition、Index、入口、版本和哈希的请求摘要；只有显式授权后才通过可替换 `PackageInstaller` 在选定 Sandbox 中执行。安装树复验后仍需第二次插件代码加载授权，才进入普通 `PluginManager`。在线来源发现、自动锁定/更新和热迁移不属于当前实现。详细设计见[工程装配分享](./project-sharing.md)。

## 12. CLI、TUI 与评测

CLI 和 Textual TUI 都通过公开 Python API 使用框架，不形成私有控制面。首版覆盖初始化、配置校验、插件检查、模型探测、Profile 解析、运行、Checkpoint 恢复、沙箱授权和事件查看；`2.0.0a4`还公开同一套锁定安装计划、精确安装确认和独立插件加载确认，不把界面确认下沉成内核特权。

当前 `Experimental` 本地评测层提供无网络脚本化模型、显式授权的 JSONL 模型录制/顺序回放、可替换 Scorer，以及 Token/版本化费用完整性、延迟、错误和工具成功率统计。录制层是可替换 Model Provider 装饰器，评测目标只依赖公开 `RunResult`，因此都不是内核特权。CLI/TUI 已能从严格 JSON 或进程内 `builtin:` 套件运行配置化 Agent，并使用一次性状态和隐私安全报告默认值。版本化客服/编码套件通过可替换注册表提供，只声明用例与工具契约，不携带工具、权限或在线服务；在线评测平台不属于项目目标。详见[本地测试、模型回放与评测](./testing-evaluation.md)。

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
