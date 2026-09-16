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
| 统一模型协议与流事件 | `Planned` | Phase 2 |
| OpenAI、Anthropic、Gemini、OpenAI-compatible、本地模型适配 | `Planned` | Phase 2 |
| Python/YAML 模型路由 | `Planned` | Phase 2 |
| 手动、注册时、周期接口探测 | `Planned` | Phase 2 |
| ReAct Agent Loop 模板 | `Planned` | Phase 3 |
| 工具定义、策略和执行器分离 | `Planned` | Phase 3 |
| Session 事件记录与回放 | `Planned` | Phase 3 |
| DAG、状态图、Python Workflow | `Planned` | Phase 4 |
| 节点级 Checkpoint、暂停和恢复 | `Planned` | Phase 4 |
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

- 模型请求、响应、流事件、能力声明和扩展参数。
- Provider Adapter、路由决策和三类接口探测。
- 错误、限流、超时、重试与故障转移。

### Phase 3：Agent 与工具

- Run、Session 和追加式事件记录。
- 可替换 Agent Loop 与默认 ReAct 模板。
- Python/HTTP 工具、执行策略、结果和审批扩展点。

### Phase 4：Workflow

- DAG、状态图和 Python API。
- 节点级 Checkpoint、暂停、恢复、取消。
- Agent 调用 Workflow 和 Workflow 节点调用 Agent。

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
