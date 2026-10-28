# 知识索引准备恢复与协调边界

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-build-recovery.en.md) | 简体中文

2.0.0 Experimental，已随 2.0.0 发布。SQLite、替身 Embedding/HTTP 与 CLI/TUI 本地回归可验证恢复边界；不代表真实费用、远端索引或生产验收。

## 可恢复的批次准备

`prepare_recoverable_knowledge_plan()` 使用可替换 `KnowledgePreparationStore`，SQLite 实现为 `SQLiteKnowledgePreparationStore`。批次身份绑定精确 manifest、文档顺序、点 ID 和真实输入字节数；manifest 又绑定快照摘要、Embedding 修订/维度与目标。不同身份不能复用 checkpoint。

流程是：事务登记 pending → 一次批次 Embedding → 保存 ready（含完整精确向量工件）→ 幂等保存计划。构造对象不产生 I/O，新库须显式 initialize，父目录须存在。Checkpoint 数据库必须独立于正文、计划、构建和回执库。

| 已保存状态 | 再次调用的行为 |
| --- | --- |
| 无记录 | 只有显式 `confirm_embedding=True` 才登记新尝试并 Embedding |
| pending | 拒绝重发，可能正在执行，也可能已计费后中断 |
| ready | 校验快照/目标/点顺序/工件，直接暂存相同向量，不调用 Embedding |
| abandoned | 保留证据引用与旧尝试；新 ID 和新的 Embedding 确认才可再次准备 |

计划暂存失败时，ready checkpoint 仍可在重启后恢复。若进程在 Embedding 返回与 ready 提交之间崩溃，保留 pending；没有办法仅凭本地缺少结果判断未计费。当前 checkpoint 粒度是批次，尚未保存批内逐文档部分向量。调用方可预先使用 `plan_missing_knowledge_batches()` 划分较小批次，然后对每个明确选择的批次调用此入口。

```powershell
# 在已有 knowledge-plan-prepare 参数上增加独立恢复库与尝试 ID
wagent knowledge-plan-prepare --host-entry examples.knowledge_index_host:index_catalog --binding prepare --source-database .wagent/knowledge.sqlite3 --namespace support --version v1 --plan-database .wagent/knowledge-plans.sqlite3 --document-ids '["doc-a"]' --preparation-database .wagent/knowledge-preparation.sqlite3 --preparation-attempt-id prepare-001 --confirm-code --confirm-read --confirm-embedding --confirm-save --confirm-create

wagent knowledge-preparation-list --database .wagent/knowledge-preparation.sqlite3 --confirm-read
```

`--confirm-create` 在指定恢复库时同时允许初始化计划库与恢复库。已有库恢复仍需宿主代码、读取与保存确认；ready 恢复可省略 `--confirm-embedding`，若不存在 ready 则直接失败，不发出新 Embedding。宿主仍需提供与原身份相符的模型标签、维度和 Writer 配置；加载受信宿主本身可能有宿主自定义副作用。

## 显式处理未知准备结果

先由宿主停止并排空相关 worker，核查独立证据。`abandon()` 的 inactivity 是宿主断言，不是远端计费退款或自动探测。保留 pending 时不会自动过期；退休后旧 worker 的迟到 complete 会被拒绝。

```powershell
wagent knowledge-preparation-abandon --database .wagent/knowledge-preparation.sqlite3 --batch-digest <目录中的批次摘要> --attempt-id prepare-001 --evidence-ref <宿主停止核查记录引用> --confirm-inactive --confirm-write
# 如仍需重新准备，重新调用 prepare，使用新 attempt ID 并明确 --confirm-embedding。
```

单次退休不会进行 Embedding、写远端或自动重试。并发的 begin 在同库事务中只允许一个活跃尝试；ready 同样阻止新准备，恢复它即可。Checkpoint 总计最多 1024 条尝试、256 MiB 工件 payload，单个工件沿用 32 MiB/向量值限制；这些不是文件大小或进程内存配额。这里保存敏感向量与明文证据引用，不保存凭据、正文或准确费用账本。数据库/目录须由宿主管理访问权限。

## 构建与远端写入

将已暂存且完整、无重叠的批次组装为 `KnowledgeIndexBuild`，再通过[构建入口](./knowledge-builds.md)逐批授权写入。构建和回执目录可发现名称/版本/manifest；稳定 retry 链只允许 not-sent 或经独立对账的 not-applied。共享 journal 的 exclusive begin 阻断同目标重叠未确定尝试。

协调仅涵盖调用该入口且共享相同 SQLite 文件、精确目标字符串的 worker。其他库、URL 别名或外部服务调用需要宿主协调。所有本地完成状态仍返回 `remote_state_verified=False`。

本地验证：`py -3.11 -m pytest tests/test_knowledge_build_lifecycle.py tests/test_knowledge_builds.py tests/test_knowledge_plan_actions.py -q`。测试覆盖跨连接竞争、未知状态不重发、独立对账后的 retry、失败暂存后零 Embedding 恢复、显式退休与迟到提交拒绝；不调用真实收费服务。
