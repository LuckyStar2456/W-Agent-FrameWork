# 插件系统

[English](./plugin-system.en.md) | 简体中文

状态：`Planned`。本文定义下一代插件系统，当前 1.5.2 尚未实现这些 API。

## 目标

插件系统让模型、路由、Agent Loop、Workflow、工具、存储、沙箱、界面和评测模块使用同一装配与生命周期机制。内置插件和第三方插件遵循相同规则。

## 接入方式

四种方式统一为 `PluginSpec`：

1. 显式 Python 构造。
2. 装饰器注册。
3. YAML 配置。
4. Python entry point 发现。

显式 Python 构造是行为基准；其他入口不能拥有额外语义。

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

插件可以提供多个能力，但能力键、版本和冲突必须显式声明。配置在加载前完成模式校验。

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

必需依赖消失时，Consumer 先停止接收新工作，再卸载。依赖恢复后，可以重新解析并加载。可选依赖在使用点显式查询，不触发隐式强依赖。

插件更新创建新版本实例。新 Run 使用新解析快照，活跃 Run 保持原快照，直到完成或在支持迁移的静默点显式切换。首版不支持任意执行位置热替换。

## 作用域

```text
Application → Workspace → Session → Agent → Run → Step
```

下层 Scope 可以覆盖上层 Provider。作用域销毁时撤销其全部注册和资源。框架不内置租户；需要额外隔离维度的插件可以扩展 `ScopePath`。

## 失败规则

- 缺失必需依赖：不加载。
- 版本不兼容：不加载并给出冲突链。
- 配置非法：解析阶段失败。
- 部分加载失败：回滚本次 effect scope。
- 清理失败：记录错误并继续清理其他资源，最终报告不完整清理。
- 未知插件代码：只有用户确认安装和首次加载后才执行。

## 与工程装配的关系

`CompositionManifest` 引用插件名称、版本约束和配置，而不是直接修改注册表内部状态。导入编码只产生预览；安装和加载仍是单独、需要确认的操作。
