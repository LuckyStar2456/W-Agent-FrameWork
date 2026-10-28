# W-Agent 使用指南

[English](./guide.en.md) | 简体中文

本指南面向 **2.0.0**，要求 Python 3.11+。[PyPI 版本页](https://pypi.org/project/wagent-framework/2.0.0/)提供正式安装包；验证证据见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

## 1. 安装并先跑离线示例

在自己的虚拟环境安装，并运行 [README 最小示例](../README.md#快速入门)：

```bash
python -m pip install "wagent-framework==2.0.0"
wagent --help
```

如果要开发框架或运行仓库中的完整客服/编码示例，在同版本源码根目录使用可编辑安装：

```powershell
python -m pip install -e .
python -m examples.basic_development support
python -m examples.basic_development coding
wagent --help
```

示例实际使用现代模板、注册表和工具执行器，最终文本来自真实工具结果，没有真实模型调用。安装依赖可能联网，与示例离线运行不同。完整解释见[基础开发教程](./basic-development.md)。

使用 PyPI 包时，也可从同版本源码复制 `examples/basic_development.py` 到自己的项目，运行 `python basic_development.py support`；不要假定 wheel 提供 `examples` 包。

按需选择 extras：`models` 为 HTTP 模型，`tui` 为 Textual，`knowledge-documents` 为 PDF/DOCX/XLSX/PPTX，`mcp` 为 HTTP MCP 路径，`media-preview` 为图片字符预览；另有 `fastapi`、`langchain`、`opentelemetry`、`testing` 和平台受限的 `wasm`。例如 `python -m pip install -e ".[models,tui]"`。依赖安装不是服务调用授权。

## 2. 选择最小开发路径

- 客服/RAG：从 `customer_support_agent` 和样例 `support_tools()` 开始，替换本地文档并保留来源；再接[知识工具](./knowledge-tools.md)或[具名知识装配](./knowledge-runtime.md)。
- 编码：从 `coding_agent` 和 `coding_tools(source)` 开始。示例只读宿主给定文本，不包含隐式 IDE、任意文件访问、shell 或写入。
- 单 Agent：组合 Provider、ModelRegistry/Router/Executor、ToolRegistry/Executor 与 ReactAgentLoop。模板不自动注册工具或授权，见[Agent](./agents.md)与[工具](./tools.md)。
- Workflow：选择 DAG、状态图或 Python 定义，通过公开适配器与 Agent 组合。恢复位于支持的节点边界，不恢复任意 Python 指令栈，见[Workflow](./workflows.md)。

## 3. 接真实模型与持久 Runtime

[基础教程](./basic-development.md)提供可选 Ollama 替换代码；[Provider 模板](./provider-templates.md)提供其他服务路径。准备自己的地址、模型和凭据，明确批准请求及潜在费用。声明模型目录/能力不证明远端连通、鉴权或生成质量，见[模型路由与探测](./model-routing.md)。

需要配置、Session、持久 Run 和审批恢复时，使用[本地 Runtime](./local-runtime.md)。先初始化目录并检查环境：

```text
wagent init
wagent doctor
wagent profile list
```

`wagent init` 只创建目录与空的 `{}` 配置，不会生成可运行的模型配置。按照[本地 Runtime 配置示例](./local-runtime.md)填写 `.wagent/config.json`，设置实际 Provider、模型、地址与凭据，再明确授权执行：

```text
wagent run "hello" --config .wagent/config.json --confirm-model-call --json
```

`run` 会调用服务并可能产生费用。安装 `tui` extra 后，可用 `wagent tui` 打开终端界面；界面不能代替有效模型配置。工厂位于自己项目的正常导入路径，例如 `my_project_tools:open_tools`，不要依赖 wheel 中不存在的 `examples.*`。工厂加载、工具选择、本次权限、精确调用 ID 审批分别控制；配置引用不能代替授权。

## 4. 知识、状态与安全

知识最小闭环可只用本地关键词检索。进阶路径为[文件预览/锁定保存 → 固定 trace → 同步计划 → 独立批准执行](./knowledge-sync-entries.md)。解析器与[结构/重叠分块](./knowledge-splitting.md)配置进入锁定摘要；[原始归档](./knowledge-archive-entries.md)显式读取/写入/新文件导出，不自动恢复覆盖。读取许可不能替代 Embedding、upsert 和 delete 批准。

[Run/Session](./sessions.md)、[回放](./event-replay.md)、[共享预算](./shared-budget.md)与[服务用量](./service-usage-runtime.md)有各自存储/计量边界。未知价格/用量保持未知；预算不是精确账单。示例 helper 拥有并关闭 Provider，实际宿主要明确共享资源、任务取消与 Store 生命周期。

不可信代码使用[沙箱](./sandbox.md)，隔离不可用时失败关闭。显式 unsafe-local 不提供隔离保证。普通 Python handler/插件是受信宿主代码；WRITE/EXTERNAL 权限不替代逐调用审批，副作用未知不自动重放。

## 5. 测试、分享与兼容

- [测试与评测](./testing-evaluation.md)：先离线脚本模型/契约断言，再经授权测试真实模型；本地通过不是厂商质量或计费验收。
- [工程分享](./project-sharing.md)：配置/插件引用先离线预览；安装、导入和运行分别授权。
- [1.x 迁移](./migration-1x.md)：保留工程底座及 `BaseAgent.arun()`；`LegacyAgentAdapter` 只桥接文本/最终结果，不隐式获得工具循环或持久 Session。
- [开发者指南](./developer.md)、[API](./api.md)、[文档目录](./README.md)：替换模块与完整接口索引。

能力状态以[路线图](./roadmap.md)为准。`Planned` / `Reserved` 不是可执行 API；语义分块、跨库事务、高级恢复和多 Agent 等增强不是基础使用前提。当前发布验证见[正式版记录](./acceptance-2026-10-01-stable-release.md)，历史 alpha 记录不能代替该版本的验收证据。
