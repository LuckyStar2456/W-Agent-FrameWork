# W-Agent 开发者指南

[English](./developer.en.md) | 简体中文

## 1. 开发基线

当前仓库版本为 `2.0.0a1`，Phase 1 微内核、Phase 2 模型基础、Phase 3 Agent/工具基础和 Phase 4 本地 Workflow 基础已经实现，1.x API 继续保留。任何新能力都必须同步更新中英文文档，并标记状态。

下一代实现目标：

- Python 3.11+。
- 异步内核，同步 API 只在用户边界提供。
- 公共 API 直接从 `w_agent` 导出，不创建 `w_agent.v2`。
- 官方默认实现只能使用公开协议和注册表。
- 所有注册、任务和资源都必须有明确生命周期所有者。

## 2. 当前仓库结构

状态：`Implemented`。

```text
w_agent/
├── aop/             # 切点、通知和代理
├── agents/          # Run 协议与可替换 ReAct Loop
├── config/          # 动态配置
├── container/       # IOC 与 Bean 生命周期
├── core/            # 1.x Agent、装饰器、事件与 Doctor
├── deployment/      # FastAPI 示例集成
├── distributed/     # Redis 锁
├── lifecycle/       # 初始化与销毁
├── kernel/          # 插件、注册表、作用域与事件管线
├── models/          # 模型协议、注册表、路由与探测
├── observability/   # 日志、指标、追踪、健康检查
├── resilience/      # 超时和舱壁
├── sandbox/         # 新一代 Sandbox 协议、Registry、Docker 与显式本地后端
├── scanner/         # AST 组件扫描
├── security/        # MCP 认证
├── skills/          # Skill 和沙箱
├── testing/         # 测试辅助
├── tools/           # 工具注册、策略、执行、Python 模板与 LangChain 兼容
└── workflows/       # DAG、状态图、Python Workflow、Store 与本地引擎
```

新的 ReAct Runtime 与本地 Workflow Engine 已独立于 `BaseAgent.arun()` 实现；后续持久化 Session 和组合适配继续建立在公开协议上。

## 3. 插件设计规则

状态：`Implemented`（`2.0.0a1`）。

每个能力必须区分 Definition、Provider 和 Consumer。插件依赖稳定 Definition，不依赖具体 Provider。

插件清单包含：

```yaml
name: example-router
version: 1.0.0
api_version: "2"
provides:
  - model.router
requires:
  - model.registry >=2.0
optional:
  - telemetry.tracer
scope: application
```

实现要求：

- 加载前校验依赖、版本、冲突和配置。
- 注册返回可撤销句柄。
- 失败加载回滚已经发生的注册。
- 卸载先进入静默，再释放资源。
- 配置缺失不得静默跳过插件。
- 插件更新默认不改变活跃 Run 的解析快照。

完整设计见[插件系统](./plugin-system.md)。

## 4. 扩展点选择

| 目标 | 扩展方式 |
|---|---|
| 新模型或私有参数 | `ModelProvider` 与命名空间扩展 |
| 新路由算法 | `RoutingPolicy` |
| 新推理链路 | `AgentLoop` |
| Loop 阶段拦截 | Event/Pipeline 插件 |
| 新 Workflow 执行方式 | `WorkflowEngine` |
| 新工具来源 | `ToolBinding` / `ToolRegistry` / `ToolExecutor` |
| 新隔离环境 | `SandboxProvider` |
| 新存储 | Session、Checkpoint 或 Memory Provider |
| 新界面 | 使用公开运行时 API 和事件流 |

不要为了一个新能力直接修改默认 Agent Loop，除非公共协议本身无法表达该能力。

## 5. 配置与装配

四种入口最终生成同一个 `PluginSpec`：

1. 显式 Python 构造，作为行为基准。
2. 装饰器注册，作为语法便利层。
3. YAML 配置，解析和验证后生成相同规格。
4. Python entry point，用于独立发布插件的发现。

配置层不执行任意 Python 表达式。秘密值通过环境变量或凭据引用注入，不能进入装配编码。

## 6. 类型与扩展字段

稳定协议使用 dataclass、Protocol、Enum 和 Pydantic 边界模型。进程内可信类型不重复解析；文件、网络、插件配置、持久化和模型输出边界必须校验。

扩展字段使用命名空间：

```python
extensions={
    "vendor.reasoning_effort": "high",
    "my_plugin.cache_key": "...",
}
```

插件不得修改其他插件的命名空间。核心字段只通过正式状态转换 API 改变。

## 7. 并发、取消与关闭

- 每个异步操作只有一个生命周期所有者。
- `asyncio.TaskGroup` 管理同一操作的子任务。
- 取消信号必须传播到模型流、工具、Workflow 和沙箱。
- 关闭流程先拒绝新工作，再等待静默，最后清理资源。
- 依赖卸载与插件热更新必须等待受影响工作到达安全点。
- 不允许后台任务脱离所有者后继续修改已卸载服务。

## 8. 安全规则

- Docker/OCI 是编码 Agent 的默认执行后端；默认断网、资源受限且失败关闭。
- `UnsafeLocalSandboxProvider` 必须接收当前进程显式生成的 `UnsafeLocalAuthorization`。
- 工程装配导入不能携带或授予本地执行许可。
- 沙箱不可用时失败关闭。
- 插件安装、升级和首次运行需要明确操作。
- 日志、事件和导出清单不得包含凭据。

## 9. 测试要求

首版计划要求每个能力至少覆盖：

- 协议与配置单元测试。
- Provider/Consumer 组合测试。
- 注册撤销和插件卸载测试。
- 缺失依赖、冲突版本和失败回滚测试。
- 取消、超时和关闭测试。
- 事件录制与回放测试。
- 客服或编码模板的真实组合测试。

模型测试优先使用确定性 Mock；真实 API 测试必须显式启用并避免泄漏凭据。

## 10. 文档规则

- 中文文件与 `.en.md` 英文文件同时修改。
- README 只描述可验证的当前状态和清晰标记的计划。
- 新能力更新架构、路线图、API 和对应专题文档。
- `Reserved` 能力不得写成待办承诺或现有 API。
- 示例中的计划 API 必须明确标记为不可执行设计示例。

## 11. 兼容策略

1.x 使用人数有限，因此只保留基础兼容。下一代 API 直接占用 `w_agent` 顶层命名空间；旧 `BaseAgent` 等接口由兼容适配器承载。新特性不继续加入 1.x 抽象。

详见[1.x 迁移](./migration-1x.md)。
