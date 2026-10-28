# 2026-10-01 并行开发与统一验收

[English](./acceptance-2026-10-01.en.md) | 简体中文

本页为第一批代码的冻结验收记录；之后的改动与单独授权的定向验证见[后续记录](./acceptance-2026-10-01-followup.md)，不能沿用本页全量通过数证明新代码。

本次按用户要求从串行小步开发切换为模块并行：七个模块分别由子代理实现，最多三个同时运行，主代理负责共享入口、交叉审查与统一验收。保留原有工作区改动；未提交、推送或发布，版本仍为 `2.0.0a9`。本文描述 a9 之后的工作区增量，不把新功能追记为 a9 已发布能力。所有新增模块保持 `Experimental`。

## 本轮模块

| 模块 | 已落地增量 | 后续边界 |
|---|---|---|
| 知识导入 | 可选 PDF/DOCX/XLSX/PPTX 解析；增量解析复用；解析原文与分块偏移；CLI/TUI 预览摘要锁 | OCR、原始二进制仓库、增量向量同步与追溯缓存自动持久化未完成 |
| 检索/Workflow/评测 | BM25、RRF 混合检索、可替换重排；检索节点、证据消息与逐用例隔离评测 | 小语料内存基线；真实检索质量、外部后端与专用评测 UI 待验收/接线 |
| 索引生命周期 | 构建/回执目录；同库原子冲突协调；明确前序身份的重试；ready 向量检查点恢复 | 不是跨库租约；pending 不自动重跑；准备费用与主 Run 统一账本未完成 |
| 模型/媒体 | Responses 同一后台生成原生 GET 续流；可替换检查点/SQLite 跨进程恢复；最终图片输出 | 必须显式 background/store；不是整段 Agent 恢复；CLI/TUI 配置、共享预算续流与真实厂商验收未完成 |
| MCP | 显式 handler、2026 有界 MRTR、双工 stdio、现代/旧版资源订阅 | 持续 HTTP SSE/GET、旧版 HTTP 主动请求、Tasks 与外部互操作尚缺 |
| 沙箱 | nsjail cgroup v2 Provider、旧技能桥、资源参数/清理加固；官方参数语义复核 | Windows 本地测试不证明 Linux 隔离；Wasm 通用硬资源接口及网络 allowlist 尚缺 |
| 插件 | 同名实例替换预览、静止确认、一次性精确计划、依赖停用与旧句柄隔离 | 不是在线包升级/热迁移；自动排空、消费者重建、替换 UI 与持久审计尚缺 |

## 已发现并修复的集成问题

- 四个知识 TUI Panel 的业务 `_task` 与 Textual 消息循环字段冲突，按钮一直被判为忙碌。改用 `_operation_task` / `_panel_closing`，18 项页面回归通过。
- TUI 页签清单旧测试缺少新增四页，已修正并通过；工具运行测试缺少显式 `max_tool_calls`，补测试配置而不放宽运行时默认预算。
- PDF 验收从空白页强化为带正文的真实 PDF，验证提取 `refund seven days`；XLSX/PPTX 与 DOCX 也使用真实依赖生成并解析。
- 对照 nsjail 官方源码发现 CLI `--mount` 不解释通用挂载标志，改用私有临时 protobuf 配置落实 `nosuid/nodev/noexec` 并始终清理；同时修复上游 CPU 配额换算的溢出边界。仍未在真实 Linux 运行。
- 增加公共 API 导出完整性测试与跨模块验收：实际文本导入/摘要锁 → SQLite 重开 → BM25/RRF/重排 → Workflow → ReAct/离线 Provider → 独立用例评测，核对证据 USER 角色、Token 计量和资源关闭。

## 最终干净环境验收

Windows / Python 3.11.9；全部子代理停止代码编辑、共享入口整合后运行：**1,811 passed、3 skipped、0 failed，1,814 项，168.10 秒**。`pytest.ini` 同时收集 `test_*.py` 和 `comprehensive_*.py`，未排除模块，也没有解析依赖跳过。

经用户批准，最终使用**不继承全局 site-packages** 的专用临时 venv，执行 `pip install -e '.[models,tui,testing,knowledge-documents,fastapi]'`。`pip check` 返回 `No broken requirements found`。关键依赖：Rich 14.3.4（符合 `<15`）、Textual 8.2.8、pypdf 6.19.0、python-docx 1.2.0、openpyxl 3.1.5、python-pptx 1.0.2。未修改全局环境；先前继承全局依赖的环境和 1,629 项基线不作为最终证据。

三项跳过逐一说明：

1. Windows 当前权限不允许创建符号链接（`test_symlink_selection_rejected_when_platform_allows_creation`）。
2. Windows 不支持测试 FIFO 创建（`test_fifo_is_rejected_without_opening`）。
3. 干净环境未安装可选 `google.protobuf`，跳过独立 nsjail 配置 schema 解析 QA；该项在已有依赖的宿主环境通过，但不是 Linux/nsjail 实机验收。

额外检查：`compileall` 通过；734 个顶层公共导出无缺失/重复；实际 `wagent --help` 可运行；headless TUI 宽屏、窄屏和缩放恢复均通过。无人工终端布局/生产交互验收。PDF/DOCX/XLSX/PPTX 的 15 项扩展测试包含于统一结果中；各模块定向测试不能再与 1,811 相加。

可复现命令（`python` 指该隔离环境）：

```powershell
python -m pytest -q --tb=short --junitxml=<report-path>
python -m compileall -q w_agent
python -m pip check
python tests/integration_tui_smoke.py --output <tui-report-directory>
```

本机临时环境与验收工件位于 `C:\Users\97554\AppData\Local\Temp\wagent-clean-20261001-9b85883185c44a94baaf28c3b662defa`；`reports/pytest.xml` 为最终 JUnit，`reports/tui/` 为 TUI 自动验收截图。它们不纳入包、不作为永久归档。

未执行真实付费模型/Embedding、外部重排或 Qdrant 写入；Docker API 探测返回 Linux engine pipe 不存在。Wasmer/nsjail/其他系统未真实验收。离线或模拟测试不证明厂商服务、沙箱隔离或模型质量。

## 仍需推进

本轮七个交付切片完成，不等于整份框架路线图完成。剩余开发按六组继续：

1. **知识/索引**：原始二进制与追溯缓存持久化、向量增量同步/旧点清理、语义分块、逐文档准备检查点、跨库租约、其他后端和知识评测专用入口。
2. **计量/预算**：准备、检索、原生续流与主 Run 的统一持久账本/费用归集；不能把未知费用视为零。
3. **模型/交互**：更多厂商媒体映射、原生续流 CLI/TUI 装配、完整 Agent/工具恢复以及 TUI 媒体专用展示。
4. **MCP**：上述 HTTP 持续交互、Tasks、自动恢复和沙箱绑定。
5. **插件工程**：在线发现/锁生成/包升级、自动排空与迁移、消费者重建、替换 CLI/TUI 及审计。
6. **沙箱**：通用 Wasm 硬资源协议、真实网络 allowlist 和多系统适配验证。

外部厂商/Embedding/Qdrant、检索质量、Docker/nsjail/Wasmer 和人工 TUI 验收作为独立验收项，不因本地回归通过而完成。精确状态见[路线图](./roadmap.md)。多 Agent、分布式 Workflow、跨 Store 原子事务、托管评测和签名信任网络仍按既定设计保留，不计入首版已交付能力。
