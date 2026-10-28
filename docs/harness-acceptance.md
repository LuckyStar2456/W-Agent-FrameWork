# Harness 核心最终验收（M5）

[English](./harness-acceptance.en.md) | 简体中文

> 版本说明：本页新框架核心纳入 2.1.0。下方“未发布”与候选 2.0.0 元数据属于发布前阶段记录，不代表 2.1.0 包状态。参见[2.1.0 发布说明](./releases/2.1.0.md)；上传状态以 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/) 为准。

日期：2026-10-02。对象是当前未发布源码及本地候选制品；不是对 PyPI 2.0.0 的新增能力声明。依据[固定基线](./harness-core.md)，不扩大为全库或所有外部服务验收。

## 验收矩阵

| 条目 | 对应实现与证据入口 | 当前状态 |
|---|---|---|
| H01 注解开发闭环 | 客服示例；`test_application_decorators.py`、`test_harness_delivery.py` 的启动失败/有序清理 | 已验收（范围见下文） |
| H02 自定义 Harness | 仓库外 custom/support/coding；默认 Loop/路由/执行器替换 `test_local_application.py` | 已验收（范围见下文） |
| H03 切面闭环 | `test_application_aspects.py`：同步/异步、异常、取消、流收尾 | 已验收（范围见下文） |
| H04 三种装配等价 | 装配/注解/配置用例与三入口失败清理对照 | 已验收（范围见下文） |
| H05 默认可退出 | 自定义示例，无默认 ReAct；子进程阻止 HTTP/TUI 可选依赖导入 | 已验收（范围见下文） |
| H06 前端无特权 | 安装包三项目分别经 Python/CLI/无显示 TUI 执行；删除追踪不取消编码批准检查 | 已验收（范围见下文） |
| H07 文档可复现 | 中英 README 与三条教程；`tests/acceptance/harness_delivery.py` 核对安装来源 | 已验收（范围见下文） |
| H08 单一所有权 | Context/Plugin/Host 取消、借用、卸载与自定义作用域顺序回归 | 已验收（范围见下文） |

阶段完成后自动运行相关测试/静态检查，不跑全量。用户另已批准离线构建 wheel/sdist、新建隔离环境、只使用缓存/本地依赖安装、仓库外三示例与 CLI/TUI 验收。不改全局环境、不调用外部服务、不发布。

## 实现范围

三条开发教程与配套离线示例、README/架构/API/迁移说明同步中英双版。插件桥接新增 `scope_order`，预检与实际创建上下文使用相同层级。编码示例在工具边界检查批准摘要与原文，切面只追踪。

## 验证记录

阶段相关测试在既有项目隔离环境、Python 3.11.9 下运行，全部离线：

- 核心与交付 203 passed / 4.47s：`test_harness_delivery`、`test_application_execution`、`test_application_frontends`、`test_local_application`、`test_application_planning`、`test_application_context`、`test_application_decorators`、`test_application_aspects`、`test_application_configuration`、`test_application_legacy`、`test_application_plugins`。
- 相邻插件 56 passed / 5.51s：`test_kernel_plugins`、`test_plugin_cancellation`、`test_plugin_replacement`、`test_plugin_replacement_session`。
- 共 259 个不同用例；命令是 `python -m pytest tests/<上述文件名>.py ... -q` 的两个明确文件组。不是全量测试，也不与历史 M4 的 572 项累加。
- 33 个相关 Python 文件通过 AST 与内存编译；28 份双语入口/教程文档检查本地链接文件存在（不验证标题锚点）。中英 README 的完整 Python 快速入门均实际运行，输出 `HELLO FRAMEWORK`。

制品验收使用临时目录 `wagent-m5-453ccba78c2447f2ba07d961e8320ac6`：

1. 复制构建输入到独立 source 目录，使用已有构建工具 `python -m build --no-isolation --sdist --wheel`，不修改全局依赖。
2. 从本地 pip HTTP 缓存恢复原 wheel 文件，`--no-index --only-binary=:all: --find-links <wheelhouse>` 安装候选 wheel 的 `tui` extra 到新建、不继承全局依赖的 `installed` 环境；没有安装模型 HTTP extra。
3. 制品检查确认 wheel 中 234 个 Python 模块与源码一致，sdist 包含且逐字匹配 14 个交付文件（双语 README/教程/验收文档、三示例、输入 JSON 与验收脚本）。示例未进入 wheel；未夹带 .env、凭据文件或缓存。
4. 在 `outside` 目录运行独立验收脚本；包来自 `installed/Lib/site-packages/w_agent/__init__.py`。三条示例的脚本入口、生命周期及 Python/CLI/无显示 TUI 均通过；完整 TUI 挂载和 `wagent`/`w-agent` 两个已安装命令入口通过。Docker 探测在 TUI 冒烟中明确禁用。
5. `pip check` 输出 `No broken requirements found.`。离线安装初次发现缓存通用 wheel 名被误标为 py2，保留其归档原字节并改用归档声明的 py3 标签后安装成功；验收脚本的 Windows 子进程编码统一为 UTF-8 后，两命令帮助输出通过。两项都是验收工具修正，不是框架测试失败。

验收记录同步后重新构建本地最终候选并复核安装与仓库外运行；本地文件摘要由临时目录的制品检查输出记录，不把候选当成 PyPI 制品。构建只产生旧式许可证分类/空可选文件匹配的提示，不影响成功退出。

## 保留限制与后续

- 未发布；本地制品元数据仍为 2.0.0，仅作为当前源码候选，不能与 PyPI 同版本制品混同。正式发布需单独决策和版本化。
- 无真实模型、计费质量、外部 MCP/向量服务或新的 Docker 验收；无全量回归。TUI 为无显示交互验收，不是终端外观人工验收。
- 示例使用确定性替身和内存数据；编码不执行代码，批准摘要不是身份认证。普通 Python/切面/插件是受信宿主代码，不是沙箱。
- Host 仅管理提交给自己的任务/流；不协作同步代码、未登记后台任务、任意 Python 栈恢复不受保证。每次调用创建子作用域，不自动跨调用保留 Session 作用域。
- `replace_components` 在启动前替换并校验，不裁剪图或热替换活跃实例。旧容器/代理语义需主动迁移。
- 多 Agent、分布式 Workflow、远程沙箱、插件市场、高级热迁移保留；新增厂商模板、知识高级策略与媒体/TUI 装饰增强暂缓。见[路线图](./roadmap.md)。
