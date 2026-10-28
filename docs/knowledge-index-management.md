# 索引日志管理 API、CLI 与 TUI

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-index-management.en.md) | 简体中文

相关入口包括[精确向量计划与暂存](./knowledge-index-plans.md)及[宿主工厂与 CLI/TUI 准备保存/授权执行](./knowledge-plan-actions.md)。

2.0.0 Experimental：本地核心及无头 TUI 回归已通过，已随 2.0.0 发布，不属于 `2.0.0a9`。本入口管理已有本地索引日志，不是远端索引验收器，也不会创建数据库、生成向量、重发 upsert 或自动抓取证据。

## API

`KnowledgeIndexReviewRequest` 捕获数据库路径、精确清单摘要、可选 `KnowledgeIndexReconciliation` 及独立确认。`review_local_knowledge_index(request)` 复用现有 SQLite 日志的 `inspect()` / `reconcile()`；`knowledge_index_review_view(snapshot)` 是纯展示函数，可用于宿主自定义日志读取结果。底层日志和可选对账协议仍可替换；本地便利入口固定选择 SQLite。

默认输出：清单/快照摘要、维度、预期/本地已确认点数、未确定尝试 ID，以及每次尝试的计划摘要、原始状态、有效状态、点数和对账 ID。`all_points_locally_confirmed` 只描述本地回执/宿主决定，**`remote_state_verified` 始终为 False**。空闲、取消或搜索不到点都不是未应用的充分证据。

`include_details=True` 另行披露 endpoint、Embedding 标签、vector_name、点 ID、远端 operation ID 和对账证据/操作者引用。默认视图中的标签、摘要也可能敏感；无正文不等于匿名。存储日志本身会保存这些字段；隐藏展示不加密数据库，也不认证操作者或证据。

## CLI

```powershell
wagent knowledge-index-inspect --database .wagent/knowledge-index.sqlite3 --manifest-digest <64位清单摘要> --confirm-read

# 宿主已独立审查，并排空该尝试所有潜在迟到效果后，才执行：
wagent knowledge-index-reconcile --database .wagent/knowledge-index.sqlite3 --manifest-digest <64位清单摘要> --attempt-id build-v1-batch-001 --plan-digest <64位计划摘要> --expected-outcome unknown --outcome completed --reconciliation-id review-001 --evidence-ref audit-001 --actor-ref local-developer --confirm-read --confirm-write --confirm-inactive
```

占位摘要需替换为真实日志中的精确 SHA-256，不是命令原文。两条命令都默认只返回摘要视图；`--include-details` 显式披露敏感细节。所有参数先校验再进入日志 I/O；缺少读取/写入/无迟到效果确认均拒绝。读取不会创建缺失库，管理入口不提供隐式初始化。

原始状态只能为 pending/acknowledged/unknown；决定只能为 completed/not-applied。决定绑定清单、计划、尝试、预期原始状态及证据引用。事务内重新匹配，过期状态或不同已有决定失败；完全相同决定可幂等提交，原始观察不覆盖。`not-applied` 只声明该尝试无效果且无迟到效果，不声明远端当前没有这些点。详见[日志与对账语义](./knowledge-index-journal.md)。

确认不是执行租约，也不是框架独立验证过的事实。用户需先停掉/排空有关本地和远端工作，并掌握覆盖整次精确计划的独立证据。没有充分证据应保持未知，不能为了使覆盖率变绿而对账。CLI 参数可能进入 shell 历史；仅填写不含凭据/证据正文的引用。

## TUI

Index journal 页包含已有日志路径、清单摘要、尝试/计划摘要、原始状态、决定结果、对账 ID、证据和操作者引用。

- 查看：填写 `READ INDEX`，点击 Inspect local journal。
- 保存已经审查的决定：另填 `WRITE DECISION` 与 `NO LATE EFFECTS`，点击 Save reviewed decision。
- 展示敏感细节：另填 `SHOW INDEX DETAILS`。

确认词逐次消费；错误拼写或将写入确认用于只读查看会拒绝。捕获不可变请求后锁定字段，操作使用捕获值，不随界面后续修改漂移。相对数据库路径以 TUI 工作区为准。页面挂载不读取日志、不自动发现清单、不填入“最新”状态或自动生成证据。headless TUI 回归已通过；人工布局和生产交互仍待验收。

取消/退出会等待已开始的 SQLite 线程结束；决定可能已经提交，先 inspect 再决定是否重交完全相同决定。失败信息不回显底层数据库异常或证据；输出转义控制字符且不解释为 Rich 标记。管理入口不请求远端写入，因此绝不能把本地失败转为自动重发远端。

## 进度与剩余

管理请求/纯视图/API、CLI 与 TUI 的权限、状态冲突、原始观察保留、字段捕获/取消回归已通过。

新增 `list_local_knowledge_journals()`、`knowledge-index-list --database <日志库> --confirm-read` 与 TUI List journal manifests，可发现清单摘要和未确定尝试，不要求事先知道摘要。目录逐项校验，缺失/损坏失败而非空列表；敏感详细字段仍需显式选择。另见[构建与安全重试](./knowledge-builds.md)、[准备恢复](./knowledge-build-recovery.md)。真实点状态核验、错误决定修订、清理/差异同步、统一费用账本与模型/向量服务验收仍待实现/核验。见[路线图](./roadmap.md)。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。真实服务、费用、质量及人工生产界面仍待验收。
