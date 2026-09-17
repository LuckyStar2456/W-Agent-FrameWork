# 路线图与能力状态

[English](./roadmap.en.md) | 简体中文

本文是 W-Agent 能力状态的唯一总览。路线图表达实现顺序，不承诺发布日期。

## 当前 1.5.2

| 能力 | 状态 | 说明 |
|---|---|---|
| `BaseAgent.arun()` | `Implemented` | 最小异步 Agent 抽象 |
| IOC、组件扫描和生命周期 | `Implemented` | 现有 1.x 工程底座 |
| AOP、重试、断路器、超时、舱壁 | `Implemented` | 通用弹性能力 |
| 动态配置和事件总线 | `Implemented` | 尚不是下一代插件内核 |
| 日志、指标、追踪、健康检查 | `Implemented` | 可选后端依赖 |
| Wasm 与 nsjail 技能沙箱 | `Implemented` | 与计划中的 Docker 编码沙箱不同 |
| LangChain 适配和 FastAPI 示例 | `Implemented` | 1.x 集成 |

## 首版计划

| 能力 | 状态 | 阶段 |
|---|---|---|
| Phase 1 微内核公共协议 | `Implemented` | 2.0.0a1 |
| 统一注册表与插件生命周期 | `Implemented` | 2.0.0a1 |
| 依赖解析、可撤销注册、作用域与事件管线 | `Implemented` | 2.0.0a1 |
| 统一模型协议与流事件 | `Implemented` | Phase 2A / 2.0.0a1 |
| OpenAI-compatible Chat Completions 适配 | `Implemented` | Phase 2B / 2.0.0a1 |
| 通用 HTTP 映射层与 SSE/NDJSON 传输 | `Implemented` | Phase 2B / 2.0.0a1 |
| Anthropic、Gemini、Ollama、Qwen 原生模板 | `Implemented` | Phase 2B / 2.0.0a1 |
| DeepSeek、GLM、Qwen-compatible、Turbo 模板注册表 | `Implemented` | Phase 2B / 2.0.0a1 |
| 专用 OpenAI Responses 与 vLLM 差异适配 | `Planned` | Phase 2B |
| Python/YAML 模型路由 | `Implemented` | Phase 2A / 2.0.0a1 |
| 手动探测 API、缓存与周期调度 | `Implemented` | Phase 2A / 2.0.0a1 |
| 显式注册服务的自动安全探测与健康桥接 | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI 探测入口 | `Planned` | Phase 2B |
| 收集式调用、超时、重试与故障转移执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| 安全逐事件透传执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| 跨流断点恢复与续传 | `Planned` | Phase 2B |
| 单 Agent ReAct/tool loop 模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| 进程内 RunEvent 流与有界预算 | `Implemented` | Phase 3 / 2.0.0a1 |
| 本地 JSONL RunEvent 与审批断点恢复 | `Implemented` | Phase 3 / 2.0.0a1 |
| 工具定义、策略和执行器分离 | `Implemented` | Phase 3 / 2.0.0a1 |
| Python 函数工具模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP 与无 Shell 命令工具适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 客户端绑定适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| 官方 MCP stdio/HTTP 会话客户端与发现 | `Planned` | Phase 3/5 |
| 完整 Session 生命周期与通用回放 | `Planned` | Phase 3 |
| DAG、状态图、Python Workflow | `Implemented` | Phase 4 / 2.0.0a1 |
| 本地节点级 Checkpoint、暂停和恢复 | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/Workflow 双向便捷适配器 | `Planned` | Phase 4 |
| Docker/OCI 编码沙箱 | `Planned` | Phase 5 |
| `UnsafeLocalSandbox` 显式授权模式 | `Planned` | Phase 5 |
| 客服/RAG 与编码 Agent 模板 | `Planned` | Phase 5 |
| 工程装配编码与版本管理 | `Planned` | Phase 6 |
| CLI 与 Textual TUI | `Planned` | Phase 6 |
| 本地 Mock、录制回放和评测指标 | `Planned` | Phase 6 |
| 1.x 最小兼容适配器 | `Planned` | 每阶段同步维护 |

## 实施阶段

### Phase 0：设计和文档

