# 知识计划准备、保存与授权执行入口

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-plan-actions.en.md) | 简体中文

2.0.0 Experimental：本地 API/CLI 回归已通过；真实服务/费用与生产界面验收未执行，已随 2.0.0 发布，不属于 2.0.0a9。

## 宿主绑定与生命周期

`KnowledgeIndexHostOptions(entry, binding, confirm_code=True)` 指向 `module:factory`。工厂无参数，返回异步上下文管理器；进入后提供 1–64 项具名 `KnowledgeIndexHostBinding` 目录。目录名沿用具名知识绑定约束，必须包含本次选择。

绑定包含 `QdrantVectorWriter`；准备绑定另提供 `AsyncTextEmbedder`、宿主维护的 `embedding_key` 和精确维度，执行专用绑定可以完全不提供 Embedder。当前管理模板面向 Qdrant，底层正文/向量/预算/传输接口仍可替换，其他后端计划管理模板仍保留设计。Embedding 可由宿主显式包装共享预算；准备费用不自动并入主 Agent Run。

这是**明确授权的不隔离本地开发代码**。`--confirm-code` / `LOAD INDEX HOST` 允许 import、setup、cleanup；不提供 Python 沙箱，框架也无法约束宿主代码自行产生的副作用。只加载自己审核过的模块。需要 OS 隔离时应由宿主提供独立执行环境，不能把这个开关当作沙箱。

工厂负责资源创建与释放。进入成功后，目录无效、正文错误和取消均尝试退出；退出返回 True 不能吞掉动作错误。正文与清理同时失败保留正文错误并添加固定清理提示；正常动作后清理失败会报错，但之前可能已计费、保存或远端写入。setup 尚未完成的清理由工厂负责，重复取消可能中断清理；不可盲目重试。

参考 `examples/knowledge_index_host.py`：提供 prepare/execute 两种绑定，不自动创建集合、安装模型或读取环境凭据。示例模型名是待用户修改的占位值，维度和服务可用性未验证；加载示例不等于模型已可调用。

## CLI

```powershell
# 授权后准备并保存；整个快照须能装入一个批次（最多 128 文档）
wagent knowledge-plan-prepare --host-entry examples.knowledge_index_host:index_catalog --binding prepare --source-database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --plan-database .wagent/knowledge-plans.sqlite3 --confirm-code --confirm-read --confirm-embedding --confirm-save --confirm-create

# 先查看精确计划和目标，独立完成审查
wagent knowledge-plan-inspect --database .wagent/knowledge-plans.sqlite3 --artifact-digest <工件摘要> --confirm-read --include-target

# 只有审查后才提供批准的同一摘要；不能自动串联执行
wagent knowledge-plan-execute --host-entry examples.knowledge_index_host:index_catalog --binding execute --plan-database .wagent/knowledge-plans.sqlite3 --artifact-digest <工件摘要> --approved-digest <独立审查批准的同一摘要> --journal-database .wagent/knowledge-index.sqlite3 --attempt-id build-001 --confirm-code --confirm-read --confirm-remote-write --confirm-record --confirm-create-journal
```

示例中的摘要占位符必须替换；须从仓库根目录运行示例，或使用自己可导入的模块。库文件父目录需已存在。`--document-ids` 接收不超过 64 KiB 的 JSON 数组，1–128 个唯一字符串/整数原文档 ID（不是向量点 ID）；空数组、布尔值、未知文档等失败。不传时选择整个能放入单批的快照。分块后的快照应使用分块文档 ID。

准备动作的 `KnowledgePlanPrepareRequest` 要求读取、Embedding、保存三项确认，宿主代码另确认；建计划库还需 `--confirm-create`，目标展示另需 `--include-target`。先加载精确正文快照并核对选择，再创建/检查计划库，之后才进入工厂。已有库预检查只是只读 schema 检查，不是容量预留或可写性保证。成功后返回暂存摘要，不执行远端写入；失败时已完成的 Embedding 可能计费，已建库可能保留。

执行动作的 `KnowledgePlanExecuteRequest` 要求读取、远端覆盖写入、日志记录确认，以及与工件摘要完全匹配的独立审批摘要；建回执库另需 `--confirm-create-journal`。全部静态参数/确认在 I/O/import 前校验；随后读取并严格校验已存向量，再加载工厂。目标/向量名/请求大小匹配后才可创建日志并执行。框架不重新生成 Embedding、不自动建集合或重试；任意宿主工厂自身的行为仍须用户审核。

两个动作分别由 `prepare_local_knowledge_plan()` / `execute_local_knowledge_plan()` 实现。准备不接收远端写入确认，执行不接收正文 Embedding 确认，CLI 不提供准备后立即发送的组合命令。回执 completed/acknowledged 只是服务观察，返回的 `remote_state_verified=False` 不会变成“索引已验收”。

## TUI

Index plans 页保留只读查看，并增加宿主/绑定、正文库/命名空间/版本/文档 ID、日志库/尝试 ID 和单独的审批摘要输入。

| 动作 | 必需确认 | 可选确认 |
| --- | --- | --- |
| 查看已存计划 | `READ PLAN` | `SHOW TARGET` |
| 准备并保存 | `READ SOURCE`、`LOAD INDEX HOST`、`EMBED DOCUMENTS`、`SAVE PLAN` | `CREATE PLAN STORE`、`SHOW TARGET` |
| 执行已审查计划 | `READ PLAN`、`LOAD INDEX HOST`、`WRITE INDEX`、`RECORD WRITE`，以及精确审批摘要 | `CREATE INDEX JOURNAL` |

确认字段逐次清空，包括捕获失败；无关动作的确认不能混用。审批摘要不会从读取结果自动填入。请求在后台协程开始前捕获、参数锁定；后续界面修改不会替换正在使用的请求。取消/退出尝试清理已进入的工厂，SQLite 线程会排空，但计费/提交/远端效果可能已发生。输出不解释为 Rich 标记、不回显底层错误正文；失败后先查计划与回执日志再决定下一步。headless TUI 回归已通过；人工布局和生产交互仍待验收。

## 进度与剩余

本地测试覆盖宿主生命周期、单批准备保存/执行；[构建目录、独立回执目录与显式安全重试](./knowledge-builds.md)已实现。准备请求可选 `preparation_database` / `preparation_attempt_id`，CLI 同名连字符参数启用[准备恢复 checkpoint](./knowledge-build-recovery.md)；ready 恢复可不授权新的 Embedding，pending 必须独立处理。其他后端、准备费用归档、真实远端核验与整体生产验收仍待完成。参见[精确计划](./knowledge-index-plans.md)、[回执日志](./knowledge-index-journal.md)和[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。真实服务、费用、质量及人工生产界面仍待验收。
