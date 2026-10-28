# 完整知识索引构建清单与逐批继续

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-builds.en.md) | 简体中文

2.0.0 Experimental：本地核心回归测试已执行通过；真实服务/费用/远端检索验收未执行，已随 2.0.0 发布，不属于 2.0.0a9。

## 固定已准备的完整集合

`KnowledgeIndexBuild(name, version, manifest, plans)` 固定用户选择的有序 `KnowledgeIndexPlanInfo`，要求同一精确清单、1–128 个不同工件、无重叠、完整覆盖预期点。缺失或重叠直接拒绝，不自动挑选“最新”或替换向量。名称、版本、顺序、清单和计划引用都参与构建摘要。

清单只保存工件摘要、计划摘要、点 ID 与目标清单，不复制正文、向量或凭据。`assemble_knowledge_build()` 可通过可替换计划存储读取并核对每份选中工件，再构造清单；需要显式读取确认。构造或保存都不批准执行，也不证明向量模型/质量正确。

`knowledge_build_from_json()` 严格校验构建摘要、精确字段、重复键、格式、规范序列化、完整覆盖和无重叠。摘要是完整性标识，不是签名或来源认证；JSON 中目标与标签仍可敏感，摘要视图不显示它们。

## 持久化与本地入口

`KnowledgeBuildStore.save/load` 是独立可替换协议。`SQLiteKnowledgeBuildStore` 使用第四类独立数据库：**正文快照库、向量计划库、构建清单库、回执日志库不可混用**。按用户自定义 name/version 追加保存：相同内容幂等，不同内容不能覆盖同一版本，损坏读取失败而非修复。每个构建最多 1 MiB，库最多 1024 个版本/总 payload 64 MiB；不是物理磁盘或进程内存配额。

构造无 I/O，创建与保存分别确认，父目录须存在；不迁移其他 schema、不创建集合、不复制向量、不删除旧构建。取消会排空已开始的 SQLite 线程，写入可能已经提交。计划文件丢失不会被构建清单自动重建。

```powershell
# 显式选择完整、无重叠的计划集合；默认只预览，不打开构建数据库
wagent knowledge-build-create --plan-database .wagent/knowledge-plans.sqlite3 --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --artifact-digest <第一批工件摘要> --artifact-digest <第二批工件摘要> --confirm-read
# 保存时另加 --confirm-save；新建构建库再加 --confirm-create

wagent knowledge-build-inspect --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --confirm-read
# 查询恢复状态时另加 --journal-database .wagent/knowledge-index.sqlite3（既有日志库）
```

用真实摘要替换占位符，按所需顺序重复 `--artifact-digest`。`create_local_knowledge_build()` / `review_local_knowledge_build()` 是共用本地 API。预览不是后续保存的锁定提交，但使用不可变计划摘要并保持名称/版本/顺序时构建身份稳定。

只查看构建时不读取计划文件，返回 `artifact_availability_checked=False`；不得据此声称所有向量仍存在。传入日志库才查询进度；日志缺失/损坏/无权限是错误，不冒充全新构建。仅**成功打开支持的日志库后明确返回该清单不存在**，才表示该日志里还没有此清单的尝试。自定义日志实现须遵守相同 not-found 语义，不可把 I/O 错误转成缺失。

## 逐批继续，不自动重发

每批 `attempt_id` 由构建摘要与工件摘要稳定派生。`knowledge_build_progress()` / `inspect_knowledge_build_progress()` 从日志推导每批原始状态、有效状态、重叠的外部未确定尝试，以及 `can_request_first_execution`。

- 没有对应尝试且没有重叠的外部 pending/acknowledged/unknown，才允许请求该批首次执行；这不是自动许可。
- 同一派生尝试 ID 的计划/点序列若与构建不符，读取失败，不将另一写入当作本批证据。
- completed 或宿主对账后 completed 可计入本地完成，但外部未确定重叠仍阻止整体完成判断。
- 本批所有状态均不自动重试。`not-sent` 或独立对账后的 `not-applied` 可通过 `retry_knowledge_build_batch()` 明确重试；绑定前次尝试 ID、构建/工件批准摘要，稳定派生下一次 ID，保留旧记录。pending/acknowledged/unknown 不允许直接重试。
- `all_batches_locally_completed` 仅描述这组精确尝试的本地观察；`remote_state_verified=False` 始终保留。其他构建的成功不能代替本批回执，也不证明当前远端仍保留这些向量。

```python
from w_agent import execute_knowledge_build_batch, inspect_knowledge_build_progress
from my_application import build, plans, writer, journal, selected_artifact, reviewed_build, reviewed_artifact

progress = await inspect_knowledge_build_progress(build, journal)
# 人工/宿主审查之后，只明确执行所选的一批；不遍历并自动批准。
receipt = await execute_knowledge_build_batch(
    build, selected_artifact, plans, writer, journal,
    confirm_build_digest=reviewed_build,
    confirm_artifact_digest=reviewed_artifact,
    confirm_record=True,
)
```

