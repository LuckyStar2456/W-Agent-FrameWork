# 注解式 Harness 开发

[English](./annotation-development.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

M2 将注解和配置选择编译为 M1 的 `AssemblyPlan`，由同一个 `ApplicationContext` 创建、注入、初始化和关闭对象。本阶段已通过 142 项相关测试；尚未发布，安装 2.0.0 不能使用本文新 API。M3 [应用切面](./application-aspects.md)已通过阶段验收；CLI/TUI 公共装配接线仍属于 M4。

## 从声明到运行

```python
from typing import Annotated
from w_agent import (
    AgentComponent, ApplicationContext, PostConstruct, PreDestroy,
    RepositoryComponent, Value, compile_decorated,
)

@RepositoryComponent("journal")
class Journal:
    def __init__(self):
        self.entries = []
        self.closed = False

    @PreDestroy
    def close(self):
        self.closed = True

@AgentComponent("harness", scope="run")
class MyHarness:
    def __init__(self, journal: Journal,
                 prefix: Annotated[str, Value("model.prefix", required=True)]):
        self.journal, self.prefix = journal, prefix

    @PostConstruct
    def ready(self):
        self.initialized = True

    async def run(self, text):
        result = self.prefix + text.upper()
        self.journal.entries.append(result)
        return result

async def main():
    plan = compile_decorated([Journal, MyHarness], values={"model": {"prefix": "LOCAL:"}})
    async with ApplicationContext(plan) as app:
        async with app.scope("run", "example") as run:
            result = await run.resolve("harness").run("hello")
    return result
```

完整源码示例 [annotated_harness.py](../examples/annotated_harness.py) 还包含自定义模型和配置工厂，可从源码目录运行 `python -m examples.annotated_harness`。它不依赖官方 ReAct、Provider 或 TUI，也不调用外部模型。普通用户组件仍是受信宿主 Python，不因注解而获得沙箱、工具授权或预算强制。

## 扫描和导入边界

`scan_components(module_a, module_b)` 只扫描宿主已经加载的模块对象。不会递归导入包、修改 `sys.path` 或执行组件工厂；传入字符串模块名会失败。组件只从其定义模块收集，重复别名去重，不把导入重导出或未显式装饰的子类当作新组件。也可以直接把类/函数传给 `compile_decorated()`，明确组合跨模块声明。

加载 Python 模块本身会执行模块代码，必须由宿主独立决定。旧 `ParallelASTScanner` 可继续作源码发现工具，但 AST 扫描结果不是导入授权，不自动转换为可执行目标。

## 组件和注入

沿用 `@AgentComponent`、`@ServiceComponent`、`@RepositoryComponent`、`@ControllerComponent` 和 `@ToolComponent`。类默认名为类名小写，支持显式 `name` 和 `scope`；旧 `singleton` 映射 application，`prototype` 必须改为明确的 run/step 生命周期。函数组件是借用的可调用对象，不在启动时当工厂执行；创建对象请用 `@Bean`。

构造器默认按运行时类型匹配，支持具体类及其子类；多个候选报歧义，不按偶然注册顺序选择。无类型参数可按同名组件解析。没有候选时使用普通 Python 默认值；需要配置值时显式使用 `Value`，不从环境变量或文件隐式读取。

- 构造器：`store: Annotated[Store, Qualifier("primary")]`，或 `store: Store = Autowired("primary")`。
- 字段：`store: Store = Autowired("primary")`，或 `store: Annotated[Store, Autowired()]`；无类型字段可写 `store = Autowired("primary")`。
- setter：`@Autowired()` 标记单参数方法，可叠加 `@Qualifier("primary")`；同步/异步均可。
- 配置：构造器或字段使用 `Value("model.limit", default=4)`；setter 使用 `@Value(...)`。`required=True` 表示缺失即失败，默认值不生效。沿用旧 `Value` 的默认 `None`；有严格类型且不允许 None 时，必须提供值或类型正确的默认值。

关键顺序为：创建 → 登记所有权 → 字段/setter 注入 → `PostConstruct`。因此注入失败、初始化失败和取消都会走 M1 清理路径。所有字段/setter 依赖都进入同一依赖图，环和长作用域捕获短作用域同样拒绝。未标记的普通业务字段不参与注入，也不求值其类型字符串。

`from __future__ import annotations` 支持受限类型表达式解析：名称、已加载模块的公开类型、常用容器、Union/Optional/Annotated 及注入标记。不调用 `eval` 或任意注解函数；局部前向类型可传 `types={"Store": Store}`。复杂泛型依赖、任意注解表达式和非运行时协议结构匹配不自动推断，可用显式 `ComponentDefinition`/依赖引用适配。配置值支持常用严格类型及嵌套容器，不自动把字符串转换成数字。

## 配置工厂和生命周期

```python
from w_agent import Bean, Configuration

@Configuration("models")
class Models:
    @Bean(name="model", provides=CustomModel)
    async def model(self):
        return CustomModel()
```

这里的 `CustomModel` 由宿主定义。配置类自身也是托管组件，可注入依赖并声明生命周期；Bean 方法在配置对象初始化后执行，参数使用同样的注入规则。支持模块级 `@Bean` 工厂。返回注解或 `provides` 用于类型匹配和返回值检查，未声明时通过名称引用。不支持配置类静态/classmethod 工厂；可以改用模块级工厂。

工厂产品中声明的 `@PostConstruct`/`@PreDestroy` 会编译为生命周期钩子，也可给 `@Bean` 显式传入 `initialize`/`dispose`，分别替代对应声明钩子。普通 Python 直接调用 `self.model()` 仍会执行工厂，不被魔法代理成容器查询；依赖其他 Bean 应通过方法参数注入，避免自己创建未托管对象。

初始化方法按 `(order, 方法名)` 升序，销毁按逆序；继承遵循 Python 覆盖语义。销毁方法之一失败或取消，仍继续其他销毁方法并聚合错误。新上下文只执行明确标记的钩子，不因方法恰好叫 `close` 或 `post_construct` 而自动调用。工厂返回前内部资源由工厂自行回滚。

## 配置选择与显式装配等价

宿主先用自己的解析器读取 JSON/YAML/TOML，再调用 `compile_configured(document, catalog=...)`。配置只从传入目录选择对象，不接受文件路径/模块字符串作为执行目标，也不进行环境替换。

```python
from w_agent import compile_configured

plan = compile_configured(
    {
        "components": ["journal", "harness"],
        "values": {"model": {"prefix": "LOCAL:"}},
    },
    catalog={"journal": Journal, "harness": MyHarness},
)
```

目录值可以是已声明类、配置类、函数组件、Bean 工厂或显式定义；配置类选择同时包含其 Bean。未知键、重复选择、目录外目标和重复组件身份都拒绝。可用 `arguments={组件名: {构造参数: 值}}` 或 `dependencies={组件名: {构造参数: 组件名}}` 显式覆盖构造绑定，二者不能重叠；不能通过配置替换代码或生命周期钩子。额外复杂参数应由宿主显式定义。

注解与配置入口均先按组件名归一化，再调用 `compile_assembly()`。得到的是普通 `AssemblyPlan`，可交给 `ApplicationContext`，也可将 `.components` 交给 `ApplicationPlugin`。显式 Python 入口保持用户输入次序；比较无依赖组件的启动顺序时也应使用相同排序。三入口共享依赖、作用域、失败回滚及清理规则，不需要另一套执行容器。

## 验收与后续

2026-10-01，在现有隔离 Python 3.11.9 环境完成阶段统一验证：142 passed / 1.73s，其中 M2 新增 41 项、M1 回归 81 项、旧容器/扫描/生命周期回归 20 项。与上一阶段有重叠，不能累加为独立用例数。20 个 Python 文件通过 AST 和内存编译检查。

验收实际执行完整注解示例，以及 Python/注解/配置三入口正常运行和初始化失败的所有权对照；涵盖字段、setter、配置工厂、限定选择、前向类型、无隐式导入、失败/取消清理及公共导出。首次收集发现 Value 缺失顶层导出，修复后全范围重验通过。未跑全量、安装、构建、调用真实外部服务或发布。

复现命令：`python -m pytest tests/test_application_decorators.py tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_scanner.py tests/test_lifecycle.py -q`。

另已提取中英文教程各自首个完整代码块实际执行，两者均返回 `LOCAL:HELLO`；教程本地链接检查通过。相关已跟踪文件 `git diff --check` 无空白错误，仅有 CRLF 提示；未做文档渲染验收。

M2 阶段通过不等于最终目标完成：[M3 应用切面](./application-aspects.md)现已通过阶段验收；仍需 M4 默认模块/CLI/TUI 公共装配，以及 M5 安装包外部目录的开发者验收。H01/H04 已有本地核心链路证据，完整 H01–H08 终验尚未完成。
