# 插件系统

[English](./plugin-system.en.md) | 简体中文

状态：`Implemented`（`2.0.0a1`）。本文定义当前微内核插件 API；模型、Agent 和 Workflow 等上层插件仍按路线图实现。

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

通过 `PluginManager` 卸载 Provider 时，Manager 会先级联卸载依赖它的活跃 Consumer。直接撤销任意 Provider 注册后的自动卸载、依赖恢复后的自动重新加载为 `Planned`。可选依赖在使用点显式查询，不触发隐式强依赖。

Registry 允许同一 Provider 名称的多个版本并按版本约束解析，也可以创建不可变快照。当前 `PluginManager` 同一时间只允许一个同名活跃插件；协调版本替换、Run 绑定和静默点迁移为 `Planned`。

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
- 未知插件代码：只有用户确认安装和首次加载后才执行。

## 与工程装配的关系

`CompositionManifest` 引用插件名称、版本约束和配置，而不是直接修改注册表内部状态。导入编码只产生预览；安装和加载仍是单独、需要确认的操作。

## 当前限制

- `PluginManager` 内同名插件不能同时处于活跃状态。
- Registry 快照固定解析结果，但尚未拥有 Provider 生命周期租约。
- 依赖恢复不会自动重新加载 Consumer。
- YAML 只加载 `module:attribute` 引用和配置，不安装第三方包。
