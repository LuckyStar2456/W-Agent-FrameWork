# 精确知识向量计划与暂存

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-index-plans.en.md) | 简体中文

2.0.0 Experimental：本地回归通过，已随 2.0.0 发布，不属于 2.0.0a9；真实服务、费用、质量及人工生产界面仍待验收。

## 为什么独立保存计划

先准备向量、再预览审批、最后执行，必须保持同一组向量值和目标。`PreparedKnowledgeIndexPlan` 保存完整 `KnowledgeIndexManifest` 和一批 `QdrantUpsertPlan` 的精确向量值。执行时不重读正文、不重算 Embedding，也不自动扩大批次。

工件摘要绑定格式、整个清单与向量内容；清单摘要绑定预期全点集与目标，计划摘要绑定本次精确远端请求。三者不能混用。摘要只用于定位/完整性校验，不是签名、授权或 Embedding 质量证明。完整清单可覆盖多个批次；暂存一批不代表全库准备完成。

## 准备、暂存、审查、执行 API

```python
from w_agent import (
    SQLiteKnowledgeIndexPlanStore, SQLiteKnowledgeIndexJournal,
    prepare_knowledge_index_plan, execute_prepared_knowledge_plan,
)
from my_application import index, embedder, writer, review_saved_artifact

# 示例中的确认由宿主实际授权提供；示例本轮未执行。
artifact = await prepare_knowledge_index_plan(
    index, embedder, writer,
    document_ids=("document-1",), confirm_embedding=True,
)
plans = SQLiteKnowledgeIndexPlanStore("knowledge-plans.sqlite3")
await plans.initialize(confirm_create=True)
digest = await plans.save(artifact, confirm_write=True)

# 可在另一进程/稍后重开；不会重新调用 Embedding。
saved = await plans.load(digest)
# 宿主审查精确工件和目标后返回批准的工件摘要；不能盲抄不可信输入。
approved_digest = await review_saved_artifact(saved)
journal = SQLiteKnowledgeIndexJournal("knowledge-index-journal.sqlite3")
await journal.initialize(confirm_create=True)
receipt = await execute_prepared_knowledge_plan(
    saved, writer, journal, attempt_id="build-v1-batch-001",
    confirm_artifact_digest=approved_digest, confirm_record=True,
)
```

`index`、`embedder`、`writer` 为宿主已装配对象。准备默认拒绝未确认正文 Embedding；`document_ids=None` 只允许整个快照能放入单批的情况，空批拒绝，大快照应显式分批。准备不保存、不创建集合、不写远端。借用对象由宿主管理生命周期，Embedding 可显式包裹共享预算；本模块不自动把准备费用计入 Agent Run。

执行需精确工件摘要与日志写入确认。首先核对当前 Writer 的目标、向量名和请求大小，再登记 pending、发送一次并记录回执；同尝试 ID 重复执行拒绝。不同尝试 ID 或不同日志库不构成全局去重，宿主仍须审查覆盖风险。`confirm_artifact_digest` 是外部审查结果，库内部才把工件内计划摘要传给已有 Writer，不能因暂存成功就自动执行。

## 格式与存储

- `to_json()` 显式输出包含浮点向量的敏感规范 JSON，不适合常规日志。无源正文、API key 或运行时对象，但向量、endpoint、标签、点 ID 仍可能泄露业务信息，不能当作脱敏数据。
- `prepared_knowledge_plan_from_json(payload, expected_digest=...)` 严格核对外部指定摘要、格式、精确字段集、重复键、有限数字、维度、点集、内层摘要及规范序列化；损坏/非规范输入失败，不返回部分计划。自己重算不可信文件的摘要不等于来源可信。
- 单批 1–128 点，清单最多 1024 点；维度上限 65536，总向量值最多 1,048,576，工件 JSON 最多 32 MiB。准备默认总输入 1 MiB、整体超时 30 秒，沿用已有向量准备边界。
- Writer 仍施加自己的请求字节上限，可能比工件限额更小。准备后构造请求因大小失败时，先前 Embedding 可能已计费；不自动重试或保存部分向量。
- `KnowledgeIndexPlanStore` 是可替换 save/load 协议。`SQLiteKnowledgeIndexPlanStore` 使用**独立计划库**，不能与正文快照库、写入回执日志库混用；构造无 I/O，建库和保存分别确认，父目录必须已存在。
- 按工件摘要追加保存，已有完全相同内容幂等；损坏的既有记录失败而非覆盖修复。读取使用只读连接并核对完整性，缺失库不创建，未知 schema 不迁移。最多 128 工件、总 payload 256 MiB；不是物理磁盘/WAL/进程内存配额。
- 取消时排空已经开始的 SQLite 线程，提交可能已完成。准备/暂存/日志登记/远端写入/最终回执是分开的边界；任何失败都不代表之前的动作被回滚。检查状态后再决定下一步，不自动重嵌入或重放。

## 只读管理入口

```powershell
wagent knowledge-plan-inspect --database .wagent/knowledge-plans.sqlite3 --artifact-digest <工件SHA256> --confirm-read
# 另加 --include-target 才输出目标、Embedding 标签和本批点 ID
```

用真实工件摘要替换占位符。`inspect_stored_knowledge_plan()` 是共用本地查看 API。默认摘要视图无向量值和敏感目标字段；即便显示目标也不输出向量值。`authorized=False` 表示该视图不授予许可，`remote_state_verified=False` 表示没有核验远端，并不是查询过远端后认定不存在。

TUI 的 Index plans 页要求 `READ PLAN`；另填 `SHOW TARGET` 才显示目标。确认逐次消费，捕获参数后锁定字段，可取消，页面挂载不读取、不执行。相对路径以 TUI 工作区为准。终端输出转义控制字符、不解析 Rich 标记。headless TUI 回归已通过；人工布局和生产交互仍待验收。

## 本轮进度与剩余

精确计划编解码、可替换暂存/SQLite、准备/授权执行、CLI 查看和 headless TUI 捕获本地回归通过，覆盖篡改、确认和重复尝试拒绝。

[具名宿主动作](./knowledge-plan-actions.md)、[目录/批次建议](./knowledge-plan-catalog.md)、[完整构建与安全重试](./knowledge-builds.md)及 [ready 准备恢复](./knowledge-build-recovery.md)已实现并有本地回归覆盖。同库冲突协调不是跨库租约。准备/主 Run 费用统一归集、真实索引核验、其他后端和生产验收仍未完成。导入扩展、混合检索与 Workflow/评测 API 见各自专题。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