执行前分别核对构建摘要、工件摘要、工件可用性及内容、当前日志状态，再复用精确计划执行链：pending → 一次远端写入 → 最终观察。不重新 Embedding，不凭缺少成功回执重发。构建要求 `CoordinatedKnowledgeIndexJournal.begin_exclusive()`：SQLite 在同一个 `BEGIN IMMEDIATE` 中检查同库、相同精确 endpoint/vector_name 下跨清单的未确定重叠点并登记 pending。重复稳定 ID 或未确定重叠均拒绝；没有自动租约过期。不同数据库、不同 URL 别名、绕过此入口的低层 begin/外部 Writer 仍由宿主协调。进度视图只反映当前清单；真正发送前仍会做跨清单原子检查。

工件、构建和日志是分开的存储边界，没有跨库事务。取消或保存回执失败时先重新 inspect；未知状态走独立证据对账。换构建名称/版本不是绕过未知结果的办法，同日志内相同目标的未确定重叠仍阻止继续；不同库不共享协调状态。

## 显式执行入口与 TUI

`KnowledgeBuildExecuteRequest` 是冻结的本地单批请求，`execute_local_knowledge_build_batch()` 为 CLI/TUI 共用入口。读取、远端覆盖写入、写日志分别授权；宿主另用 `KnowledgeIndexHostOptions` 明确批准不隔离本地代码。名称/版本、三类数据库路径、摘要与确认值先做纯参数校验；读取后比对构建摘要、所选工件归属与完整计划引用，再导入宿主。目标/请求大小不匹配会在创建日志库前拒绝。

```powershell
wagent knowledge-build-execute --host examples.knowledge_index_host:index_catalog --binding execute --build-database .wagent/knowledge-builds.sqlite3 --name support-index --version v1 --plan-database .wagent/knowledge-plans.sqlite3 --journal-database .wagent/knowledge-index.sqlite3 --artifact-digest <所选工件摘要> --approved-build-digest <独立审查的构建摘要> --approved-artifact-digest <独立审查的同一工件摘要> --confirm-code --confirm-read --confirm-remote-write --confirm-record
# 仅在明确新建日志库时另加 --confirm-create-journal；不会新建构建或重新 Embedding。
```

宿主工厂及其清理均由开发者负责，可以使用无 embedder 的执行专用绑定。工厂本身是受信任代码，可能产生自身副作用；确认不等于沙箱。返回前退出宿主上下文；若清理失败，远端写入和本地回执仍可能已经完成，必须重新 inspect，不因错误再次发送。同一构建内其他未尝试批次可以继续明确选择；没有“一键执行全部”。

TUI 新增 `Knowledge builds` 页：

- 创建：填写名称、版本、计划库、构建库及有序工件摘要 JSON 数组；输入 `READ BUILD INPUTS` 仅预览，另加 `SAVE BUILD` 才保存，新库再加 `CREATE BUILD STORE`。
- 查看：填写精确名称/版本与构建库，并输入 `READ BUILD INPUTS`；日志库留空仅看构建，填写后才读本地进度。不会自动读取向量工件。
- 执行：填写一个工件摘要与独立审查的构建/工件摘要、宿主绑定及三类数据库路径；分别输入 `READ BUILD INPUTS`、`LOAD INDEX HOST`、`WRITE INDEX`、`RECORD WRITE`；新日志库才增加 `CREATE INDEX JOURNAL`。

摘要批准字段不会自动填入。所有确认词在捕获动作时消费，包括输入有误；无关动作的确认词会被拒绝。请求冻结后后台执行、锁定表单，取消/卸载排空当前任务；界面只显示固定错误及转义摘要，不输出异常正文或凭据。取消不是回滚；headless TUI 回归已通过；人工布局和生产交互仍待验收。

## 目录、显式重试与准备恢复

`SQLiteKnowledgeBuildStore.list_builds()` 和 `SQLiteKnowledgeIndexJournal.list_journals()` 在有界只读事务中校验完整目录；损坏/缺失数据库失败，不冒充空目录。CLI 使用 `knowledge-build-list --database <构建库> --confirm-read` 和 `knowledge-index-list --database <日志库> --confirm-read`；TUI 对应 List saved builds / List journal manifests，不要求预先知道名称或摘要。

`knowledge-build-execute` 增加 `--previous-attempt-id <最后一次安全失败尝试>`，TUI 对应 Retry only 输入。其他独立批准仍必需。进度返回 `attempt_history`、`can_request_retry`、`next_retry_attempt_id`；陈旧前次 ID、完成状态或未知状态不会发送。首次执行入口不会隐式变成重试。

准备阶段可启用[持久 checkpoint](./knowledge-build-recovery.md)，跨进程恢复已完成批次，阻断未确定 Embedding 的自动重发。当前仍无分布式租约、逐文档向量 checkpoint、准备费用精确归档或真实远端验收；参见[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
