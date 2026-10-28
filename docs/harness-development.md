# 开发自己的 Harness

[English](./harness-development.en.md) | 简体中文

本教程对应 2.1.0 框架核心，不适用于此前 2.0.0 API。Python 3.11+；安装 `python -m pip install "wagent-framework==2.1.0"`，需要 TUI 时使用 `python -m pip install "wagent-framework[tui]==2.1.0"`。以下示例无网络、无 API Key、无真实模型调用，不执行生成代码。版本范围与验收见[发布说明](./releases/2.1.0.md)和[核心终验](./harness-acceptance.md)。

## 统一开发路径

声明普通 Python 组件 → 编译 `AssemblyPlan` → 定义 `ApplicationProject` 的公开操作 → 在 `project.open()` 中调用。容器管理依赖、作用域、初始化和清理；Harness 自己决定执行算法。显式定义、注解与允许目录中的配置都编译到同一计划，不存在三套容器。

三种方式可以混用。`compile_assembly` 适合完全控制工厂；`compile_decorated` 适合类型注入与生命周期注解；`compile_configured` 只选择宿主已经导入的定义，不自动导入配置里的 Python 路径。`scan_components` 只扫描明确传入的已加载模块，不递归导入目录。

## 1. 显式装配：自定义模型、工具与存储

完整源码：[custom_harness.py](../examples/custom_harness.py)，输入：[custom_harness_call.json](../examples/custom_harness_call.json)。在仓库根目录运行：

```bash
python -m examples.custom_harness
python -m w_agent.cli application run --entry examples.custom_harness:create_project --input-file examples/custom_harness_call.json --confirm-code
```

Python 示例返回 `LOCAL:HELLO`、含相同结果的日志和已关闭标记；CLI 输出 `{"result": "LOCAL:HELLO"}`。

`CustomModel.compose(question, *, dialect)` 是用户协议，不转换为 OpenAI 请求。普通工具负责规范化文本，`MemoryJournal` 保存结果，Run 作用域的 `CustomHarness` 协调它们。`ComponentDefinition.dependencies` 显式声明连接，`dispose` 指定清理，不要求继承框架 Agent。换模型参数时，修改自己的接口和消费组件；不需要改框架源码。

替换实现可在启动前用 `replace_components(plan, replacements)` 保留原名字并重新校验依赖。自建的新图直接交给 `compile_assembly`；替换不会自动删除不用的默认组件，也不是活跃对象热替换。宿主已有资源用 `BorrowedComponent`，关闭责任保留给宿主。

## 2. 注解式客服：扫描、DI、AOP 与生命周期

完整源码：[support_harness.py](../examples/support_harness.py)，输入：[support_harness_call.json](../examples/support_harness_call.json)。

```bash
python -m examples.support_harness
python -m w_agent.cli application run --entry examples.support_harness:create_project --input-file examples/support_harness_call.json --confirm-code
```

客服模块声明模型、FAQ 工具、日志仓库与 Harness，通过构造器类型注入。`Value("support.tone", required=True)` 从装配值绑定 `Friendly`。`@PostConstruct` 在依赖就绪后初始化；`@PreDestroy` 在所属作用域关闭时清理。`@Aspect` 的 Before/Finally 只记录公开 `answer` 调用，不改变业务授权。

运输问题的输出字段为：`answer="Friendly: Demo orders ship within two working days."`、`source="local-faq"`、`handoff=false`。未知问题返回转人工，不伪造 FAQ 答案。完整示例的生命周期顺序是：

```text
store-open → harness-ready → reply-saved → harness-closed → store-closed
```

切面记录 `before:answer`、`finally:success`。扩展业务时替换 FAQ 或模型组件即可；实际模型需要独立授权、凭据与自己的预算边界。这是框架开发模板，不是生产客服质量评估。

## 3. 配置式编码：Bean 工厂与明确批准

完整源码：[coding_harness.py](../examples/coding_harness.py)、配置：[coding_project.json](../examples/coding_project.json)、输入：[coding_harness_call.json](../examples/coding_harness_call.json)。配置只引用代码里允许的 `models/workspace/tool/harness/trace` 目录键。

