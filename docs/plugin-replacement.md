# 显式本地插件替换

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

简体中文 | [English](./plugin-replacement.en.md)

状态：`Experimental`，已随 2.0.0 发布；离线生命周期验证范围见[定向记录](./acceptance-2026-10-01-followup.md)，不代表任意第三方插件均已验收。

`PluginManager.plan_replacement()` 与 `replace()` 用于替换**已经构造、由宿主信任的同名 Python 插件**。模型、路由、工作流、工具等能力复用同一生命周期。它不会安装包、导入模块、授权未知代码或热重载 Python 模块缓存。

```python
plan = await manager.plan_replacement(next_plugin)
print(plan.previous.version, plan.replacement.version, plan.unload_order)
# 宿主停止接收新 Run，等待现有 Run 结束，并停止使用旧 Registry 快照。
# 应用或用户审核并批准这一份精确预览后再执行。
handle = await manager.replace(
    plan,
    expected_plan_id=plan.plan_id,
    host_quiescent=True,
    config={"mode": "local"},
)
```

## 契约

- 预览不执行插件 setup/unload，展示新旧 `PluginSpec`（含提供与依赖能力）以及消费者优先的卸载顺序。原插件必须活跃，新插件必须同名且为新实例。允许明确选择的同版本替换或降级。
- 预检模拟移除受影响所有者之后的注册表，检查内核 API、必要依赖、声明的注册项和冲突，也检查保留插件的反向冲突；无法预先验证未声明的 setup 行为。
- 依赖影响沿用现有保守卸载策略：对声明能力的硬依赖均计入，即使还有其他 Provider 可满足。可选依赖不自动跟踪。
- 计划只在当前进程、当前管理器中有效，绑定返回的精确对象；仅最后一份预览可执行。计划 ID 是审批关联标记，**不是包或代码摘要，也不是对可信 Python 代码的安全边界**。配置由宿主执行时显式传入，不属于预览。
- 执行持有管理器生命周期锁；停用前若插件记录、spec 身份或注册表贡献变化则拒绝。宿主不得同时修改对象、注册表或配置；这不是跨线程/进程租约，也不能防御恶意插件。
- `host_quiescent=True` 是宿主声明，不会自动排空任务。当前 Registry 快照与 Run 没有生命周期租约；宿主必须停止接收新任务，等待使用者结束，确保旧 Provider 引用不再使用。
- 先停止消费者，再停止旧 Provider；替换成功后消费者**仍为停止状态**，由宿主显式构造/重载兼容消费者。无关插件保持活跃。
- 句柄绑定原始记录；旧句柄显示旧实例状态，不能误卸载新实例。

## 失败与恢复

计划在开始停用前被消耗。清理失败时立即停止，绝不执行新插件 setup；此前部分消费者可能已经停止，而旧 Provider 可能仍活跃或已停止。手工恢复前应查看 `manager.records()` 和 `error`。新 setup 失败会清理其登记效果，将记录标为 `FAILED`，不会静默重启旧组件。setup 被取消时也会尝试清理并传播取消异常；停用阶段被取消可能留下中间生命周期状态，须由宿主检查。重复取消与外部副作用无法事务回滚。

自动回滚、消费者重建、状态迁移、超时/强制清理、在线来源发现、锁生成、包升级、导入缓存修改、持久替换审计、Run 绑定迁移均保留为待实现。已安装包升级仍需独立安装与加载审批，可能必须使用新进程，参见[插件系统](./plugin-system.md)。

## CLI 与 TUI 入口

当前工作区新增共享复核控制器 `PluginReplacementSession`，使用单条引用 YAML：

```yaml
plugins:
  - entry: my_plugins.next_router:setup
    config:
      mode: local
```

文件必须恰有一个启用引用。检查读取上限为 1 MiB，仅展示配置键，并将后续动作绑定到原始字节的 SHA-256。这是**配置摘要，不是 Python 源码/制品摘要**，导入对象仍是开发者可信代码。代码变更、签名、安装仍是独立责任。

打开真正的当前进程插件会话：

```text
wagent plugin session --config .wagent/plugins.yml --confirm-plugin-code
plugin-session: status
plugin-session: inspect .wagent/replacement.yml
plugin-session: prepare
Exact IMPORT REPLACEMENT confirmation: IMPORT REPLACEMENT <source_digest>
plugin-session: replace
Exact REPLACE confirmation: REPLACE <plan_id>
Exact QUIESCENT confirmation: QUIESCENT <plan_id>
plugin-session: status
plugin-session: exit
```

启动代码授权只加载初始 YAML。准备新版本需要独立的精确导入短语；执行需要精确计划绑定的替换与静止短语。插件在多次命令间持续活跃，直到 `exit`、EOF 或中断关闭会话；`cancel` 丢弃待执行复核。命令**不会**更新其他进程、持久修改工程插件选择或升级已安装包。它是本地活跃管理器，不是跨进程控制接口。配置值及任意插件异常文本不会被输出。

TUI **Plugins** 页复用现有常驻管理器：检查替换 → 授权导入并准备 → 输入 `REPLACE` 与 `QUIESCENT` 执行 → 刷新生命周期。路径或 YAML 内容变化必须重新复核；执行尝试即消耗复核，即使被拒绝也如此。取消复核会释放保留候选对象，但不能撤销 Python 导入副作用、终止已运行插件代码或反加载模块。

TUI 在已知 Agent、Workflow、链路或评测任务活跃时拒绝替换；涉及已安装插件批次时也拒绝，因为其导入路径租约需要独立的新进程处理。界面忙碌检查只涵盖已知操作，插件自建后台使用者和外部引用仍需宿主明确保证静止；没有增加强制租约/任务排空或沙箱保证。

`PluginManager.discard_replacement(plan)` 仅丢弃精确保留的计划，不会撤销更新的预览；控制器取消通过它释放待执行对象。Python 嵌入可从 `w_agent.plugin_replacement_session` 导入 `PluginReplacementSession`。

## 验收

`tests/test_plugin_replacement.py` 覆盖预览/审批、一次性与过期计划、注册表/spec 漂移、消费者顺序、依赖缺失、API 不兼容、反向冲突、清理/setup 失败、取消、旧句柄安全及显式配置传递。这是实际本地管理器/注册表测试，不代表外部包升级或生产并发验收。

CLI/TUI 入口本轮独立运行新增 `tests/test_plugin_replacement_session.py` 15 项，以及原替换 17 项、生命周期 7 项：隔离 Python 3.11 环境 **39 passed**；现有 CLI、TUI 与包安装相关回归另有 **61 passed**，相关 compileall 和 diff 检查也通过。这是本轮相关验收证据，不借用上一轮全量结果；外部包升级和生产并发仍未验收。
