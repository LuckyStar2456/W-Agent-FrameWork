# 2026-10-01 同步入口与跨服务计量验收

[English](./acceptance-2026-10-01-sync-usage.en.md) | 简体中文

本页是[上一批定向验收](./acceptance-2026-10-01-followup.md)之后的独立增量，不沿用第一批 1811 项全量结果。用户明确批准本轮相关测试、编译和静态检查；没有安装依赖、调用真实服务、构建、提交、推送或发布。源码元数据仍为 `2.0.0a9`，新增能力为未发布 `Experimental`。

## 已交付

- [同步管理与 CLI](./knowledge-sync-entries.md)：UTF-8 文件预览/摘要锁定 trace 保存，具名宿主工厂准备精确持久向量计划，安全检查，独立 upsert/delete 批准与执行；明确未发送的重试及宿主证据完成对账。已知目标冲突在 Embedding 前拒绝；竞争仍由持久 stage 校验。
- [同步 TUI](./knowledge-sync-tui.md)：同一服务的文件导入到批准执行完整主路径，独立单次确认、请求冻结、后台取消和安全分页。保留大字符欢迎页；TUI 不提供 retry/reconcile 按钮，可用显式 CLI。
- [跨服务用量](./service-usage.md)：模型、Embedding、检索、重排的统一观测协议、内存/SQLite 账本和显式包装器。复用现有共享预算，不重复预留；按币种/价格版本分组，未知与不适用分开。`wagent service-usage` 只读显示输入/输出 Token、费用与完整性。
- `examples/knowledge_sync_host.py`：可编辑本地 Ollama/Qdrant 工厂，无导入联网、拉模型或建集合。须自行配置实际模型与独占集合。

## 验证范围

现有隔离 Python 3.11.9 环境；冻结后的最终合并定向结果为 **282 passed，0 failed，0 skipped，51.72 秒**。JUnit：验收虚拟环境下 `reports/sync-service-integration-final.xml`。相关 compileall、公共导出和 Git 空白检查已通过，787 个公共导出存在且无重复；核心 import 不加载 Pillow/Textual。没有运行全仓类型检查或额外 lint 工具。

合并组覆盖 18 个明确选定文件：新增 sync 管理/CLI/TUI、service usage、两组根集成测试，及受影响的 shared budget、Embedding budget、Session usage、CLI/TUI、包接口和已有跨链路验收。不是全量测试，子代理/前期结果与此组有重叠，不能相加。

关键证据使用真实临时 SQLite 与离线服务：

1. 实际注册的 CLI 从文件预览/保存到准备/执行；第二版文件变化产生差异增删，缺少删除批准时在宿主导入前拒绝，重执行 completed 计划不再嵌入或发送。
2. 明确 not-sent 从 generation 0 检查到独立批准重试；64 次耗尽仍可检查；unknown/ack 不自动重发，取消/cleanup 失败保留状态边界。
3. 四种服务共用持久观测，模型和 Embedding 共用原 SQLite 预算；重开后已知用量 9 Token、宿主测试价格 0.03 USD，后续超额模型调用被预算拒绝。数字是离线夹具，不是真实账单。
4. 账本不保存查询/正文；缺失费用不变零；`1E28 + 1E-28` 在宿主低精度 Decimal 环境仍精确保留。

## 仍需推进

六组剩余工作没有全部关闭，本轮完成其中的同步入口与显式统一观测部分：

1. 知识：其他格式 trace 入口、原始二进制归档、语义分块、准备部分检查点、未知结果 not-applied/撤销恢复及跨库协调。
2. 计量：运行链自动关联/界面装配、检索与重排的服务级预算接线、真实供应商费用映射、原生游标计量。新账本不自动改写 Run/Session/evaluate 统计。
3. 模型与恢复：更多原生媒体模板、完整 Agent 应用级与跨进程续流恢复。
4. MCP：持续 HTTP 订阅、旧版 HTTP 主动请求、Tasks 与 Sandbox 绑定。
5. 插件：在线发现/锁定/更新、执行租约和状态迁移。
6. 隔离与验收：网络策略/通用 Wasm，真实服务、Docker/nsjail/Wasmer 与人工终端体验验收。

真实收费、检索质量、远端状态、跨库原子提交以及人工 TUI 未由本轮证明。完整状态以[路线图](./roadmap.md)为准；未完成目标不标为完成。
