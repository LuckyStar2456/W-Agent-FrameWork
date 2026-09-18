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
| Wasm 与 nsjail 技能沙箱 | `Implemented` | 1.x 接口；尚未适配新的 SandboxProvider |
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
| CLI/TUI 安全端点探测入口 | `Implemented` | Phase 2B / 2.0.0a1 |
| CLI/TUI 配置化 Provider 安全/主动探测 | `Experimental` | Phase 2B/6 / 2.0.0a1 |
| 收集式调用、超时、重试与故障转移执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| 安全逐事件透传执行器 | `Implemented` | Phase 2B / 2.0.0a1 |
| Provider 输入/输出 Token 规范化计量 | `Implemented` | Phase 2B / 2.0.0a1 |
| 跨流断点恢复与续传 | `Planned` | Phase 2B |
| 单 Agent ReAct/tool loop 模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| 进程内 RunEvent 流与有界预算 | `Implemented` | Phase 3 / 2.0.0a1 |
| Run 级 Token 可见计量与硬预算 | `Implemented` | Phase 3 / 2.0.0a1 |
| Session 累计与逐尝试 Token 账本 | `Implemented` | Phase 3/6 / 2.0.0a1 |
| 版本化价格表、费用计量与 Run 费用硬预算 | `Implemented` | Phase 3/6 / 2.0.0a2 |
| Agent 跨 Session 聚合、调用前预估器与软阈值 | `Planned` | Phase 3/6 |
| 本地 JSONL RunEvent 与审批断点恢复 | `Implemented` | Phase 3 / 2.0.0a1 |
| 工具定义、策略和执行器分离 | `Implemented` | Phase 3 / 2.0.0a1 |
| Python 函数工具模板 | `Implemented` | Phase 3 / 2.0.0a1 |
| HTTP 与无 Shell 命令工具适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 客户端绑定适配器 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 2026-07-28 stdio/Streamable HTTP 客户端与发现 | `Implemented` | Phase 3 / 2.0.0a1 |
| MCP 旧版初始化协商、MRTR 与订阅流 | `Planned` | Phase 3/5 |
| 本地 Session 生命周期与跨 Run 文本投影 | `Implemented` | Phase 3 / 2.0.0a1 |
| 多模态/工具/RunEvent 通用回放 | `Planned` | Phase 3/6 |
| DAG、状态图、Python Workflow | `Implemented` | Phase 4 / 2.0.0a1 |
| 本地节点级 Checkpoint、暂停和恢复 | `Implemented` | Phase 4 / 2.0.0a1 |
| Agent/Workflow 双向便捷适配器 | `Implemented` | Phase 4 / 2.0.0a1 |
| Workflow Checkpoint 脱敏汇总、显式 Definition 加载与 CLI/TUI 恢复 | `Experimental` | Phase 4/6 / main（未发布） |
| Docker/OCI 编码沙箱 | `Implemented` | Phase 5 / 2.0.0a1 |
| `UnsafeLocalSandbox` 显式授权模式 | `Implemented` | Phase 5 / 2.0.0a1 |
| Sandbox 命令工具绑定 | `Implemented` | Phase 5 / 2.0.0a1 |
| 客服/RAG 与编码 Agent 模板 | `Implemented` | Phase 5 / 2.0.0a1 |
| 工程装配编码、安全预览与版本管理 | `Implemented` | Phase 6 / 2.0.0a1 |
| 通用插件无导入预览、确认批量加载与 TUI 卸载 | `Experimental` | Phase 1/6 / main（未发布） |
| Typer/Rich CLI、Textual TUI 与 Session 生命周期界面 | `Experimental` | Phase 6 / 2.0.0a1 |
| 本地配置化文本 Agent 运行入口 | `Experimental` | Phase 6 / 2.0.0a1 |
| 配置化工具选择、显式代码加载与 CLI 审批恢复 | `Experimental` | Phase 3/6 / 2.0.0a1 |
| Agent 审批 Checkpoint 脱敏列表（API/CLI/TUI） | `Implemented` | Phase 3/6 / 2.0.0a1 |
| TUI 工具加载/权限/精确审批恢复与脱敏实时 RunEvent | `Experimental` | Phase 3/6 / 2.0.0a3 |
| 脚本化模型 Mock、显式录制/回放和本地评测指标 | `Experimental` | Phase 6 / 2.0.0a1 |
| CLI/TUI 本地评测入口与安全报告 | `Experimental` | Phase 6 / 2.0.0a1 |
| 评测价格/费用指标 | `Experimental` | Phase 6 / 2.0.0a2 |
| 客服/编码内置基准集 | `Planned` | Phase 6 |
| 1.x 最小 `LegacyAgentAdapter` | `Implemented` | Phase 6 / 2.0.0a1 |

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

