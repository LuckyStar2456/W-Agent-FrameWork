# 计划目录、准备覆盖与缺失批次建议

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-plan-catalog.en.md) | 简体中文

2.0.0 Experimental：本地回归通过，已随 2.0.0 发布，不属于 2.0.0a9；真实服务、费用、质量及人工生产界面仍待验收。

## 可替换目录与一致读取

`KnowledgeIndexPlanCatalog.list_plans()` 是可选扩展，不改变已有 `KnowledgeIndexPlanStore.save/load` 协议。结果为不可变 `KnowledgeIndexPlanInfo`：工件摘要、计划摘要、完整清单与该批点 ID，不保留向量值。宿主自己构造这些元数据时须负责准确性；类型校验并不能证明向量曾被正确读取。

SQLite 实现按工件摘要排序，在一个只读事务里检查 schema、128 条工件/总 payload 256 MiB 限额，然后逐条严格解码已有工件并校验内外摘要与规范 JSON。每条最多 32 MiB；逐条丢弃向量，仅保留元数据。任何损坏、超限或不支持的 schema 都使整次目录读取失败，不返回部分“成功”状态；过滤清单也不能隐藏其他损坏行。

不会创建数据库、加载宿主代码、调用 Embedding、写远端或修改日志。只读事务给出一次目录快照，不是租约、冻结库或进程内存上限。SQLite timeout 是锁等待配置，不保证整个解码耗时。取消会等待已经开始的读取线程排空。

## 覆盖分析

`KnowledgePlanCoverage(manifest, plans)` 要求元数据属于同一个**完全相同的清单**、工件摘要不重复，最多 128 个计划；可以传空元组表达“已知该清单，但尚未准备任何点”。

- `prepared_point_ids`：已有计划点 ID 的并集，按清单顺序返回。
- `missing_point_ids`：清单中尚未被任何已存计划覆盖的点。
- `overlapping_point_ids`：出现在两个或更多不同工件中的点，不自动选一个胜出。
- `all_points_prepared` 只表示准备并集完整；即便为 True，也可能存在重叠。
- `batches_disjoint` 只描述是否重叠；重叠不证明向量不同，不重叠也不证明模型正确。
- `execution_selected=False`、`remote_state_verified=False` 明确表示没有形成批准的执行集合、没有核验远端。已准备不是已执行、已计费结算或检索验收。

本目录只能发现**计划库已有工件所引用的清单**，不是所有回执日志清单的目录。无工件的指定摘要返回 not-found，不将它误判成没有缺失点；空库全量查询返回空列表。

## CLI 与 TUI 目录

```powershell
wagent knowledge-plan-list --database .wagent/knowledge-plans.sqlite3 --confirm-read
wagent knowledge-plan-list --database .wagent/knowledge-plans.sqlite3 --manifest-digest <清单SHA256> --confirm-read --include-target
```

用真实清单摘要替换占位符。`review_knowledge_plan_catalog()` 是共用本地 API。默认只输出摘要、数量、准备覆盖/重叠指标；`--include-target` 另行披露目标、Embedding 标签、本批点 ID、缺失与重叠点 ID。始终不输出浮点向量或正文。`artifacts_integrity_verified=True` 只表示本次读取已通过工件内部一致性校验，不认证来源；标签/摘要也可能敏感。

TUI Index plans 页增加 List plans and coverage 按钮及可选清单过滤输入；需要 `READ PLAN`，目标/点 ID 详情另需 `SHOW TARGET`。无需已知某个工件摘要，也不会自动回填审批摘要或触发宿主工厂。确认逐次消费，字段捕获后锁定；结果不是写入许可。布局和交互尚未验收。

## 缺失批次建议

`plan_missing_knowledge_batches(index, coverage)` 是纯规划 API。要求快照摘要、Embedding 标签、维度和完整预期点序列都与清单一致，之后按快照文档顺序对缺失点做稳定贪心分批。默认每批最多 128 文档、实际 Embedding JSON 输入共 1 MiB、向量值总数 1,048,576。可通过 API 调整上述限额；执行准备时须使用相应配置。

返回 `KnowledgePreparationBatch`，含清单摘要、文档 ID、点 ID、输入字节数和稳定批次建议摘要，不含正文或向量。单个缺失文档超限时整次规划失败，不返回部分建议；没有缺失点时返回空元组。已有点只因已暂存而跳过，不代表向量质量已验证。字节数不是 Token 数、价格或预算预留；生成浮点向量后的 Writer 请求大小仍需另行检查。

```powershell
wagent knowledge-plan-batches --plan-database .wagent/knowledge-plans.sqlite3 --source-database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --manifest-digest <清单SHA256> --confirm-read --include-ids
```

`review_missing_knowledge_batches()` 为共用本地 API：读取目录和固定正文快照，验证身份，返回建议；`--include-ids` 才展示可供下一次 `knowledge-plan-prepare --document-ids` 使用的文档 ID。读取正文只为计算准确输入字节，不发送给服务。两个数据库读取不是跨库原子快照或容量预留；并发新暂存可能让建议过时，行动前可重新查看。

此管理入口目前要求计划库已有至少一份该清单的工件；全新清单可以用底层纯 API 的空 `KnowledgePlanCoverage` 规划，或先显式准备首批。缺失批次建议已接 API/CLI/TUI，本地及 headless TUI 回归通过。不自动保存建议、补跑收费调用、创建尝试 ID、授予整批执行许可或处理未知回执。

本地 API 与 CLI 也支持三项限额：`max_documents` / `--max-documents`（1–128）、`max_input_bytes` / `--max-input-bytes`（1–33,554,432）、`max_vector_values` / `--max-vector-values`（1–1,048,576）。参数与库路径分离在读取前校验，结果 `limits` 回显本次规划配置。限额是分批条件，不是执行配置或费用预算；现有本地 prepare 入口仍固定 1 MiB 输入限制，不会因建议调大而自动放宽。

### TUI 缺失批次建议

在 `Index plans` 页填写计划库、正文快照库、精确 namespace/version，以及**必填**清单摘要（与目录过滤共用字段）。批次上限字段可调整，点击 `Suggest missing batches` 前输入独立确认词 `READ BATCH INPUTS`；该动作读取完整计划目录和所选正文快照，只为分析缺失点及输入字节。文档/点 ID 默认隐藏，另输入 `SHOW BATCH IDS` 才披露；正文和向量值始终不显示。

该动作无需宿主绑定，不接受 `READ PLAN` 或 `READ SOURCE` 代替专用确认，也拒绝 `SHOW TARGET`、Embedding、保存、远端执行等无关确认。确认词在捕获时消费，包含失败提交；冻结请求后锁定字段，取消/卸载排空任务。输出不自动填入文档选择或批准字段，后续准备必须另行配置并授权。headless TUI 取消及交互回归已通过；人工布局和生产交互仍待验收。

## 进度与剩余

目录协议、严格 SQLite 读取、覆盖/重叠分析、CLI/headless TUI 目录及可调限额缺失批次建议本地回归通过。

[构建/回执目录与显式安全重试](./knowledge-builds.md)、同库冲突协调及 [ready 准备恢复](./knowledge-build-recovery.md)已实现并有本地回归覆盖。自动收费补跑、pending 重放、跨库租约、准备/主 Run 费用归集、远端核验及生产验收仍不在本实现范围。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
