# 2026-10-01 正式版验收与发布

[English](./acceptance-2026-10-01-stable-release.en.md) | 简体中文

结果：**`wagent-framework==2.0.0` 正式版已发布**。[PyPI 版本页](https://pypi.org/project/wagent-framework/2.0.0/)。没有发布新 alpha，没有运行全量测试，没有调用真实模型，没有修改全局依赖，没有提交/推送 Git。

用户授权本轮核心链路相关测试、wheel/sdist 构建、临时隔离环境安装本地包及通过后发布；随后明确改为正式版，并授权后台启动 Docker Desktop、使用缓存镜像实测且不拉镜像。发布依照这些边界完成。

## 范围与开发结果

[固定基础清单 B01–B12](./stable-release-baseline.md)已闭环。模块审计没有要求再新增架构；实际修复两处基础问题：

- 探测不再把本地模型目录当作连接/鉴权通过；自定义映射的证据来自本次实际请求路径，任务间隔离。远端目录只证明目录连通。
- 插件加载、卸载、替换及通知取消时先收敛已有资源，重复取消不遗留清理任务；内部依赖清理失败不会继续安装替代插件，显式 manager close 可以收敛剩余插件。

新增客服/编码的实际模板→工具→结果示例和权限/生命周期测试。`python-patterns` 技能用于保持协议可替换、显式副作用和异常/取消传播。重整六份中英文入口文档，专题文档明确历史状态与当前源码归属；不把 Experimental 一概提升为稳定。

## 定向源码验收

Python 3.11.9，现有干净项目专用环境。各组有重叠，不相加称为独立用例总数：

| 分组 | 结果 | 范围 |
|---|---:|---|
| 核心开发链路 | 282 passed / 163.65s | 20 文件：ReAct、工具、Runtime、Workflow、知识、兼容、CLI/TUI、Session、模型执行、分享、沙箱、MCP、包完整性 |
| 插件修复 | 76 passed / 13.12s | cancellation、kernel plugins/loading、replacement/session、installation |
| 模型探测修复 | 50 passed | evidence、probing、HTTP templates、OpenAI-compatible、routing |
| 相邻计量 | 91 passed | budget evaluation/probe、service usage frontends/runtime、Runtime shared budget |
| 模板组合 | 12 passed / 1.98s | basic development、agent templates、framework acceptance |
| 底座与预算 | 84 passed / 8.32s | registry/events、lifecycle/AOP/component chain、SQLite budget、usage links/resume、evaluation |
| 版本调整后交叉检查 | 45 passed / 2.41s | package integrity、probe evidence、plugin cancellation、basic development |

源码 TUI 冒烟实际执行 `tests/integration_tui_smoke.py`，宽屏 120×42、窄屏 45×30、大字符/颜文字及回切通过。生成 SVG 供复核；不将自动断言描述为人工逐屏验收。

## 制品与隔离安装

使用既有构建工具，未安装/修改全局工具。`python -m build --no-isolation` 同时生成 sdist，并从 sdist 构建 wheel；初次构建与文档收口发生重叠，冻结后重新构建，发布只使用后者。

- 最终构建目录：`C:/Users/97554/AppData/Local/Temp/wagent-stable-2.0.0-72c3fb1c9fd9484dad400cc5aa3b0e74/frozen-dist`。
- 216 个 `w_agent` Python 源文件在 wheel/sdist 中均与冻结源码逐字节一致，没有额外/遗漏 Python 模块。
- sdist 文档与冻结版逐字节一致；版本、Python 要求、Stable 分类、双 CLI 入口以及 README 元数据核对通过。
- 不含 `.env`、`wagent-pypi.txt`、`.pypirc`、凭据目录、字节码或缓存；`twine check --strict` 两份制品通过。
- 新建不继承全局 site-packages 的虚拟环境，安装本地确切 wheel 与 `models,tui,testing` extras；`pip check` 通过。
- 仓库外使用 `python -I` 确认导入路径位于新环境 `site-packages`，不是源码工作区。
- 复制五个验收文件及它们的测试辅助依赖后，包内回归 **46 passed / 2.44s**。第一次采集缺少辅助测试模块，补齐后重跑；不是框架导入失败。
- `wagent --version`、`w-agent --version` 都返回 2.0.0；客服/编码示例均 completed、2 steps、1 tool call；实际安装包 TUI 宽窄/回切通过。

实际包回归命令（在隔离 smoke 目录；只有测试资产，无 `w_agent` 源码）：

```text
python -I -m pytest -q -o pythonpath=. tests/test_package_integrity.py tests/test_model_probe_evidence.py tests/test_plugin_cancellation.py tests/test_basic_development.py tests/test_framework_acceptance.py
```

## Docker 实测

授权启动 Docker Desktop 后，Linux engine 29.2.1 可达。源码与实际安装包各跑一遍 `integration_docker_smoke.py`，仅使用缓存固定摘要：

```text
node@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
```

验证断网、只读根目录/工作区、UID 65534、移除 capabilities、禁止提权、512 MiB 内存、临时目录写入、显式环境变量、超时与容器清理。均通过；无拉取、无沙箱降级。最终没有遗留 `wagent-release-smoke` 容器；Docker Desktop 保持运行，不改动其他项目容器。

## 发布与远端核对

上传前再次检查 2.0.0 不存在且本地摘要没有变化；通过现有项目凭据上传，凭据内容未输出。上传成功后读取 PyPI 版本 JSON，两份制品均非 yanked，摘要如下且与已验收候选完全一致：

| 制品 | 字节数 | SHA-256 |
|---|---:|---|
| `wagent_framework-2.0.0-py3-none-any.whl` | 586455 | `1a2abe9a99bc232969e545f062cef101e7445b1496a90d495040843a56f27897` |
| `wagent_framework-2.0.0.tar.gz` | 1298525 | `35a51b6ea5685e0a881e90719ba4fa9f9797cad9804732de569229a80691ed38` |

本记录和发布后清单状态是在上传后写入工作区，天然不在已冻结 sdist 内；发布源码未因此改变。没有声称再从 PyPI 安装过，证据是本地确切制品安装与远端摘要一致。

## 剩余范围

基本版剩余阻塞为零；不代表整个框架永远开发完毕。后续仍有模型原生游标/更多多模态、知识高级维护、插件在线更新/迁移、额外编排与沙箱类型、媒体/语音等增强或 Reserved 设计。详见基础清单和[路线图](./roadmap.md)。真实模型计费、远端向量数据库和全平台组合仍未在本轮验证，后续测试/安装/发布继续先询问用户。
