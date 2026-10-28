# 沙箱与本地执行

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./sandbox.en.md) | 简体中文

## 当前能力

状态：`Implemented`。

1.5.2 提供 Wasm/WASIX 和 nsjail 技能沙箱。两者在真实后端不可用时失败关闭。当前版本另外实现统一 `SandboxProvider`、`SandboxRegistry`、Docker/OCI 后端、nsjail 通用命令后端、显式授权本地后端和 Sandbox 命令工具。`ProviderSkillSandbox` 将旧 `execute(skill, script_name, args)` 调用接入新版 Provider；Wasm 尚未实现通用命令与硬资源限制协议。

## Provider 状态

状态：本地首版为 `Implemented`。

| Provider | 用途 | 平台 |
|---|---|---|
| Docker/OCI | `Implemented`：编码 Agent、命令和完整工作区 | Docker CLI/Daemon 支持的平台 |
| nsjail provider + skill adapter | `Implemented`：通用命令与旧 Skill 调用桥接；真实隔离待平台验收 | Linux，curated rootfs + cgroup v2 |
| Wasm adapter | `Planned`：把现有 Skill 后端接入新协议 | 支持的 Wasmer 平台 |
| `UnsafeLocalSandboxProvider` | `Implemented`：用户明确授权的本地开发 | 所有支持平台 |
| Remote Sandbox | 远程隔离服务协议 | `Reserved` |

## SandboxProvider

`SandboxProvider.open(SandboxSpec)` 返回有明确生命周期的 `SandboxHandle`。Handle 通过 `execute(SandboxCommand)` 执行无 Shell argv，通过 `close()` 收敛容器或本地运行上下文。Provider 使用 `sandbox.provider` 能力进入共享、版本化、分 Scope 的注册表。

`SandboxSpec` 包含工作区、镜像、读写模式、网络模式、CPU/内存/PID、环境和容器工作目录。`SandboxCommand` 独立声明 argv、超时和输出上限。Docker 环境值通过权限受限的临时 env 文件交给 CLI，并在创建后删除；它们不进入命令参数、日志、Checkpoint 或装配编码。

CPU 和超时必须为有限正数；内存、PID 和输出上限必须为正整数，拒绝布尔值、NaN 和无穷大。字符串网络/工作区枚举会规范化，未知值（包括尚未实现的 `allowlist`）立即拒绝。

## nsjail 与旧技能桥接

`NsJailSandboxProvider(rootfs, cgroup_path=...)` 需要宿主预先准备的精简 rootfs、可委派的 cgroup v2 和 nsjail。每条命令新建 jail，共享显式工作区；并非持续运行的容器。CPU、内存、进程数分别映射到 cgroup quota/memory/pids，另有壁钟超时和输出限制。仅支持 `network=none`，保留网络 namespace，并通过 seccomp 拒绝 socket 系统调用。需要 socketpair 的异步运行时也可能被拒绝。不能创建 namespace/cgroup 或执行命令时不重试较弱策略。