```bash
python -m examples.coding_harness
python -m w_agent.cli application run --entry examples.coding_harness:create_project --input-file examples/coding_harness_call.json --confirm-code
```

`@Configuration`/`@Bean` 创建模型；`PatchProposal` 保留 path/before/after 和内容摘要。CLI 默认只运行 `preview`，返回预览与 digest。完整 Python 示例在同一 Host 中预览后，显式将摘要交给 `apply`，结果内存内容为 `greeting = 'framework'\nprint(greeting)\n`，修订数为 1，退出后仓库关闭。

`PatchTool.apply` 自身检查摘要与原内容是否匹配；删掉追踪切面不会取消检查。空摘要、变更后的预览或过期原文不能写入。该摘要检查用于绑定批准的内容，并不是认证系统；真实应用必须从可信的人机交互取得批准，不能让模型自批。示例只修改内存字典，**不写项目文件、不运行生成代码**。

两个独立 CLI 调用各自创建新 Host，不共享内存；需要持久状态时替换仓库组件，并设计批准身份、并发控制、沙箱和恢复协议。不要把此演示当作完整代码执行沙箱。

## Python、CLI、TUI 是同一项目的入口

Python 使用 `async with create_project().open() as host` 与 `await host.invoke(operation, ...)`；Python 参数和返回值保留自己的类型。流操作必须声明 `ApplicationOperation(..., kind="stream")`，用 `host.consume` 消费，资源寿命覆盖消费期。

CLI 使用 `application run --entry module:create_project --input-file call.json --confirm-code`。JSON 只承载 `operation`、`args`、`kwargs`；不能自动序列化任意 Python 对象。TUI 启动 `python -m w_agent.cli tui`，进入 Application 页，填写相同入口与输入文件，输入一次性确认 `RUN APPLICATION` 后执行；取消会等待该调用清理。界面展示能力不等于任意对象序列化协议。

`--confirm-code` 和 TUI 确认允许导入受信 Python 项目，**不是隔离、工具权限或逐次副作用批准**。模块顶层/工厂可执行任意宿主代码，须审阅后加载；工厂返回项目之前创建的资源由工厂负责。容器不会管理业务私自启动的后台任务，也不能强行中断不协作的同步代码。

## 安装制品与仓库外运行

wheel 只包含库；匹配源码/sdist 提供示例。将三份 `*_harness.py`、三份 `*_harness_call.json` 和 `coding_project.json` 复制到新的工作目录。使用安装了候选 wheel 的隔离环境，不设置指向仓库的 `PYTHONPATH`，在新目录执行：

```bash
python custom_harness.py
python support_harness.py
python coding_harness.py
python -m w_agent.cli application run --entry support_harness:create_project --input-file support_harness_call.json --confirm-code
```

此时入口去掉 `examples.` 前缀；TUI 同理。可复制[独立验收脚本](../tests/acceptance/harness_delivery.py)到同目录运行 `python harness_delivery.py`：检查包实际来自隔离环境，并对三项目分别执行 Python、CLI 和无显示 TUI。它需要 `tui` extra，不访问模型或外部服务。构建/安装命令不隐含授权；M5 离线验收与后续 2.1.0 发布分别获得授权。

## 所有权、兼容和保留边界

工厂创建的对象由所在作用域清理，借用对象不自动清理；初始化失败仍回滚已创建对象。自定义作用域需声明顺序，插件桥接也可传 `scope_order`，长生命周期不能捕获短生命周期对象。Host 每次调用创建目标所需的子作用域链，持久 Session 作用域需直接管理 `ApplicationContext`，不能假定两次 invoke 共用它。

默认 ReAct/Workflow 只是可选装配，见[默认装配](./default-assembly.md)。旧 BeanFactory、ProxyFactory 与手动 Runtime 不自动升级，见[迁移说明](./migration-1x.md)。多 Agent、分布式 Workflow、远程沙箱、插件市场、高级热迁移、延迟依赖引用与任意 Python 栈恢复均不属于本次完成条件；后续计划保持在[路线图](./roadmap.md)。
