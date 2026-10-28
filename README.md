# W-Agent

**借鉴 Spring 的依赖注入、切面和生命周期，为 Python 开发者装配自己的 Agent 执行系统。**

[English](./README_EN.md) · [文档](./docs/README.md) · [快速入门](#快速入门) · [扩展开发](./docs/developer.md) · [路线图](./docs/roadmap.md)

[![PyPI](https://img.shields.io/pypi/v/wagent-framework)](https://pypi.org/project/wagent-framework/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](./setup.py)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](./LICENSE)

W-Agent 是面向 Python 开发者的开源 **Harness 开发框架**。这里的 Harness 指组织模型调用、工具、状态与执行流程的代码。你可以用注解、配置或显式 Python 装配自己的实现，也可以按需采用内置 ReAct、Workflow 和 CLI/TUI。

当一个小应用开始需要替换模型、统一记录调用结果、管理共享客户端的初始化与释放时，这些代码很容易散落在业务函数里。W-Agent 将装配、日志切面和生命周期交给容器，让业务方法专注于执行流程。下面用一个客服回复应用展示这些变化。

**首次试用请安装 `wagent-framework==2.1.0`，Python 导入名为 `w_agent`。本页完整示例对应这个正式版。**

## 安装

需要 **Python 3.11+**。建议在项目自己的虚拟环境中安装。以下命令固定到正式版 2.1.0：

```bash
python -m pip install "wagent-framework==2.1.0"
```

| 你要使用的内容 | 版本与来源 |
|---|---|
| 本页示例与 Harness 开发核心 | [PyPI 2.1.0](https://pypi.org/project/wagent-framework/2.1.0/) · [版本说明](./docs/releases/2.1.0.md) |
| 已有 1.x / 2.0.0 项目 | 先看 [1.x 迁移](./docs/migration-1x.md)或 [2.0.0 基础组件教程](./docs/basic-development.md)，再核对 API 差异 |
| GitHub 源码开发 | `main` 可能包含未发布改动；需要复现发行版时，使用 PyPI 对应版本的源码包（sdist） |

安装版本和下载制品以 PyPI 为准，变更范围见仓库内的版本说明；GitHub Releases 是否有条目不作为 Python 包是否已发布的判断依据。从源码执行 `python -m pip install -e .` 会使用当前检出的代码，不会自动切换到 PyPI 2.1.0。

按需添加依赖，不必安装所有模块：

```bash
# HTTP 模型接入与终端界面
python -m pip install "wagent-framework[models,tui]==2.1.0"

# PDF / DOCX / XLSX / PPTX 解析
python -m pip install "wagent-framework[knowledge-documents]==2.1.0"
```

其他 extras 包括 `mcp`、`media-preview`、`testing`、`fastapi`、`langchain`、`opentelemetry` 和平台受限的 `wasm`。参见[安装指南](./docs/guide.md)。

## 快速入门

### 从手动管理到容器装配

假设你已有一个提供 `open()`、`answer()` 和 `close()` 的模型适配器。手动编排时，调用处需要同时处理业务、日志和资源释放：

```python
# 对照片段：model 是调用方已创建的适配器实例。
async def reply_manually(model, question):
    model.open()
    try:
        print("call:run")
        answer = await model.answer(question)
        print("result:success")
        return answer
    finally:
        model.close()
```

使用 W-Agent 后，这三项职责分别放到业务组件、日志切面和生命周期方法中。保存下面的完整示例为 `support_app.py`，执行 `python support_app.py`。只需上方的基础安装，**不需要 API Key、网络服务或 TUI**：

```python
import asyncio

from w_agent import (
    AgentComponent, ApplicationOperation, ApplicationProject, Aspect,
    Before, Finally, PostConstruct, PreDestroy, ServiceComponent,
    compile_decorated,
)


class ReplyModel:
    async def answer(self, question: str) -> str:
        raise NotImplementedError


@ServiceComponent("model")
class OfflineModel(ReplyModel):
    """Deterministic stand-in; no real LLM request."""

    @PostConstruct
    def open(self):
        print("model:open")

    async def answer(self, question: str) -> str:
        if "shipping" in question.casefold():
            return "Demo orders ship within two working days."
        return "Please contact a human teammate."

    @PreDestroy
    def close(self):
        print("model:close")


@AgentComponent("support", scope="run")
class SupportHarness:
    def __init__(self, model: ReplyModel):
        self.model = model

    async def run(self, question: str) -> str:
        return await self.model.answer(question)


@Aspect("trace", component="support", methods=("run",))
class CallLog:
    @Before
    def started(self, invocation):
        print(f"call:{invocation.method}")

    @Finally
    def finished(self, invocation, outcome):
        print(f"result:{outcome.status}")


async def main():
    plan = compile_decorated([OfflineModel, SupportHarness, CallLog])
    project = ApplicationProject(plan, {"reply": ApplicationOperation("support")})
    async with project.open() as host:
        print(await host.invoke("reply", "What is your shipping time?"))


asyncio.run(main())
```

预期输出：

```text
model:open
call:run
result:success
Demo orders ship within two working days.
model:close
```

`SupportHarness.run()` 只保留回复流程。容器按类型注入模型；日志切面记录调用结果；模型是应用级共享组件，在 Host 打开时初始化、关闭时清理。`scope="run"` 则让客服组件每次调用使用独立实例。实际适配器可在生命周期方法里创建和关闭客户端；这里的打印只演示调用顺序。

### 替换模型，不改业务方法

在同一文件的 `main()` 之前添加另一个适配器，它遵守应用自己定义的 `ReplyModel` 接口：

```python
@ServiceComponent("model")
class AlternateModel(ReplyModel):
    async def answer(self, question: str) -> str:
        return "Alternative model: a human teammate will follow up."
```

然后只替换 `main()` 中的装配行，再次运行文件：

```python
plan = compile_decorated([AlternateModel, SupportHarness, CallLog])
```

回复会变为 `Alternative model: a human teammate will follow up.`，`call:run` 与 `result:success` 日志仍然存在。两个模型都是离线替身，用于验证装配方式，不代表真实 LLM 的理解或生成质量。接入真实模型时，在适配器中调用 [Provider](./docs/provider-templates.md)，并按需安装 `models` extra、配置凭据及客户端生命周期。

要去掉日志，只需从装配列表移除 `CallLog`，业务方法无需修改。要添加耗时统计等切面，参见 [AOP 开发](./docs/application-aspects.md)。失败调用会记录 `result:error` 并将异常交给调用方；此例不自动重试。

### 继续尝试完整应用

三条完整开发链路见[开发自己的 Harness](./docs/harness-development.md)：

| 示例 | 主要方式 | 演示边界 |
|---|---|---|
| [自定义 Harness](./examples/custom_harness.py) | 显式 Python 装配 | 自定义模型参数、工具和存储，无默认 Loop |
| [客服](./examples/support_harness.py) | 注解扫描、依赖注入、AOP | 本地 FAQ、未知问题转人工、生命周期记录 |
| [编码](./examples/coding_harness.py) | 配置目录、Bean 工厂、AOP | 预览与摘要批准，只修改内存，不执行代码 |

示例使用确定性离线模型替身，不代表真实 LLM 质量。默认 ReAct、Workflow、Provider、工具和预算仍可按需加入，见[默认装配](./docs/default-assembly.md)。`examples` 不包含在 wheel 中；安装用户需从匹配源码或 sdist 复制示例及伴随 JSON，不能把教程文件当成库运行时依赖。

## 按你的方式装配

以下是职责关系，不是必须经过的固定管线：

```text
注解 / 显式 Python / 允许目录中的配置
                 ↓
        AssemblyPlan（依赖与作用域校验）
                 ↓
 ApplicationContext（实例、DI、AOP、生命周期）
                 ↓
  你的 Harness 或可选 ReAct / Workflow 装配
                 ↑
 ApplicationProject / Host ← Python / CLI / TUI
```

| 你要做什么 | 从哪里开始 |
|---|---|
| 接入特殊模型、参数或响应格式 | [Provider 模板](./docs/provider-templates.md) · [模型路由与探测](./docs/model-routing.md) |
| 改写 Agent 推理链路 | [Agent 协议与 Loop](./docs/agents.md) |
| 添加 Python、HTTP、命令或 MCP 工具 | [工具体系](./docs/tools.md) · [MCP 交互](./docs/mcp-interactions.md) |
| 组合流程、状态和审批 | [Workflow](./docs/workflows.md) |
| 接入本地知识、文件或向量检索 | [知识检索](./docs/knowledge-context.md) · [导入与同步](./docs/knowledge-sync-entries.md) |
| 管理用量和上下文 | [Session](./docs/sessions.md) · [共享预算](./docs/shared-budget.md) |
| 编写插件、分享命名版本的装配 | [插件系统](./docs/plugin-system.md) · [工程分享](./docs/project-sharing.md) |

## CLI 与 TUI

安装 `tui` extra 后：

```bash
wagent --help
wagent init
wagent tui
```

`w-agent` 是同一 CLI 的别名。TUI 提供大字符标识与颜文字、运行和审批、会话/用量查看等入口。

2.1.0 还提供 `wagent application run --entry module:create_project --input-file call.json --confirm-code` 与 TUI 的 Application 页，共用公开项目执行入口。项目是受信 Python 代码，确认加载不等于工具副作用批准；完整操作见[三条教程](./docs/harness-development.md)。

`wagent init` 只创建本地 `.wagent` 目录和空的 `config.json`，已有配置不覆盖；**不会配置模型或发起请求**。实际运行前按[Runtime 配置示例](./docs/local-runtime.md#配置)填写配置，再明确授权模型调用。TUI 不替代这些授权边界。

## 能力状态与安全

2.1.0 提供 Harness 开发框架核心；可选高级能力仍可能标记为 `Experimental`。见[版本范围](./docs/releases/2.1.0.md)与[路线图](./docs/roadmap.md)。

发布前的 M0–M5 验收记录包含 259 项相关测试、隔离安装与三示例的仓库外 Python/CLI/无显示 TUI 验证，见[验收记录](./docs/harness-acceptance.md)和[发布证据](./docs/acceptance-2026-10-02-release-2.1.0.md)。这些是指定范围的历史验证，不代表全量回归、真实模型质量/计费或全平台验证。

升级前请核对[版本说明](./docs/releases/2.1.0.md)与[迁移指南](./docs/migration-1x.md)，不要假设旧容器或同步 Runtime 自动具有新容器语义。依赖缺失、注入歧义或作用域不合法会在装配校验时报错；初始化与清理的失败行为见 [Harness 核心](./docs/harness-core.md)。

- 普通 Python 工具和插件是受信宿主代码，**不是安全沙箱**；不可信代码需要隔离执行。
- 工具权限不等于逐调用审批；导入分享码不自动安装、执行代码或授予权限。
- 模型目录声明不证明连接、鉴权或生成质量；未知用量和价格不表示为零。
- 恢复只保证文档明确支持的边界，不恢复任意 Python 调用栈，也不自动重放结果未知的副作用。
- 多 Agent、分布式 Workflow、在线插件市场等保留或计划项，不是当前开箱即用能力；框架不提供多租户托管服务。

## 文档与贡献

从[使用指南](./docs/guide.md)开始，或查阅[文档目录](./docs/README.md)、[架构](./docs/architecture.md)、[公共 API](./docs/api.md)与[1.x 迁移](./docs/migration-1x.md)。

欢迎通过 [Issues](https://github.com/LuckyStar2456/W-Agent-FrameWork/issues) 提交问题与提案。报告问题时请附 Python/W-Agent 版本、最小复现和脱敏日志；新增能力请先说明扩展点、授权边界，并同步中英文文档。贡献约定见[开发者指南](./docs/developer.md)。

## 许可证

[MIT](./LICENSE)
