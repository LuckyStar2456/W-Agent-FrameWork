# 2026-10-01 持久关联、分块与归档入口验收

[English](./acceptance-2026-10-01-links-splitting-archives.en.md) | 简体中文

这是[上一轮](./acceptance-2026-10-01-http-archives-runtime.md)后的独立增量。用户已批准本轮相关测试、编译和静态检查。没有跑全量、安装依赖、调用外部服务、构建、提交、推送或发布。版本元数据仍为 `2.0.0a9`，新增功能为未发布 Experimental。

## 本轮交付

- [用量关联](./service-usage-links.md)：可替换关联协议、内存/SQLite 模板、Run/Session→operation 不可覆盖映射；在历史/知识准备前保存，恢复先核对身份。关联失败不进入模型/工具；准备失败可保留预关联，不伪装成已完成 Run。
- `service-usage-link` 按 Run、Session 或 operation 只读查询；`service-usage --run ... --links-database ...` 查关联后展示整个操作汇总。明确 `host-operation-not-this-run`，同操作的多个 Run 不应重复相加。新增无自动 I/O 的可编辑[宿主示例](../examples/service_usage_host.py)。
- [结构/重叠分块](./knowledge-splitting.md)：精确 Unicode/UTF-8 span、段落/句尾优先、硬字节限制及有界字符重叠。同步 API/CLI/TUI 显式选择、配置锁定；默认 v1 序列化和点 ID 兼容，结构模式用严格可重建 v2。它不是模型语义推理。
- [归档入口](./knowledge-archive-entries.md)：`knowledge-archive preview/save/inspect/export`。保存核对独立批准摘要和完整原始来源；导出只新建指定单文件，拒绝覆盖/链接，不执行内容。
- 新增 15 个顶层导出，README、API、开发/TUI 指南、路线图及涉及的旧说明均更新中英文版本。未改动 TUI 大字符欢迎页。

## 定向验证

现有隔离 Python 3.11.9 环境。最终合并组结果：**485 passed，0 failed，0 skipped，127.48 秒**。共选定下列 31 个文件；子代理 137/42/79、根入口 48/16 等组互有重叠，不能累计为独立总数。

```text
python -m pytest -q
  tests/test_service_usage_links.py
  tests/test_service_usage_link_cli.py
  tests/test_service_usage_runtime.py
  tests/test_service_usage_host.py
  tests/test_service_usage_frontends.py
  tests/test_service_usage_resume_frontends.py
  tests/test_service_usage_cli.py
  tests/test_service_usage.py
  tests/test_service_usage_acceptance.py
  tests/test_local_runtime.py
  tests/test_runtime_shared_budget.py
  tests/test_knowledge_runtime.py
  tests/test_sessions.py
  tests/test_knowledge_splitting.py
  tests/test_knowledge_splitting_tui.py
  tests/test_knowledge_split_archive_acceptance.py
  tests/test_knowledge_archive_entries.py
  tests/test_knowledge_archives.py
  tests/test_knowledge_import_extensions.py
  tests/test_knowledge_sync.py
  tests/test_knowledge_sync_management.py
  tests/test_knowledge_sync_cli.py
  tests/test_knowledge_sync_formats.py
  tests/test_knowledge_sync_acceptance.py
  tests/test_tui_knowledge_sync.py
  tests/test_knowledge_ingestion.py
  tests/test_knowledge_management.py
  tests/test_cli.py
  tests/test_tui.py
  tests/test_budget_evaluation_probe.py
  tests/test_knowledge_evaluation_ui.py
```

上面是可读参数清单，执行时应合并成一条命令。15 个相关源码文件、6 个新测试文件与 1 个示例 compileall 通过；813 个公共导出存在且无重复，核心 import 不加载 Pillow/Textual；Git diff 空白检查通过。没有安装/运行额外 lint 或全仓类型检查工具。

重点证据：

1. 真实 SQLite 关联重开、幂等/容量/冲突拒绝；取消等待已启动 worker 后传播，模型不执行。知识准备失败前已有关联，可据此找到同操作的已观察费用。
2. 实际审批断点：错 operation、Session 或缺失关联均在领取断点/调用工具之前拒绝，随后使用正确关联仍可恢复一次。未修改原 SessionManager 协议。
3. 旧 v1 canonical JSON/摘要/稳定向量 ID 参考算法兼容；v2 重复文本、中文、emoji、重叠、配置变化、篡改、零重复 Embedding、取消不保存，以及实际 headless TUI。
4. 注册到主 CLI 的完整路径：结构重叠导入预览→精确保存 v2 trace→归档预览/保存/检查→单 blob 导出；最终原始字节完全一致，再导出拒绝且不改变已有文件/库。
5. 真实临时 Windows junction/硬链接拒绝、缺确认不触及文件系统、摘要或源漂移不建归档库、损坏数据拒绝、fsync 失败清理、无法清理时固定错误提示，以及不删除后来替换的文件。
6. 查询多个 Run 的共用 operation 返回一次操作总量而非逐 Run 账单；示例工厂不创建目录、不打开 SQLite。

## 仍未完成

框架目标保持进行中，六组仍有未关闭项：

1. 知识：模型语义分块、自定义分块持久 codec、逐文档准备检查点、未知/not-applied/撤销恢复、跨库协调、其他后端；归档目录恢复、GC/加密和专门 TUI 入口。
2. 计量：每笔服务/准备观察的 Run 归属与完整自动覆盖、检索/重排统一预算、真实厂商计价、原生游标计量。新关联不修改 Run 模型用量，也不提供跨库原子性。
3. 模型与恢复：更多原生媒体模板、完整 Agent 应用级/跨进程续流。
4. MCP：Tasks、完整 Sandbox、OAuth、session DELETE、旧双端点与自动恢复、外部互操作验收。
5. 插件：在线发现、锁生成、包更新、执行租约/排空、消费者重建和状态迁移。
6. 沙箱与真实验收：网络白名单、通用 Wasm 硬资源、Docker/nsjail/Wasmer 实际隔离、厂商/检索质量与人工 TUI。

所有“已通过”仅对应上述范围，不能替代真实服务或完整框架验收。Reserved 项仍见[路线图](./roadmap.md)。下轮验证、安装、构建或发布继续单独询问。
