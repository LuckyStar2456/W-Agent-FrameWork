# 应用装配与生命周期

[English](./application-assembly.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

状态：M1 显式装配、应用/子作用域、插件注册表桥接、旧单例借用和配置预检已实现并通过阶段相关验收；未发布，不属于已发布 2.0.0。本文介绍[Harness 核心基线](./harness-core.md)的显式 Python 入口；M2 [注解与配置编译](./annotation-development.md)也已通过阶段验收，M3 [应用切面](./application-aspects.md)也已通过阶段验收。

## 统一定义

- `ComponentDefinition` 描述工厂、具名依赖、宿主参数、作用域与可选生命周期钩子。运行时创建的实例由创建它的容器作用域管理。
- `BorrowedComponent` 描述宿主/插件已有的实例，不附带初始化或清理授权。外部所有者必须保证实例在声明作用域内有效。
- `ComponentRef` 显式引用另一个定义，不导入模块、不猜测类型、不接触模型服务。
- `compile_assembly()` 返回依赖优先的 `AssemblyPlan`，自身不创建对象或执行钩子；`ApplicationContext` 显式启动后才执行计划和管理实例。

```python
from w_agent import (
    BorrowedComponent, ComponentDefinition, ComponentRef, compile_assembly,
)

class CustomHarness:
    def __init__(self, store, vendor_options):
        self.store = store
        self.vendor_options = vendor_options

host_store = {}
plan = compile_assembly([
    ComponentDefinition(
        "my-harness",
        CustomHarness,
        dependencies={"store": ComponentRef("store")},
        arguments={"vendor_options": {"custom_mode": "developer-defined"}},
    ),
    BorrowedComponent("store", host_store),
])
# plan.startup_order 的预期值为 ("store", "my-harness")。
# 此处没有创建或运行 CustomHarness；示例尚未执行验收。
```

新参数不必映射到 OpenAI 字段。参数映射的结构复制为只读视图，但值仍为宿主对象，不承诺深冻结、序列化或跨进程分享。对象值、工厂和生命周期钩子不出现在默认定义 repr 中；组件名称和依赖名称仍可见，不应包含密钥。

## 计划校验

当前拒绝重复名称、缺失依赖、依赖环、依赖与显式参数冲突、非法参数名、未声明作用域，以及长生命周期对象直接依赖更短生命周期对象。默认采用既有六级作用域顺序；可通过 `scope_order` 显式声明自定义层级，不能反转内置层级。计划不是权限凭证，也不代表实例实际生命周期已受管理。

拓扑排序使用非递归算法。同层无依赖组件以输入顺序入队，消费者在其所有依赖就绪后入队。不承诺不同输入排列具有相同启动顺序；注解/配置适配器后续必须采用同一规范化顺序。直接构造 `AssemblyPlan` 也校验依赖顺序，不能据此绕过检查。

编译器不执行组件工厂和钩子，不动态导入模块。输入是受信 Python 对象；自定义迭代器/Mapping 本身可能执行宿主代码，所以这不是不可信配置的安全解析器。

## 待完成与验证边界

M1 的实现范围已收齐，阶段验收结果见下文。M2 已完成[注解、配置和类型/限定注入](./annotation-development.md)到这些定义的编译，剩余 M4–M5 按核心基线继续。直接使用 `ComponentDefinition` 时不自动扫描 `@PostConstruct` / `@PreDestroy`，生命周期钩子需显式提供；使用 M2 编译器时会生成对应钩子。旧容器中的既有钩子仍由旧容器执行。

2026-10-01，现有隔离 Python 3.11.9 环境完成 M1 阶段验证：137 passed / 1.72s，其中计划 15、上下文 32、配置 13、旧容器适配 5、插件桥接 16，共 81 项；相邻容器/注册表/插件生命周期与替换回归 56 项。此前 47 项包含在其中，不重复相加。14 个 Python 文件通过 AST 和内存编译检查；相关已跟踪文件 `git diff --check` 无空白错误，仅有 CRLF 提示。

测试实际运行自定义 Harness 示例，以及旧单例 → 注册表 → 自定义 Harness → Run 清理的组合用例；覆盖初始化失败、重复取消、单一清理所有权、导出冲突回滚和跨管理器误用。未做全量测试、安装包/仓库外验收、安装、构建、真实外部调用或发布。用户规则现为完成完整阶段后自动运行该阶段相关验证，阶段中途不运行测试；安装、构建、外部调用和发布仍需另行授权。

复现范围：`python -m pytest tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_kernel_registry.py tests/test_kernel_plugins.py tests/test_plugin_cancellation.py tests/test_plugin_replacement.py -q`。

## 插件和能力注册表

`ApplicationPlugin` 实现现有插件协议，通过 `PluginManager.load()` 加载，不创建第二个管理器或注册表。`CapabilityImport("store", CapabilityRequirement("storage"))` 将能力按名称、版本和可见路径解析成借用组件；`CapabilityExport("harness", CapabilityDeclaration("harness"))` 发布同一个应用实例。目前只导出 application 作用域实例，避免注册表留下已关闭的 run 对象。

```python
from w_agent import (
    ApplicationPlugin, CapabilityDeclaration, CapabilityExport,
    ComponentDefinition, PluginManager, ScopePath,
)

async def plugin_example():
    manager = PluginManager()
    module = ApplicationPlugin(
        name="custom", version="1",
        components=[ComponentDefinition("service", lambda: {"custom": True})],
        exports=[CapabilityExport("service", CapabilityDeclaration("custom-service"))],
    )
    try:
        await manager.load(module)
        assert manager.registry.resolve("custom-service", ScopePath.application()) is module.application.resolve("service")
    finally:
        await manager.close()
```

插件效果作用域整体拥有上下文；上下文拥有工厂结果；撤销注册只移除查找能力，不销毁对象。先停用依赖消费者，再撤销导出和释放应用。依赖级联复用已有管理器按 capability 的保守规则，不承诺按版本精确最小卸载。非插件直接注册的对象仍由宿主管理。

同一个桥接实例只能成功进入加载一次，重载使用新实例。宿主须在卸载前停止已有任务/流；取得的裸对象引用不是可撤销租约。`scope` 控制注册表可见路径，内部应用根以插件名命名，不冒充外部路径对应的生命周期。插件 `config` 非空会被拒绝：先在受信 Python 中生成带参数的定义，不能静默忽略配置。

## 旧容器兼容

`BeanFactory.existing_singleton(name)` 只读取已创建的单例，不创建对象或返回早期引用。`borrow_legacy_singletons(factory, {"store": "legacy-store"})` 返回借用定义，可以直接传给 `compile_assembly()` 或 `ApplicationPlugin`。

宿主先完成旧容器初始化，再构造借用定义；关闭所有新应用后才调用旧容器销毁。该适配不接管整个 BeanFactory，不复制其缓存，不重复调用旧生命周期钩子。尚未创建的单例和 prototype 不能借用；宿主也不得提前销毁旧对象。旧容器启动失败和清理失败语义没有升级为新上下文保证；要获得新保证，应迁移为显式工厂定义。这是基础 1.x 兼容边界，不是第二套托管容器。

## 配置预检

`ComponentDefinition(..., validate_arguments=validator)` 在整个应用的工厂签名检查之后、任何工厂执行之前校验参数，包括尚未打开的子作用域。校验器接收只读参数映射，同步返回 `None` 或抛错；不负责依赖对象的类型注入。校验器是受信宿主代码，内部可变对象不会深冻结；不可执行资源创建等副作用。

内置 `ConfigurationSchema({"count": ConfigurationField(int)})` 提供必填、严格类型和未知字段检查；`required=False` 允许省略，`allow_extra=True` 允许额外字段。严格类型区分 `bool` 与 `int`，不自动转换或填默认值。嵌套结构、范围、子类或厂商专用参数可以使用自己的校验器。错误只报告组件身份，不输出参数值或自定义校验异常正文；身份名称不要包含凭据。配置文件选择、默认值绑定和注解等价编译归 M2。

## 显式应用入口

`ApplicationContext(plan)` 构造时不创建组件；`await start()` 或 `async with` 才启动。启动前对整个计划做工厂/钩子签名校验，不能检查签名的宿主 callable 需包装成明确的 Python 工厂。进入上下文后用同步 `resolve(name)` 取得已初始化实例，解析本身不懒加载或授予权限。

```python
from w_agent import ApplicationContext

# 延续上面的 plan；在自己的异步入口中调用 run_application()。
async def run_application():
    async with ApplicationContext(plan) as app:
        harness = app.resolve("my-harness")
        assert harness.store is host_store
```

可运行的完整源码示例见 [custom_harness.py](../examples/custom_harness.py)：自定义模型的 `compose(..., dialect=...)`、普通 Python 工具、自定义 Harness 和内存 Journal 全部经公开 API 装配，不使用默认 ReAct。它没有真实模型请求、文件写入或 shell；普通工具仍是受信代码，不因容器管理而获得沙箱或审批能力。源码用户可运行 `python -m examples.custom_harness`；已发布 2.0.0 不包含新 API，不能据此声称该包支持此示例。

## 子作用域与清理规则

- 应用启动只创建 application 组件。`async with app.scope("run", "r1") as run:` 创建 run 组件；同作用域复用实例，兄弟作用域各自创建，祖先实例共享。
- 子作用域须由活跃父作用域创建，层级必须缩短生命周期。可跳过不需要的层级；如果组件依赖 session，则必须实际打开 session 祖先，不能只给 run 一个路径名称。
- 工厂返回后先记录清理责任，再调用初始化钩子。同步和异步工厂/钩子均支持；创建成功但初始化失败的实例仍会清理。
- 借用实例没有清理钩子，也不探测 `close()`。不同工厂不允许返回同一个已托管/借用实例，避免重复所有权；共享常量或宿主对象应使用借用定义或依赖引用。
- 关闭先停止新的解析/子作用域操作，再关闭所有子作用域，随后依赖逆序释放当前实例。重复或并发关闭共享同一结果；清理失败也不重试释放同一对象。
- 取消启动会关闭该作用域，包括取消与成功启动竞争的情况。取消一个并发启动等待者会取消整个共享启动，不是只取消该等待者。清理等待不被重复取消截断；清理失败与主异常同时保留在异常组中。
- 工厂/生命周期钩子不得启动或关闭同一上下文树，避免重入死锁。上下文限定一个 asyncio 事件循环。关闭或失败的实例不能重启；需要新建上下文。
- [M3 应用切面](./application-aspects.md)已托管匹配代理的方法调用和流，作用域关闭先收尾这些工作。未匹配方法及宿主自行启动的任务/流仍由宿主等待和关闭；不可返回的工厂/清理钩子可能阻塞关闭。默认模块和前端执行接线仍属于 M4。
