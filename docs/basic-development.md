# 基础开发：客服与编码 Agent

简体中文 | [English](./basic-development.en.md)

先跑通“模板 → 注册工具 → 执行权限检查 → 工具结果 → 最终回答”，再替换模型和业务数据。[现代示例](../examples/basic_development.py)默认完全离线，不读取工作区文件、不执行代码、不启动服务，也不下载模型。旧版 `basic_agent.py` 不受影响。

## 最短可运行流程

在已安装当前项目依赖的源码根目录运行：

```powershell
python -m examples.basic_development support
python -m examples.basic_development coding
```

Windows 多版本 Python 环境可将 `python` 换成相应虚拟环境的 Python，或已安装依赖的 `py -3.11`。

两条命令均返回 JSON：`stop_reason="completed"`、`steps=2`、`tool_calls=1`。客服输出示例退货条款及 `sample:returns` 来源；编码输出宿主提供的 `add()` 源文本，既不执行也不修改它。条款仅为演示，不是实际商业承诺。

`examples` 是源码资产，不是承诺随 wheel 提供的 Python 包。仅安装 wheel 的用户，请从同版本源码取得 `examples/basic_development.py`，复制到自己的项目根目录，然后运行：

```powershell
python basic_development.py support
python basic_development.py coding
```

不要在已安装 wheel 的项目中依赖 `examples.basic_development`。后续导入使用自己的项目模块路径，例如 `from basic_development import support_tools`。

## 修改哪里

| 用途 | 模板 | 实际工具 | 单次运行权限 |
| --- | --- | --- | --- |
| 客服 | `customer_support_agent(model="demo")` | `support_tools()` 注册 `knowledge_search_tool`，查询内存文档与关键词检索器 | `knowledge.read` |
| 编码 | `coding_agent(model="demo")` | `coding_tools(source)` 注册只读 `read_sample_module`，返回宿主明确提供的源文本 | `workspace.read` |

客服先替换 `support_tools()` 中的样例文档，保留来源标识；需要文件/向量知识库时接入自己的已授权检索器，参见[知识工具](./knowledge-tools.md)和[知识同步入口](./knowledge-sync-entries.md)。模型提示词不能代替来源证据。

编码先向 `coding_tools(source)` 传入自己的小段文本，或显式编写受限的项目工具。此示例不提供内置 IDE、任意路径读取、shell 执行或文件写入。`python_tool` 运行的是宿主代码，不是沙箱；宿主负责路径范围、输入验证和副作用分类。

`OfflineToolModel` 是确定性的两轮测试替身：第一轮发出工具调用，第二轮读取真实 `ToolResultContent` 产生回答。它验证组合链路，不验证语言模型理解、检索质量或任务解决能力；返回的 token 数也是合成计数，不能用于计费结论。

## 显式接入真实模型（可选，未在本例验收中请求服务）

确认模型服务、数据披露和费用授权后，可以在已复制示例的项目中创建以下脚本。用实际已配置、支持工具调用的模型名替换占位符；这段代码会访问本机 Ollama，不会替你安装或启动服务。

```python
import asyncio
from basic_development import run_with_provider, support_tools
from w_agent import customer_support_agent, ollama_provider

async def main():
    model = "YOUR_INSTALLED_TOOL_CAPABLE_MODEL"
    provider = ollama_provider(default_model=model)
    result = await run_with_provider(
        provider, customer_support_agent(model=model), support_tools(),
        "What is the sample returns rule?", frozenset({"knowledge.read"}),
        provider_name="ollama",
    )
    print(result.stop_reason.value, result.output)

asyncio.run(main())
```

编码路径只需改为 `coding_agent`、`coding_tools()`、相应问题和 `workspace.read`。检查 `stop_reason`；不要将超限、失败或 `needs-approval` 当成成功回答。

## 权限与关闭资源

`run_with_provider()` 为本次调用创建注册表，注册模型和工具，并使用 `ReactAgentLoop` / `ToolExecutor`。权限由传入的 `frozenset` 明确给出，不从提示词推导。只读示例显式声明 `READ`；缺权限时 handler 不会运行。`WRITE` / `EXTERNAL` 即使具备权限，仍需要对应调用 ID 的独立批准，示例 helper 不代为批准。

helper 拥有传入 Provider：正常返回、注册失败或取消时都会撤销已建立的注册，并调用其可用的 `aclose()`。不要传入仍被其他运行共享的 Provider；共享客户端需要宿主自行适配生命周期。异步任务取消会向上传播，不伪造成功结果。

这是单次内存运行示例，没有持久化 RunStore。重新调用 helper 会产生新 Run，不能恢复旧审批点。需要跨进程会话、审批恢复或 CLI/TUI 工程入口时，使用[本地 Runtime](./local-runtime.md)与[工具执行](./tools.md)。若将工厂交给 CLI，请用自己的模块路径（例如 `basic_development:support_tools`），遵守该入口的工具代码加载确认、工具启用列表、权限及逐调用审批；工厂导入并不自动授予权限。

## 本轮验证

已有干净 Python 环境中运行：

```powershell
python -m pytest -q tests/test_basic_development.py tests/test_agent_templates.py tests/test_framework_acceptance.py
```

结果 `12 passed`；上述两个离线示例命令均实际返回成功。新增测试覆盖客服来源与编码真实源文本进入最终回答、缺权限不执行 handler、写操作独立审批、注册失败及取消时关闭 Provider。本轮未调用真实模型或知识服务，不是模型质量、部署或正式发布验收。
