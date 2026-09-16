# CLI 与 TUI

[English](./tui.en.md) | 简体中文

状态：`Planned`。当前 1.5.2 只有基础 `w-agent` CLI；本文描述下一代本地开发界面。

## 原则

- CLI、TUI 和 Python API 使用同一个 Application 与 Registry。
- TUI 不依赖 W-Agent 托管服务或后台云控制面。
- 界面不拥有框架专用能力；所有操作可以通过公开 Python API 完成。
- 可能安装代码、产生模型费用或访问宿主机的操作必须确认。

## CLI 计划

```text
wagent init
wagent config validate
wagent plugins list|inspect|enable|disable
wagent profile list|resolve
wagent probe
wagent doctor
wagent run
wagent checkpoint list|resume
wagent composition export|inspect|import
wagent tui
```

CLI 默认输出适合人阅读的文本，并提供结构化 JSON 输出选项。命令失败返回稳定退出码，不把警告当作成功。

## TUI 技术

TUI 使用 Textual，通过 `wagent-framework[tui]` 可选依赖安装。基础 CLI 使用 Typer/Rich。TUI 采用进程内模式启动框架，不要求常驻守护进程；远程连接能力为 `Reserved`。

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