- 状态：`Implemented`。
- 固化设计原则、协议边界、状态标记和非目标。
- 更新全部中英文文档。
- 不改变现有运行时代码。

### Phase 1：微内核

- 状态：`Implemented`（`2.0.0a1`）。
- Python 3.11+。
- `PluginSpec`、统一注册表、生命周期、依赖解析、Scope 和事件/Pipeline。
- 四种插件接入方式汇聚到同一注册流程。
- 插件卸载、失败回滚和 Run 快照测试。

### Phase 2：模型与路由

- 状态：`Implemented`（2A 基础）/ `Planned`（2B 适配与执行）。
- 2A 已实现模型请求、响应、流事件、能力声明、扩展参数、Provider 注册表和稳定错误分类。
- 2A 已实现可解释路由决策、Python/YAML 策略、端点嗅探、Provider 探测、缓存和周期调度。
- 2B 已实现带可替换 HTTP 传输的 OpenAI-compatible Chat Completions Provider。
- 2B 已实现通用 HTTP 请求映射层、JSON/SSE/NDJSON 传输、四种原生模板和四种兼容厂商模板。
- 2B 已实现默认单次调用、显式有界重试/故障转移、逐尝试超时与审计记录的收集式和逐事件透传执行器；透传一旦暴露任何事件便禁止静默重放。
- 2B 已实现可选的 `ModelRegistrationProbeService` 注册安全探测路径和 `ProbeHealthBridge`；底层 `ModelRegistry.register()` 保持纯注册语义。
- 2B 后续计划提供 OpenAI Responses/vLLM 差异适配、CLI/TUI 入口和跨流断点恢复。

### Phase 3：Agent 与工具

- 状态：工具执行基础、Run 协议、单 Agent ReAct、本地事件记录与审批恢复为 `Implemented`；完整 Session 生命周期为 `Planned`。
- 已实现可替换 Agent Loop、默认 ReAct 模板、进程内/JSONL RunEvent、步骤/工具预算和不重复首轮模型调用的审批恢复。
- 后续实现 Session 列表/归档、通用事件投影与 Agent 逐 Token 事件。
- 已实现 Python 工具模板、统一注册表、参数校验、权限/逐调用审批、超时/取消、标准结果和 Prompt-free 审计。
- 已实现固定端点 HTTP、无 Shell 命令工具，以及传输中立的 MCP 客户端绑定；后续提供官方 MCP stdio/HTTP 会话客户端、发现和沙箱绑定。

### Phase 4：Workflow

- 状态：本地顺序执行引擎与节点边界恢复为 `Implemented`；双向便捷适配和并行执行为 `Planned`。
- 已实现 DAG、状态图和 Python API，共用 `WorkflowEngineProtocol`、事件和结果协议。
- 已实现内存/JSONL 节点 Checkpoint、显式暂停、重启恢复和边界取消。
- 节点执行状态不确定时保留 `RESUMING` 并拒绝自动重放；不恢复任意 Python 指令栈。
- 后续提供 Agent 调用 Workflow、Workflow 节点调用 Agent 的便捷适配器，以及可选并行 DAG 调度。

### Phase 5：本地模板与沙箱

- Docker/OCI Sandbox Provider。
- 明确授权的 `UnsafeLocalSandbox`。
- 客服/RAG 和编码 Agent 模板。
- Windows Docker Desktop/WSL2 验证。

### Phase 6：分享、界面与评测

- 命名和版本化的 `CompositionManifest`。
- 装配编码导入、预览、校验和确认。
- CLI、Textual TUI、事件查看和 Checkpoint 恢复。
- Mock、录制回放、客服与编码基准任务。

## 保留但未排期

以下能力为 `Reserved`：

- 进程外多语言插件 SDK。
- Remote Sandbox 官方实现。
- MCP 完整工具 Provider。
- 多 Agent、委派、人工审批工作流和 Agent 间通信。
- 嵌套及分布式 Workflow。
- 工程装配编码签名、发布索引和信任网络。
- 完整在线评测服务。
- 语音等专用模态适配器；核心多模态协议将在模型阶段保留。

## 非目标

- 托管 W-Agent 平台。
- 首版租户、组织、计费、云账户管理。
- 自动运行导入装配中的第三方代码。
- 在隔离后端不可用时静默使用宿主机执行。