- 状态：`Implemented`（2A 基础与 2B 首批适配/执行）；专用差异适配与跨流恢复为 `Planned`。
- 2A 已实现模型请求、响应、流事件、能力声明、扩展参数、Provider 注册表和稳定错误分类。
- 2A 已实现可解释路由决策、Python/YAML 策略、端点嗅探、Provider 探测、缓存和周期调度。
- 2B 已实现带可替换 HTTP 传输的 OpenAI-compatible Chat Completions Provider。
- 2B 已实现通用 HTTP 请求映射层、JSON/SSE/NDJSON 传输、四种原生模板和四种兼容厂商模板。
- 2B 已实现默认单次调用、显式有界重试/故障转移、逐尝试超时与审计记录的收集式和逐事件透传执行器；透传一旦暴露任何事件便禁止静默重放。
- 2B 已统一 Provider 上报的输入、输出和缓存输入 Token；`usage_reported` 明确区分真实零用量与 Provider 未上报，不用零值伪装完整计量。
- 2B 已实现可选的 `ModelRegistrationProbeService` 注册安全探测路径和 `ProbeHealthBridge`；底层 `ModelRegistry.register()` 保持纯注册语义。
- 2B 已提供 CLI/TUI 的无凭据 L1 安全端点探测，以及从严格本地配置装配 Provider 的安全目录/显式授权主动生成探测。Provider 单独装配不注册、不发起 I/O；`safe` 是否访问远程目录由具体 Provider 决定，`active` 才验证最小生成与流终止协议。后续提供 OpenAI Responses/vLLM 差异适配和跨流断点恢复。

### Phase 3：Agent 与工具

- 状态：工具执行基础、Run 协议、单 Agent ReAct、本地事件记录、审批恢复与本地 Session 生命周期为 `Implemented`；通用事件回放为 `Planned`。
- 已实现可替换 Agent Loop、默认 ReAct 模板、进程内/JSONL RunEvent、步骤/工具预算和不重复首轮模型调用的审批恢复。
- 已实现 `TokenBudget` 的 Run 级输入、输出、总量硬限制，`RunResult.usage` 与 `TOKEN_USAGE` 事件公开累计值；审批 Checkpoint 保存计量状态。`max_output_tokens` 仍只表示单次模型生成上限。
- 当前预算依据成功响应中 Provider 返回的实际用量在响应后核算，并用剩余输出/总量收紧下一次请求上限；可用 `require_usage=True` 在 Provider 不上报时失败关闭。首个请求的输入 Token 不能在没有分词器时精确预知，失败/中断的重试尝试也可能已经产生未上报用量。
- 已实现 Session 级累计、覆盖重试/故障转移的 `AttemptRecord` Token 账本，以及 RunEvent/CLI 可见性；未报告的失败尝试保持未知并使严格计量失败关闭。
- 已实现应用提供的版本化价格表、普通/缓存输入与输出费用计量、费用完整性、审批断点持久化和 Run 费用硬预算；缺少价格或用量时失败关闭，不从 Token 数静默推断金额。
- 后续实现 Agent 跨 Session 聚合、可插拔调用前 Token 预估器与软阈值动作。
- 已实现 `SessionManager`、内存/JSON Store、创建/列表/归档/取消归档、跨 Run 文本投影，以及 Session 内 Agent 启动和审批恢复。
- 后续实现多模态、工具和任意 RunEvent 的通用投影/回放，以及 Agent 逐 Token 文本事件。
- 已实现 Python 工具模板、统一注册表、参数校验、权限/逐调用审批、超时/取消、标准结果和 Prompt-free 审计。
- 已实现固定端点 HTTP、无 Shell 命令工具、传输中立的 MCP 绑定，以及 MCP 2026-07-28 stdio/Streamable HTTP JSON/SSE 客户端、分页发现、显式绑定与 `x-mcp-header`。发现不会自动注册、授权或批准工具。
- 后续提供 2025 版 `initialize` 兼容协商、MRTR 自动输入交换、订阅流和 MCP Sandbox 绑定。

### Phase 4：Workflow

