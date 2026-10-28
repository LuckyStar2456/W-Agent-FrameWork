# 插件系统

[English](./plugin-system.en.md) | 简体中文

状态：微内核插件 API 在 `2.0.0a1` 为 `Implemented`。`2.0.0a4`提供不导入代码的 YAML 预览、显式确认后的批量加载与 TUI 卸载控制。基于宿主锁目录的 Sandbox 包安装和独立加载确认已包含于 `2.0.0a4`。在线来源发现、自动锁定和自动更新仍为 `Planned`。

## 目标

插件系统让模型、路由、Agent Loop、Workflow、工具、存储、沙箱、界面和评测模块使用同一装配与生命周期机制。内置插件和第三方插件遵循相同规则。

## 接入方式

四种方式统一为 `PluginSpec`：

1. 显式 Python 构造。
2. 装饰器注册。
3. YAML 配置。
4. Python entry point 发现。

显式 Python 构造是行为基准；其他入口不能拥有额外语义。

最小示例：

```python
from w_agent import CapabilityDeclaration, PluginManager, ScopePath, plugin


@plugin(
    name="hello-provider",
    version="1.0.0",
    provides=(CapabilityDeclaration("example.hello", version="1.0.0"),),
)
async def hello_provider(context):
    context.register("example.hello", "hello", version="1.0.0")


manager = PluginManager()
handle = await manager.load(hello_provider)
value = manager.registry.resolve("example.hello", ScopePath.application())
await handle.unload()
```

## YAML 引用与明确授权

```yaml
plugins:
  - entry: my_plugins.router:setup
    enabled: true
    config:
      endpoint: https://example.test
  - entry: my_plugins.optional:setup
    enabled: false
```

`2.0.0a4` 的安全操作顺序为：

```text
wagent plugin inspect --config .wagent/plugins.yml
  → 仅解析 entry、enabled 和配置键，不导入模块
wagent plugin validate-load --config .wagent/plugins.yml --confirm-plugin-code
  → 导入并加载启用项，报告活跃快照，然后在命令退出前卸载
```

TUI Plugins 页使用同一 `PluginManager` 和加载 API。输入一次性 `LOAD PLUGINS` 后，插件在当前 TUI 进程中保持活跃；卸载要求输入与插件名绑定的 `UNLOAD <name>`，并先卸载依赖该 Provider 的活跃插件。配置值会传给插件，但预览和生命周期投影只显示配置键，不显示值。

同一批次中任一导入或加载失败时，本批次先前加载的插件按逆序卸载。已在 Manager 中活跃、但不属于本批次的插件不参与该回滚。重复引用会在导入前被拒绝，`enabled: false` 的引用不会被导入。

### 取消与清理

加载批次被取消时也会回滚。清理一旦开始，调用方的重复取消会延后到该清理任务完成，再向调用方传播 `CancelledError`，不会静默视为成功。quiesce/unload/disposer 自身抛出取消，也不会跳过剩余归属 effect。部分加载回滚收敛到 `FAILED`，卸载收敛到 `DISPOSED`，并移除注册和监听器。并发关闭 effect scope 会等待同一个清理任务；Manager 关闭时，即使某个插件清理报错或取消，也会尝试清理其余插件。

替换操作在旧版本清理边界被取消后，不再启动新 setup；若已加载但尚未向调用方交付 handle 时，生命周期通知被取消，也会卸载刚加载的记录。这些保证针对框架归属注册和清理完成，不表示插件外部副作用被回滚。受信清理 hook 必须自行限制 I/O 并最终返回；框架不会超时遗弃清理任务或强制终止 Python 代码。专属取消及相邻插件回归已通过，不涉及网络或包安装。

## 锁定安装与加载

安装链路与生命周期链路使用不同协议和授权：

```text
CompositionPlan + PluginInstallCatalog
  → plan_plugin_installations()（离线、无导入）
  → 用户确认精确 request digest、网络与包代码执行
  → PackageInstaller / SandboxPipPackageInstaller
  → PluginInstallResult（内容树摘要 + 本地站点 + entry）
  → 用户再次确认插件代码加载
  → load_installed_plugin_references() → PluginManager
```

