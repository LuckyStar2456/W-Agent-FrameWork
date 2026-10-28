# 应用切面与流生命周期

[English](./application-aspects.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

M3 将切面编译进 `AssemblyPlan`，由 `ApplicationContext` 对匹配组件织入，复用已有依赖和销毁规则。同步、异步、同步流和异步流分别执行，流的切面覆盖实际消费过程。阶段相关验收 207 项通过；尚未发布，不属于安装版 2.0.0。

## 声明一个独立切面

```python
from w_agent import (
    ApplicationContext, Aspect, Before, Finally, ServiceComponent,
    compile_decorated,
)

@Aspect("trace", component="harness", methods=("run",))
class Trace:
    def __init__(self):
        self.events = []

    @Before
    def before(self, invocation):
        self.events.append("start:" + invocation.method)

    @Finally
    def finished(self, invocation, outcome):
        self.events.append(outcome.status)

@ServiceComponent("harness")
class Harness:
    async def run(self, text):
        return text.upper()

async def main():
    async with ApplicationContext(compile_decorated([Harness, Trace])) as app:
        result = await app.resolve("harness").run("hello")
        events = app.resolve("trace").events
    return result, events
```

业务方法不需要加入追踪代码。完整流式示例见 [aspected_harness.py](../examples/aspected_harness.py)，源码运行入口为 `python -m examples.aspected_harness`。不会请求真实模型、启动服务或安装依赖。

## 切点和顺序

`MethodPointcut(component="harness*", methods=("run", "stream"), tags=frozenset({"metered"}))` 按组件名和方法 glob 匹配，并要求目标定义包含全部标签。`ComponentDefinition(..., tags=...)` 和类组件装饰器的 `tags` 提供标签。仅匹配公开可调用属性及显式可调用对象的 `__call__`；不执行 property 来寻找方法，不依赖 ReAct 私有方法名。

`order` 较小的切面在外层，同 order 按切面名称排序；退出按调用栈逆序。`app.aspect_matches` 或子作用域同名属性返回 `AspectMatch(component, method, kind, aspects)`，不包含调用参数。它是已启动作用域的实际匹配结果，不宣称未打开作用域也完成织入；未匹配的切面不会凭空调用。

切面类本身是托管组件，支持 M2 依赖注入和生命周期。引用切面组件的目标在它之后创建、之前销毁；依赖环与长作用域捕获短切面仍会拒绝。切面依赖按组件匹配保守建图，方法是否存在在启动时确认。所有作为 AdviceRef 来源的组件都排除自动织入，避免递归代理基础设施。

## 通知契约

| 声明 | 签名 | 行为 |
|---|---|---|
| `@Before` | `(invocation)` | 进入该层时执行；失败不运行更深业务，但仍执行本层 Finally |
| `@Around` | `(invocation, proceed)` | 可短路或调用下一层一次；返回值/流可变换，不隐式重试 |
| `@After` | `(invocation, result)` | 成功返回后执行；流仅在正常耗尽后执行，result 为 None；返回值忽略 |
| `@OnError` | `(invocation, error)` | 观察异常/取消，不通过返回值吞掉异常 |
| `@Finally` | `(invocation, outcome)` | 对已进入的层做最终清理，状态为 success/error/cancelled/closed |

每个切面类每种通知角色声明一个方法；需要更多处理时拆成独立有序切面。`Invocation` 提供组件、方法、kind、args 和只读 kwargs 映射；容器不深复制任意业务对象。`InvocationOutcome` 包含结果或原始异常，但默认 repr 不打印它们。通知可以读取敏感业务值，日志脱敏仍由宿主负责。

同步方法要求同步通知，保持普通同步返回；不会调用 `asyncio.run()`。异步方法支持同步/异步通知。`proceed()` 单次且只在对应通知内有效；异步通知必须完整 await，不得交给另一任务逃逸。Around 可处理业务异常；调用者/作用域发起的取消仍需收尾并传播。主要异常和清理异常同时存在时以异常组保留，不以清理错误覆盖业务错误。

## 流和作用域关闭

自动识别协程、同步生成器和异步生成器；普通方法返回 awaitable/迭代器时，可显式设置 `kind="async"`、`"stream"` 或 `"sync_stream"`，多个切面不能声明冲突 kind。

流式 Around 应写成同步/异步生成器，在 `for`/`async for item in proceed()` 中转换和产生数据。其代码寿命才能覆盖消费；普通 async 函数中仅“返回迭代器”的 finally 仍按 Python 语义在函数返回时执行。框架的 Before/After/OnError/Finally 则始终围绕实际消费。

流首次消费才启动。正常耗尽、异常、取消、`close()`/`aclose()` 和作用域关闭均收尾；Around 提前截断流也关闭下游。并发消费同一异步流会拒绝，重复关闭共享一次清理。未消费就关闭的流不会启动业务或通知。可使用 `with stream` / `async with stream`，提前 break 不应依赖垃圾回收，应显式关闭或等所属作用域关闭。

作用域停止新外部调用后，取消并等待其托管异步调用，关闭流，再释放业务组件和切面。消费者销毁钩子仍可 await 尚未销毁的依赖方法。重复取消不能截断登记的清理；不返回的同步代码、拒绝合作的异步代码或永久挂起的清理仍可能阻塞关闭，框架不强行终止 Python 线程。

只有经过匹配代理的方法、其托管调用和流纳入这套边界。宿主自行启动的未登记任务、对象自调用、未匹配方法、特殊运算符不被自动监督。目标生命周期在原对象上执行，暴露的是委托视图；不承诺 `type(proxy) is type(original)`、原始对象身份或完整透明代理。借用对象不改写方法、不转移销毁权。切面不是隔离、强制预算或权限安全边界。

## 显式代码和配置选择

显式入口使用 `compile_assembly(components, aspects=[AspectDefinition(...)])`；通知可直接给 callable，或用 `AdviceRef("trace", "before")` 引用同计划组件。`compile_decorated(..., aspects=...)` 也接受显式声明。配置入口从宿主目录选择 `@Aspect` 类或 `AspectDefinition`，不会导入未知模块；三入口使用同一计划。

通过插件加载时传 `ApplicationPlugin(..., components=plan.components, aspects=plan.aspects)`，不要只复制组件而丢弃切面。导出的是织入后的同一对象视图，跨插件再借用不转移原始资源所有权。

旧 `AspectJPointcut`、`ProxyFactory` 和 `BeforeAdvice`/`AroundAdvice`/`AfterAdvice` 保持原路径和旧行为；不会静默转换成新语义。新应用应使用上述组件切面接口。旧代理的内部实现、事件总线与新上下文托管调用不是同一执行入口。

## 验收和剩余工作

25 个 Python 文件通过 AST/内存编译检查。中英教程首个完整代码块均已实际执行，返回 `("HELLO", ["start:run", "success"])`；本地链接检查通过。未做文档渲染验收。

2026-10-01，现有隔离 Python 3.11.9 环境完成阶段相关验证：207 passed / 1.99s。其中 M3 新增 34 项，M1/M2 和相邻兼容回归 173 项；与历史阶段重叠，不累加为独立用例。覆盖三入口切面等价、同步/异步、异常/重复取消、流退出路径、跨插件借用、匹配诊断、子作用域使用、关闭顺序与自关闭死锁防护。

命令：`python -m pytest tests/test_application_aspects.py tests/test_application_decorators.py tests/test_application_planning.py tests/test_application_context.py tests/test_application_configuration.py tests/test_application_legacy.py tests/test_application_plugins.py tests/test_container.py tests/test_scanner.py tests/test_lifecycle.py tests/test_aop.py tests/test_kernel_plugins.py tests/test_plugin_cancellation.py -q`。

未跑全量。M4 默认模块及 CLI/TUI 公共装配、M5 安装包外部目录验收仍未完成。未安装、构建、调用外部服务或发布；M3 通过不等于最终 H01–H08 全部验收。
