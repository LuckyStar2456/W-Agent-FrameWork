# CLI 与 TUI

[English](./tui.en.md) | 简体中文

状态：Typer/Rich CLI、可启动 Textual TUI、本地 Session 生命周期、配置化 Agent 运行入口、Token/费用可见性、Agent Checkpoint 脱敏列表、CLI/TUI 工具选择/权限/审批恢复、脱敏实时 RunEvent 和本地评测为 `Experimental`（当前 `2.0.0a3`）；Workflow Checkpoint 汇总与通用插件操作仍为 `Planned`。

## 原则

- CLI、TUI 和 Python API 使用同一个 Application 与 Registry。
- TUI 不依赖 W-Agent 托管服务或后台云控制面。
- 界面不拥有框架专用能力；所有操作可以通过公开 Python API 完成。
- 可能安装代码、产生模型费用或访问宿主机的操作必须确认。

## 当前 CLI

```text
wagent init
wagent profile list
wagent probe <endpoint>
wagent doctor
wagent composition export|inspect|save|list
wagent session create|list|show|archive|unarchive
wagent checkpoint list [--session <id>]
wagent provider-probe --mode safe|active|capability [--confirm-active-probe]
wagent run <prompt> --confirm-model-call
wagent run-resume <session-id> <run-id> --approve-tool-call <call-id> --confirm-model-call
wagent evaluate <cases.json> --confirm-model-call [--report <report.json>]
wagent tui
```

以上命令已实现。CLI 默认输出适合人阅读的文本；模板、初始化、探测、装配检查、列表、Session 生命周期和评测提供结构化 JSON。`session show` 与 `evaluate` 展示输入、输出与缓存输入 Token，以及可用时的版本化费用，并明确标记计量是否完整。评测默认使用一次性状态，报告默认不含 Prompt 与输出。失败返回稳定非零退出码。`probe` 执行不带凭据和请求体的 L1 探测；`provider-probe` 从严格配置装配 Provider，主动模式必须额外传入 `--confirm-active-probe`。

兼容期继续保留 `w-agent` 命令名以及基础 `config`、`bean` 子命令；规范入口为 `wagent`。

`run` 使用严格的 `.wagent/config.json` 与环境变量凭据引用；每次都必须显式传入 `--confirm-model-call`。可选版本化价格配置为 CLI/TUI Run、Session、Checkpoint 和评测提供费用与完整性。配置可从显式 Catalog 选择工具；CLI 仅在 `--tool-entry` 与独立的 `--confirm-tool-code` 同时出现时导入开发者 Python 工具，并通过 `--grant-permission` 授予本次权限。TUI 使用独立的 `RUN`、`LOAD TOOLS`、权限输入和 `RESUME` 确认，且精确绑定 Session/Run/Call ID；确认立即清空。RunEvent 面板只展示白名单身份、状态、Token 和费用字段。TUI Models 页也提供配置化安全/主动 Provider 探测，主动生成必须输入 `ACTIVE` 且确认不会持久化。`config validate`、Workflow Checkpoint 聚合、通用插件操作和装配安装确认仍为 `Planned`。

TUI Evaluation 页要求输入 `EVALUATE` 才顺序运行严格 JSON 用例集；默认一次性状态，确认立即清空，只显示 Token/费用/延迟/工具结果和通过状态，并可写默认脱敏报告。自定义 Scorer、输出持久化和开发者工具入口使用 Python API/CLI。

## TUI 技术

TUI 使用 Textual，通过 `wagent-framework[tui]` 可选依赖安装。基础 CLI 使用 Typer/Rich。TUI 采用进程内模式启动框架，不要求常驻守护进程；远程连接能力为 `Reserved`。当前界面提供十个首版分区、真实的 Session 创建/列表/归档/恢复、离线装配检查、安全端点探测、模板信息和 Docker 可用性检查；尚未实现的分区会明确显示 Planned，而不伪装可操作。

下一代 CLI 的规范命令为 `wagent`；现有 `w-agent` 在兼容期作为别名保留。

## 首版页面

### Home

显示当前 Workspace、Python/W-Agent 版本、活动 Profile、插件错误和最近 Run。

### Models

管理 Provider 配置引用、模型目录和探测结果。主动探测前展示潜在费用和将发送的最小测试类型。

### Plugins

显示来源、版本、API 兼容性、提供能力、依赖、作用域和状态。安装或升级第三方包需要用户明确执行；首版不自动更新。

### Composition

查看解析后的 Profile，比较两个命名版本，导出编码，导入时预览依赖、配置差异和安全风险。

### Run

当前可读取严格本地配置并启动文本 Agent，显示最终输出、输入/输出 Token 与版本化费用；用户必须输入 `RUN` 才会发起模型调用。工具入口仅在另行输入 `LOAD TOOLS` 后导入，权限仅对本次运行有效。界面通过公开 `RunEventCallback` 实时投影已持久化事件，不读取 Loop 私有状态，也不显示 Prompt、模型文本或工具参数。

### Sessions

使用与 Python API 相同的 `JsonSessionStore` 创建、列出、归档和恢复本地 Session。详情显示每个 Session 的 Run 数、累计 Token 和同版本/币种时的累计费用；配置化 Agent 启动属于 Run 页面。

### Checkpoints

当前可刷新本地 Agent 审批 Checkpoint 的脱敏摘要，显示 Run/Session、状态、工具名、Call ID、参数名、Token 和费用，不显示 Prompt、参数值或输出。用户重新提供配置、工具入口、权限和精确 Call ID，并输入 `LOAD TOOLS`/`RESUME` 后可恢复执行；授权不从 Checkpoint 继承。Workflow Checkpoint 的统一列表、版本比较与引导恢复仍为 `Planned`。

### Sandbox

显示 Docker/OCI 可用性、镜像、挂载、网络和资源限制。启用 `UnsafeLocalSandbox` 时显示持续风险标识，并要求明确确认。

### Evaluation

运行本地客服和编码基准，比较模型或装配版本的成功率、延迟、Token、估算费用和工具错误。

## 安全交互

以下操作不能由模型或导入配置替用户确认：

- 安装或升级插件。
- 首次运行未知第三方插件。
- 导入并执行开发者 Python 工具入口。
- 启用 `UnsafeLocalSandbox`。
- 放宽 Docker 挂载或网络策略。
- 执行可能产生模型费用的主动能力探测。

确认记录绑定具体操作、版本和配置摘要，配置改变后不能复用旧确认。
