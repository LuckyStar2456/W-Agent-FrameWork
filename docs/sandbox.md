# 沙箱与本地执行

[English](./sandbox.en.md) | 简体中文

## 当前能力

状态：`Implemented`。

1.5.2 提供 Wasm/WASIX 和 nsjail 技能沙箱。两者在真实后端不可用时失败关闭。Wasm 适合受限技能脚本，nsjail 适合 Linux 进程隔离；它们尚未形成统一的下一代 `SandboxProvider`。

## 首版目标

状态：`Planned`。

| Provider | 用途 | 平台 |
|---|---|---|
| Docker/OCI | 编码 Agent、命令和完整工作区 | Linux、macOS、Windows Docker Desktop/WSL2 |
| nsjail adapter | Linux 轻量进程隔离 | Linux |
| Wasm adapter | 小型可移植技能 | 支持的 Wasmer 平台 |
| `UnsafeLocalSandbox` | 用户明确授权的本地开发 | 所有支持平台 |
| Remote Sandbox | 远程隔离服务协议 | `Reserved` |

## SandboxProvider

Provider 接收镜像、工作区挂载、环境变量引用、网络策略、资源限制、超时和命令等请求，返回有明确生命周期的 Handle。Handle 提供文件、进程和关闭操作；所有子进程在 Handle 关闭时收敛。

工作区挂载默认最小权限。密钥通过临时引用注入，不进入日志、Checkpoint 或装配编码。

## Docker/OCI 默认策略

- 默认无特权容器。
- 只挂载明确工作区。
- 默认限制 CPU、内存、进程数和执行时间。
- 网络默认关闭或使用显式 allowlist，由 Profile 决定。
- 镜像使用固定标签或摘要；可变标签必须明确允许。
- Run 结束后清理容器和临时卷。
- 导出的补丁或文件变更回写前必须经过明确路径校验。

## UnsafeLocalSandbox

`UnsafeLocalSandbox` 是危险的开发模式，不是安全沙箱。

启用要求：

- 用户从 Python、CLI 或 TUI 明确选择。
- 界面显示将访问宿主机文件、进程和网络。
- 授权绑定当前本地配置，不能随工程装配编码传播。
- 导入项目、插件默认值和模型调用不能自行开启。
- 审计事件记录启用来源和作用域，但不记录密钥。

安全后端创建失败时，框架不得自动切换到 `UnsafeLocalSandbox`。

## 编码 Agent

编码模板的文件读取、命令执行、测试和构建默认都在同一 Sandbox Handle 中完成，保证文件和进程看到一致工作区。只读宿主文件可通过明确挂载提供；写回范围必须受 Workspace 策略限制。

## 工具集成

工具声明自己的副作用和所需能力。执行 Pipeline 在调用前解析沙箱、权限、资源预算和审批。工具不能绕过 `SandboxProvider` 私自创建宿主子进程；显式本地工具必须标记为危险能力。
