# 沙箱与本地执行

[English](./sandbox.en.md) | 简体中文

## 当前能力

状态：`Implemented`。

1.5.2 提供 Wasm/WASIX 和 nsjail 技能沙箱。两者在真实后端不可用时失败关闭。当前 `2.0.0a1` 另外实现统一 `SandboxProvider`、`SandboxRegistry`、Docker/OCI 后端、显式授权本地后端和 Sandbox 命令工具。旧 Wasm/nsjail 类尚未适配到新协议。

## Provider 状态

状态：本地首版为 `Implemented`。

| Provider | 用途 | 平台 |
|---|---|---|
| Docker/OCI | `Implemented`：编码 Agent、命令和完整工作区 | Docker CLI/Daemon 支持的平台 |
| nsjail adapter | `Planned`：把现有 Skill 后端接入新协议 | Linux |
| Wasm adapter | `Planned`：把现有 Skill 后端接入新协议 | 支持的 Wasmer 平台 |
| `UnsafeLocalSandboxProvider` | `Implemented`：用户明确授权的本地开发 | 所有支持平台 |
| Remote Sandbox | 远程隔离服务协议 | `Reserved` |

## SandboxProvider

`SandboxProvider.open(SandboxSpec)` 返回有明确生命周期的 `SandboxHandle`。Handle 通过 `execute(SandboxCommand)` 执行无 Shell argv，通过 `close()` 收敛容器或本地运行上下文。Provider 使用 `sandbox.provider` 能力进入共享、版本化、分 Scope 的注册表。

`SandboxSpec` 包含工作区、镜像、读写模式、网络模式、CPU/内存/PID、环境和容器工作目录。`SandboxCommand` 独立声明 argv、超时和输出上限。Docker 环境值通过权限受限的临时 env 文件交给 CLI，并在创建后删除；它们不进入命令参数、日志、Checkpoint 或装配编码。

## Docker/OCI 默认策略

- 默认无特权容器。
- 只挂载明确工作区。
- 默认限制 CPU、内存、进程数和执行时间。
- 网络默认关闭；当前可选 `bridge`，细粒度 allowlist 仍为 `Planned`。
- 镜像默认必须使用摘要或非 `latest` 标签；可变标签必须在 Provider 构造时明确允许。
- Root filesystem 只读，drop 全部 Linux capabilities，设置 `no-new-privileges`，仅 `/tmp` 使用受限 tmpfs。
- 默认容器用户为 `65534:65534`，应用可为兼容特定镜像显式调整。
- Run 结束后清理容器和临时卷。
- 执行超时、取消或状态不确定时关闭 Handle 并删除容器，禁止继续复用。

默认 Keepalive 使用镜像中的 `sh`/`sleep`，可以通过 `SandboxSpec.keepalive_command` 替换。框架不会自动拉取或信任镜像；镜像来源与扫描仍由本地开发者或上层 Profile 管理。

## UnsafeLocalSandbox

`UnsafeLocalSandboxProvider` 是危险的开发模式，不是安全沙箱。

启用要求：

- Python 调用 `UnsafeLocalAuthorization.grant(source, acknowledge_host_access=True)` 明确生成当前进程授权对象。
- 界面显示将访问宿主机文件、进程和网络。
- 授权对象不可从配置或装配编码反序列化产生。
- 导入项目、插件默认值和模型调用不能自行开启。
- 授权记录来源与时间；后续 CLI/TUI 审计面仍为 `Planned`。

安全后端创建失败时，框架不会自动切换到 `UnsafeLocalSandboxProvider`。本地 Provider 无法落实网络隔离或只读工作区，因此调用者必须显式选择 `SandboxNetwork.BRIDGE` 和读写工作区；安全取向的值会被拒绝而不是静默忽略。容器用户和 CPU/内存/PID 字段在危险模式中也不能作为安全保证。它只提供无 Shell argv、工作目录、环境选择、超时、取消和输出上限。

## 编码 Agent

编码模板仍为 `Planned`。底层 Handle 已支持在同一容器和工作区中连续运行命令；Docker 挂载可以是只读或读写。上层编码模板仍需实现写回路径校验、补丁预览与会话生命周期。

## 工具集成

`sandbox_command_tool()` 为一次工具调用打开 Provider Handle、执行命令并始终关闭，默认需要 `sandbox.execute` 权限并按 `WRITE` 副作用要求逐调用审批。需要跨多步保持容器时，应用直接持有 Handle。

`command_tool()` 是单独的宿主命令开发适配器，不是沙箱；它默认需要 `process.execute` 和逐调用审批。应用不应把该工具默认暴露给不可信 Agent。

## 尚未实现

- Docker 网络域名/IP allowlist、镜像拉取策略和镜像扫描。
- nsjail/Wasm 到新 `SandboxProvider` 的适配。
- 编码 Agent 工作区写回审核、持久 Sandbox Session 与 TUI 授权面。
- Remote Sandbox 官方实现。