`PackageInstaller` 是开放协议，应用可替换 pip、包格式、内部 Registry 或远程构建器。默认实现只接受完整 SHA-256 wheel 闭包，禁止 sdist 和隐式依赖解析，并使用调用者选择的 `SandboxProvider`。离线计划显示 Index 来源的协议、主机和端口，供用户确认网络目标。Docker 是 CLI/TUI 默认选项；默认安装器只向 Docker 挂载每次新建的空白暂存目录，关闭沙箱并复验暂存树后才复制到最终站点，避免把整个本地状态目录暴露给包安装代码；`UnsafeLocalSandboxProvider` 只在用户明确确认宿主访问后可用，不能靠暂存目录实现隔离。安装目录在进入 `PluginManager` 前重新计算内容树摘要；校验会拒绝软链接、预编译字节码与 `__pycache__`，而不是忽略可能被 Python 执行的文件。导入已安装插件后、执行 setup 前，还会确认入口模块文件处于已验证站点内、插件名称和版本与锁定记录一致；这不取消插件导入本身执行代码的风险，所以仍需独立加载授权。路径租约随已安装插件批次卸载而释放。若插件入口模块已在进程的 `sys.modules` 中，加载会失败关闭，避免误用别处缓存的代码；普通 Python 导入不能保证模块完全反加载，也可能在使用期间生成字节码缓存，因此再次加载或切换同名版本可能需要新进程或重新安装，热迁移仍不是现有能力。

默认 pip 命令使用 `--isolated`，忽略 pip 环境变量和用户配置；镜像内全局/站点配置及网络代理仍由宿主负责，因此来源预览不保证网络只访问一个目标。私有源认证需由宿主提供自定义 `PackageInstaller`。

## 清单

```yaml
name: my-model-router
version: 1.3.0
api_version: "2"
provides:
  - model.router
requires:
  - model.registry >=2.0,<3.0
optional:
  - telemetry.tracer
conflicts:
  - model.router:exclusive
scope: application
```

插件可以提供多个能力，但能力键、版本和冲突必须显式声明。当前 YAML Loader 校验引用和配置容器结构；插件专属配置模式校验为 `Planned`。

## 生命周期

```text
DISCOVERED → RESOLVING → LOADING → ACTIVE
                         ↘ FAILED
ACTIVE → QUIESCING → UNLOADING → DISPOSED
```

每次加载拥有一个 effect scope。服务、事件处理器、后台任务、文件观察器和连接都登记到该 scope。加载失败或插件卸载时，系统撤销本次加载拥有的资源。

清理顺序依赖同一资源所有者的明确约束；不能依赖不同插件析构函数的偶然执行顺序。

## 注册表

同一能力可以有多个命名 Provider。解析过程考虑能力键、名称、版本、Scope 和选择策略。独占能力冲突时直接报错，多 Provider 能力由 Router 或调用者选择。

注册返回幂等 `Registration`。重复撤销不会失败；撤销完成后，新解析看不到该贡献。

## 依赖变化与更新

同名本地替换已有 TUI 替换控件及当前进程常驻 `wagent plugin session` 命令；均先无导入检查配置，再独立批准导入，最后输入精确替换/静止短语，参见[本地替换入口](./plugin-replacement.md#cli-与-tui-入口)。这些控件不会更新其他进程或已安装包。

通过 `PluginManager` 卸载 Provider 时，Manager 会先级联卸载依赖它的活跃 Consumer。直接撤销任意 Provider 注册后的自动卸载、依赖恢复后的自动重新加载为 `Planned`。可选依赖在使用点显式查询，不触发隐式强依赖。

Registry 允许同一 Provider 名称的多个版本并按版本约束解析，也可以创建不可变快照。`PluginManager` 同一时间只允许一个同名活跃插件。当前工作区新增[显式本地替换](./plugin-replacement.md)：预览新实例及受影响消费者，明确确认宿主已停止相关任务，再在生命周期锁内停用与替换。消费者不自动重启，外部副作用不承诺回滚；Run 绑定、自动排空任务与状态迁移仍为 `Planned`。

## 作用域

```text
Application → Workspace → Session → Agent → Run → Step
```

下层 Scope 可以覆盖上层 Provider。当前已经实现作用域解析；自动销毁某个 Scope 及其全部资源为 `Planned`。框架不内置租户；需要额外隔离维度的插件可以扩展 `ScopePath`。

## 失败规则

- 缺失必需依赖：不加载。
- 版本不兼容：不加载并给出冲突链。
- 配置非法：解析阶段失败。
- 部分加载失败：回滚本次 effect scope。
- 清理失败：记录错误并继续清理其他资源，最终报告不完整清理。
- 未知包与插件代码：安装和加载分别要求独立确认；成功安装不会自动导入、注册或授予能力。

## 与工程装配的关系

`CompositionManifest` 引用插件名称、版本约束和配置，而不是直接修改注册表内部状态。导入编码只产生预览；安装和加载仍是单独、需要确认的操作。

## 当前限制

- `PluginManager` 内同名插件不能同时处于活跃状态。
- Registry 快照固定解析结果，但尚未拥有 Provider 生命周期租约。
- 依赖恢复不会自动重新加载 Consumer。
- YAML 只加载严格的 `module:attribute` 引用和配置；包安装使用独立的锁目录和授权协议，不从 YAML 隐式触发。
- CLI `validate-load` 只做短生命周期验证；需要持久进程内插件状态时使用 Python API 或 TUI。
- 当前不在线发现来源、不生成锁文件、不自动升级，也不执行同名插件的静默热迁移。