`available()` 只检查目录和 CLI；成功不代表已验证内核隔离、权限或 cgroup 委派。宿主还需配置数值 UID/GID 映射和可读/可写工作区权限。显式环境值经 nsjail CLI 参数传递，可能被宿主进程查看，不应放入秘密。配置和 argv 构造依据 [nsjail 官方实现](https://github.com/google/nsjail/blob/master/cmdline.cc)。

`/tmp` 的 64 MiB tmpfs 使用每条命令独立的临时 protobuf 配置：`options` 只指定 `size`/`mode`，`rw`、`nosuid`、`nodev`、`noexec`、`mandatory` 使用独立字段。不能把这些布尔挂载标志塞进 CLI `--mount` 的文件系统参数。字段依据 [官方 MountPt schema](https://github.com/google/nsjail/blob/master/config.proto#L26-L58)，实际标志映射依据 [官方挂载实现](https://github.com/google/nsjail/blob/master/mnt_legacy.cc#L85-L115)。配置不插入用户文本，动态路径、环境和命令都保留为独立 argv；先加载配置再指定 CLI 限制，避免配置解析的 `CopyFrom` 覆盖限制。配置存放于框架新建的私有目录，成功、异常和取消均删除，不读取或覆盖用户配置文件。解析/挂载失败不会降级。

CPU 配额按 [官方 cgroup v2 实现](https://github.com/google/nsjail/blob/master/cgroup2.cc#L236-L250) 换算；额外限制换算后的 uint32 范围，防止上游乘以 1000 溢出。内存字段限制 RAM，尚未额外限制 swap。cgroup 目录须已授权必要控制器与写权限；nsjail 本身可能尝试启用控制器，普通目录存在并不证明能执行。

```python
from pathlib import Path
from w_agent import NsJailSandboxProvider, ProviderSkillSandbox, SandboxSpec

provider = NsJailSandboxProvider(
    Path("/opt/w-agent/rootfs"),
    cgroup_path=Path("/sys/fs/cgroup/w-agent"),
)
sandbox = ProviderSkillSandbox(
    provider,
    SandboxSpec(Path.cwd(), cpu_limit=0.5, memory_bytes=256 * 1024 * 1024),
    python_executable="/usr/bin/python3",
)
# skill 来自已审核的 Skill；调用本身仍需宿主授权。
result = await sandbox.execute(skill, "main", {"input": "hello"})
```

适配器为每次执行创建临时只读 payload，仅复制选中脚本、JSON 参数和 runner，始终关闭 Handle 并删除 payload，不挂载原项目。兼容 `execute(args)` 与全局 `result` 返回方式；异步函数能否运行取决于后端策略。`SandboxSpec.workspace` 在此作为模板被替换；不支持相邻文件导入或写回。Docker 也可用同一适配器，需配置包含 Python 的镜像。旧 Wasm 接口仍可直接调用，但 SDK 的 CPU/内存/PID 硬限制未得到验证，因此不能声明为兑现 `SandboxSpec` 的通用 Provider。

## Docker/OCI 默认策略

- 默认无特权容器。
- 只挂载明确工作区。
- 默认限制 CPU、内存、进程数和执行时间。
- 网络默认关闭；当前可选 `bridge`，细粒度 allowlist 仍为 `Planned`。
- 镜像默认必须使用摘要或非 `latest` 标签；可变标签必须在 Provider 构造时明确允许。Provider 默认传入 `--pull never`，`missing`/`always` 需要宿主显式选择。
- Root filesystem 只读，drop 全部 Linux capabilities，设置 `no-new-privileges`，仅 `/tmp` 使用受限 tmpfs。
- 默认容器用户为 `65534:65534`，应用可为兼容特定镜像显式调整。
- Run 结束后清理容器和临时卷。
- 执行超时、取消或状态不确定时关闭 Handle 并删除容器，禁止继续复用。

创建命令超时或失败时也尝试按本次唯一名称清理容器；删除失败后 Handle 禁止执行，调用者可再次 `close()` 重试。守护进程失联时无法保证远程删除已完成。

默认 Keepalive 使用镜像中的 `sh`/`sleep`，可以通过 `SandboxSpec.keepalive_command` 替换。框架不会自动拉取或信任镜像；镜像来源与扫描仍由本地开发者或上层 Profile 管理。

## UnsafeLocalSandbox

`UnsafeLocalSandboxProvider` 是危险的开发模式，不是安全沙箱。

启用要求：

- Python 调用 `UnsafeLocalAuthorization.grant(source, acknowledge_host_access=True)` 明确生成当前进程授权对象。
- 界面显示将访问宿主机文件、进程和网络。
- 授权对象不可从配置或装配编码反序列化产生。
- 导入项目、插件默认值和模型调用不能自行开启。
- 授权记录来源与时间；当前 CLI/TUI 的锁定包安装使用不同于 Docker 的显式本地确认，通用授权审计日志仍为 `Planned`。

安全后端创建失败时，框架不会自动切换到 `UnsafeLocalSandboxProvider`。本地 Provider 无法落实网络隔离或只读工作区，因此调用者必须显式选择 `SandboxNetwork.BRIDGE` 和读写工作区；安全取向的值会被拒绝而不是静默忽略。容器用户和 CPU/内存/PID 字段在危险模式中也不能作为安全保证。它只提供无 Shell argv、工作目录、环境选择、超时、取消和输出上限。

## 编码 Agent

编码 Agent 模板为 `Implemented`，但模板只声明系统指令、推荐工具和默认预算，不自行授予执行权。底层 Handle 已支持在同一容器和工作区中连续运行命令；Docker 挂载可以是只读或读写。更完整的写回路径校验、补丁预览与持久 Sandbox Session 仍为后续能力。

## 锁定插件包安装

`2.0.0a4`的 `SandboxPipPackageInstaller` 复用同一 `SandboxProvider` 协议。安装前必须显式选择 `SandboxNetwork.BRIDGE` 和读写工作区，并用绑定精确请求摘要的 `PluginInstallAuthorization` 确认网络与包代码执行。默认 CLI/TUI 选择 Docker；安装器为每次请求新建空白暂存目录，Docker 仅把该目录作为可写工作区挂载，不挂载包含 Session、Checkpoint 等内容的整个本地状态目录。关闭沙箱后，安装器校验暂存树，再复制到最终目录并再次校验；失败时清理本次创建的暂存与目标目录。Unix 映射当前 UID/GID 以写入绑定目录，Windows Docker Desktop 使用镜像用户，同时仍保留只读根、drop capabilities 和禁止提权。不隔离本地模式还要求单独的宿主访问确认；暂存目录不能限制它读取其他宿主文件，也不会因 Docker 失败自动回退。

默认安装命令使用无 Shell argv，并固定 `--isolated --require-hashes --only-binary=:all: --no-deps`。完整依赖闭包、版本和 artifact SHA-256 来自宿主锁目录；`--isolated` 忽略 pip 环境变量和用户配置，但不代表镜像内全局/站点配置或代理已被隔离。安装器不解析未锁依赖、不接受 sdist、不自动拉取或信任 Docker 镜像，也不把 Sandbox 环境中的凭据投影到安装结果。安装成功只产生按请求摘要定位、附有独立内容树摘要的目录和脱敏来源记录，插件加载仍需独立确认。

## 工具集成

`sandbox_command_tool()` 为一次工具调用打开 Provider Handle、执行命令并始终关闭，默认需要 `sandbox.execute` 权限并按 `WRITE` 副作用要求逐调用审批。需要跨多步保持容器时，应用直接持有 Handle。

`command_tool()` 是单独的宿主命令开发适配器，不是沙箱；它默认需要 `process.execute` 和逐调用审批。应用不应把该工具默认暴露给不可信 Agent。

## 尚未实现

- Docker 网络域名/IP allowlist 与镜像扫描。`bridge` 是开放网络，不是 allowlist；代理环境变量或声明列表不构成网络隔离，本版不提供未经强制执行验证的 allowlist 模板。
- Wasm 到新 `SandboxProvider` 的通用命令与硬资源限制适配。
- 编码 Agent 工作区写回审核、持久 Sandbox Session 与通用 TUI 授权审计面。
- Remote Sandbox 官方实现。

2026-10-01 早期的新增适配器、资源映射、取消和清理通过 fake runner 回归；tmpfs 配置还使用独立 protobuf 解析器按上游 schema 子集验证（该 QA 检查在 protobuf 不可用时跳过，其余清理/注入测试不依赖它）。随后正式候选收尾已完成授权的真实 Docker 冒烟；该结果不追溯扩大早期模拟测试范围，也不代表所有宿主平台、nsjail 或 Wasmer 均完成验收。最终制品构建/上传仍独立于沙箱测试，见[基础发布清单](./stable-release-baseline.md)。
