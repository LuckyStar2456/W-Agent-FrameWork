# CLI 与 TUI

[English](./tui.en.md) | 简体中文

状态：Typer/Rich CLI 与可启动 Textual TUI 基础为 `Experimental`（`2.0.0a1`）；配置化 Agent 运行、Checkpoint 管理、插件操作与评测仍为 `Planned`。

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
wagent tui
```

以上命令已实现。CLI 默认输出适合人阅读的文本；模板、初始化、探测、装配检查、列表和 Session 生命周期提供结构化 JSON。`session show` 同时展示每个 Run 的输入、输出与缓存输入 Token，并明确标记用量是否完整。失败返回稳定非零退出码。`probe` 当前只执行不带凭据和请求体的 L1 安全探测；可能计费的主动 Provider 探测仍需后续配置装配和明确授权。

兼容期继续保留 `w-agent` 命令名以及基础 `config`、`bean` 子命令；规范入口为 `wagent`。

`config validate`、插件操作、交互 `run`、Checkpoint 管理和装配安装/加载确认仍为 `Planned`。

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

启动客服、编码或自定义 Agent，流式显示消息、模型选择、工具调用、Workflow 节点、预算和事件。界面通过 RunEvent 投影，不读取 Loop 私有状态。

### Sessions

使用与 Python API 相同的 `JsonSessionStore` 创建、列出、归档和恢复本地 Session。列表显示每个 Session 的 Run 数与累计 Token；配置化 Agent 启动仍属于 Run 页面后续工作。

### Checkpoints

列出可恢复 Workflow，显示创建时间、定义版本、插件快照和最后完成节点。版本不兼容时阻止恢复并说明原因。

### Sandbox

显示 Docker/OCI 可用性、镜像、挂载、网络和资源限制。启用 `UnsafeLocalSandbox` 时显示持续风险标识，并要求明确确认。

### Evaluation

运行本地客服和编码基准，比较模型或装配版本的成功率、延迟、Token、估算费用和工具错误。

## 安全交互

以下操作不能由模型或导入配置替用户确认：

- 安装或升级插件。
- 首次运行未知第三方插件。
- 启用 `UnsafeLocalSandbox`。
- 放宽 Docker 挂载或网络策略。
- 执行可能产生模型费用的主动能力探测。

确认记录绑定具体操作、版本和配置摘要，配置改变后不能复用旧确认。