- 状态：本地顺序执行引擎、节点边界恢复与 Agent 双向适配为 `Implemented`；并行执行为 `Planned`。
- 已实现 DAG、状态图和 Python API，共用 `WorkflowEngineProtocol`、事件和结果协议。
- 已实现内存/JSONL 节点 Checkpoint、显式暂停、重启恢复和边界取消。
- 当前 main 已实现 `WorkflowCheckpointSummary`、与稳定 Store 分离的 `WorkflowCheckpointCatalog` 查询协议、显式 `module:attribute` Definition 加载，以及按名称/版本/类型精确校验的 CLI/TUI 恢复；运行时值默认隐藏，代码加载与执行分别确认。
- 节点执行状态不确定时保留 `RESUMING` 并拒绝自动重放；不恢复任意 Python 指令栈。
- 已实现 `agent_workflow_node()`，以及受工具权限/逐调用审批管线保护的 `workflow_start_tool()` / `workflow_resume_tool()`；适配器只依赖公开协议且允许替换消息、权限上下文和结果映射。
- 后续提供可选并行 DAG 调度；Agent 审批断点与 Workflow 暂停的自动级联恢复仍保留为后续设计。

### Phase 5：本地模板与沙箱

- 状态：统一协议、Docker Provider、显式授权本地 Provider、命令工具绑定和首批 Agent 模板为 `Implemented`；更广环境验收为 `Planned`。
- 已实现 Docker/OCI 生命周期 Handle、默认断网、资源限制、最小权限参数、固定镜像策略和清理。
- 已实现仅能通过运行时授权对象创建的 `UnsafeLocalSandboxProvider`；安全后端失败不会自动降级。
- 已实现 `sandbox_command_tool()`，通过现有权限、逐调用审批、取消和审计管线执行。
- 已实现完全可覆盖的客服/RAG 与编码 `AgentTemplate`；模板不绑定模型、不自动注册工具，也不授予权限或本地执行权。
- 后续实现网络 allowlist、nsjail/Wasm 新协议适配和 Windows Docker Desktop/WSL2 广泛验证。

### Phase 6：分享、界面与评测

- 已实现命名和版本化的 `CompositionManifest`、确定性编码/解码、大小限制、完整性校验、安全预览与冲突安全的本地版本/别名库。
- 装配预览阶段不访问网络、不安装、不导入也不执行插件。当前 main 已实现独立 YAML 引用的无导入预览、明确确认后的事务化批量加载，以及 TUI 持久进程内卸载；装配依赖解析、包安装确认和装配到插件引用的桥接仍为 `Planned`。
- 已提供 `wagent` CLI（保留 `w-agent` 别名）和可启动的 Textual TUI 基础；覆盖工作区初始化、模板列表、安全端点探测、装配导出/预览/保存/列表、本地 Session 创建/查看/归档/恢复和可见 Token 汇总，以及 TUI 离线装配检查。
- 已实现严格本地 JSON 到 Provider/路由/ReAct/Run/Session 的文本运行装配；CLI/TUI 每次调用均要求显式授权，凭据只从环境变量引用读取。
- 已实现由宿主 Catalog 限定的配置化工具选择、逐次权限授予、独立 Python 工具代码加载确认，以及已知 Session/Run/Call ID 的 CLI 审批恢复；配置本身不能导入、授权或批准工具。
- 已实现 Agent 审批 Checkpoint 的 API/CLI/TUI 脱敏列表；摘要不含 Prompt、参数值、输出或凭据。
- 已实现无网络的脚本化 Model Provider、需显式敏感内容授权的 JSONL 录制/顺序回放，以及可替换 Scorer 的顺序评测运行器；CLI 可读取严格 JSON 用例集，默认使用一次性状态，并输出 Token 完整性、延迟、错误与工具成功率。JSON 报告默认排除 Prompt、输出、Metadata 和异常正文。
- 已实现 TUI 顺序评测页面：严格 JSON 用例、一次性状态、`EVALUATE` 单次授权、汇总指标和可选安全报告；不默认展示 Prompt 或输出。
- 已实现 TUI 工具入口独立加载确认、本次权限、精确 Session/Run/Call ID 审批恢复和脱敏实时 RunEvent；确认不持久化，界面不展示 Prompt、模型文本、工具参数或工具结果。
- 已实现从显式选择的本地 State Root 汇总和恢复 Workflow Checkpoint；不会自动复制、合并或迁移 Store。
- 当前 main 已实现配置值脱敏的插件引用预览、`--confirm-plugin-code` 短生命周期 CLI 验证，以及绑定 `LOAD PLUGINS` / `UNLOAD <name>` 的 TUI 生命周期操作；第三方包安装/升级仍为 `Planned`。
- 已实现评测报告、CLI 与 TUI 的版本化费用汇总；客服与编码内置基准任务仍为 `Planned`。
- 已实现旧 `BaseAgent.arun()` 到 Workflow 节点的严格文本兼容桥；其他旧 API Bridge 仍按需规划，不建立第二套运行时。

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
