# 2026-10-01 HTTP、原始归档与 Runtime 计量验收

[English](./acceptance-2026-10-01-http-archives-runtime.en.md) | 简体中文

本页记录[上一轮](./acceptance-2026-10-01-sync-usage.md)之后的独立增量。用户批准相关测试、编译、静态检查及仅绑定本机回环地址的临时 HTTP 测试服务。未跑全量、安装依赖、调用真实厂商服务、构建、提交、推送或发布。包元数据仍为 `2.0.0a9`，本轮源码属于未发布 Experimental。

## 本轮完成

- [MCP HTTP](./mcp-http-interactions.md)：2026 POST 持续订阅；2025-11-25 session、HTTP 服务器请求回传及显式 GET 通知。版本独立选择，有界读取、取消、关闭；不自动重连或重放。旧 buffered transport 不变。
- [知识同步](./knowledge-sync-entries.md)：CLI `--document-formats` 与 TUI 显式四格式开关；默认仍为 UTF-8。解析器选择、版本/限额/后缀进入预览摘要锁。
- [原始归档](./knowledge-archives.md)：可替换协议与 SQLite 内容寻址模板，保存原始 bytes 和精确 trace 关联。独立读取/建库/写入确认，完整源批次验证后才保存，单批事务与容量限制。无自动归档、覆盖恢复或跨库事务。
- [Runtime 用量观察](./service-usage-runtime.md)：具名宿主目录与真实模型 attempt 观察，可选整个检索调用观察；共享预算复用同一票据，不重复预留。四类 CLI/TUI 入口分别接入运行、审批恢复、评测和探测，加载代码与记录账本独立确认。
- 新增 11 项顶层公共导出；README、API、开发指南、TUI 与路线图同步中英文更新。原大字符欢迎页保留。

用量摘要明确为 `host-operation-not-this-run`：宿主指定 operation 可以跨多个 Run，不是租户。Run 的模型用量不改变，评测保存的原 JSON 报告仍为模型范围；补充账本显示不自动成为逐案例统计。缺失用量/费用不是零；显示读取失败仅警告，不重复执行调用。

## 合并定向验收

现有隔离 Python 3.11.9 环境；最终同一组 **375 passed，0 failed，0 skipped，81.49 秒**。24 个测试文件如下，可在已有环境重现；未安装额外工具。子代理 58/62/88 项、入口 29/3 项和早期 82 项与本组重叠，不能相加。

```text
python -m pytest -q
  tests/test_mcp_http_duplex.py
  tests/test_mcp_client.py
  tests/test_mcp_interactions.py
  tests/test_knowledge_archives.py
  tests/test_knowledge_sync_formats.py
  tests/test_knowledge_sync_management.py
  tests/test_knowledge_sync_cli.py
  tests/test_tui_knowledge_sync.py
  tests/test_knowledge_sync.py
  tests/test_knowledge_sync_acceptance.py
  tests/test_service_usage_runtime.py
  tests/test_service_usage_host.py
  tests/test_service_usage_frontends.py
  tests/test_service_usage_resume_frontends.py
  tests/test_service_usage.py
  tests/test_service_usage_cli.py
  tests/test_service_usage_acceptance.py
  tests/test_local_runtime.py
  tests/test_runtime_shared_budget.py
  tests/test_knowledge_runtime.py
  tests/test_cli.py
  tests/test_tui.py
  tests/test_budget_evaluation_probe.py
  tests/test_knowledge_evaluation_ui.py
```

上方是可读参数清单，执行时合并为一条命令。相关 12 个源码文件、7 个新增测试文件 compileall 通过；798 个公共导出存在且无重复，核心 import 不强制加载 Pillow/Textual；Git diff 空白检查通过。环境没有 Ruff，本轮未安装或运行 Ruff，也未做全仓类型检查。

关键证据：

1. 真实临时 `127.0.0.1` HTTP：连接未结束时读到新版订阅确认，另一个请求并行完成；旧版初始化/session→SSE 回调→独立 POST 202→工具结果，以及显式 GET 通知。测试结束清理 listener/连接任务。
2. 真实离线 PDF/DOCX/XLSX/PPTX→trace 保存→原始 bytes 归档比对；CLI/TUI DOCX 开关；源漂移、容量、错误 schema/关联损坏失败关闭，不留下部分归档批次。
3. 真实 Runtime/SQLite 两个 Run 共 operation、共享票据不双计、失败物理 attempt 与正常重试分开、取消/提前关闭为未知、完成观察失败不发布成功 Finish。
4. CLI/TUI 宿主上下文各开关一次；安全探测不生成，主动探测才记录模型调用。缺任一用量授权在加载前拒绝；汇总读取失败不重试模型。
5. 实际持久审批断点的 CLI/TUI 恢复：首轮 5 tokens、恢复新增 4，账本合计 9 而非 14；原观察不重复、工具只执行一次、Provider 正确关闭。数字均为离线测试夹具，不是实际账单。

## 剩余模块

六组仍有未完成项，本轮关闭的是知识、计量和 MCP 中的子项，不是整个框架完成：

1. **知识**：归档 CLI/还原/GC、语义/重叠分块、逐文档准备检查点、unknown/not-applied/撤销恢复、跨库协调与其他后端。
2. **计量**：Run/Session→operation 持久关联、准备阶段自动关联、工具内部/复合子服务完整覆盖、检索/重排统一预算、真实厂商计费及原生续流计量。
3. **模型与恢复**：更多原生媒体模板、完整 Agent 应用级/跨进程续流；当前 service_usage 与 native cursor 组合明确拒绝。
4. **MCP**：Tasks、完整 Sandbox 绑定、OAuth、session DELETE、2024 双端点及自动恢复；外部服务器互操作未验收。
5. **插件**：在线发现、锁生成、包更新、执行租约/自动排空、消费者重建和状态迁移。
6. **隔离与体验验收**：网络白名单、通用 Wasm 硬资源实现，真实 Docker/nsjail/Wasmer、厂商/检索质量与人工 TUI 验收。

未纳入首版的多 Agent、分布式 Workflow、签名信任网络等仍按[路线图 Reserved](./roadmap.md)保留。后续测试、安装、构建及发布继续逐轮询问，不从本次授权推导。
