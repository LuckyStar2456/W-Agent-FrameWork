# 知识增量同步 CLI / TUI 共享入口

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](knowledge-sync-entries.en.md) · [底层同步与持久化](knowledge-sync.md)

`knowledge_sync_management` 提供同一套不可变请求及异步服务，CLI 与 TUI 不另写同步逻辑。完整主路径是本地 UTF-8 文件预览、锁定保存 trace、差异 Embedding / 持久计划、检查、明确授权执行。不会在准备时自动 upsert/delete，也不会在读状态时导入宿主代码。

## 可执行主路径

以下在项目目录使用 `python -m w_agent.cli`，亦可使用已安装的 `wagent`。先创建并保护自己的数据目录；程序不创建父目录。占位摘要必须替换为上一操作真实输出，不能直接运行占位命令。导入 trace 库与同步 journal 必须是两个专用库，不是旧 snapshot 数据库。

```text
python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v1 --trace-database ./data/traces.db --confirm-read

python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v1 --trace-database ./data/traces.db --confirm-read --expected-preview-digest PREVIEW_DIGEST --confirm-record --confirm-create

python -m w_agent.cli knowledge-sync-prepare --host-entry examples.knowledge_sync_host:sync_catalog --binding prepare --trace-database ./data/traces.db --namespace manual --version v1 --expected-trace-digest TRACE_DIGEST --journal-database ./data/sync.db --confirm-code --confirm-read --confirm-embedding --confirm-record --confirm-create

python -m w_agent.cli knowledge-sync-inspect --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --confirm-read

python -m w_agent.cli knowledge-sync-execute --host-entry examples.knowledge_sync_host:sync_catalog --binding execute --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --approved-plan-digest PLAN_DIGEST --approved-upsert-digest UPSERT_DIGEST --confirm-code --confirm-read --confirm-record
```

`examples/knowledge_sync_host.py` 是需要审查/配置的本地 Ollama + Qdrant 装配模板。模型占位名、维度、预处理修订键必须按实际模型修改；集合须已存在且专属于该同步链路。示例导入不会启动服务、下载模型或创建集合；以上命令不是已完成真实服务验收的证据。

文件导入默认只支持已有 UTF-8 文本后缀；显式传入 `--document-formats` 后使用已有 `OptionalDocumentKnowledgeParser`，增加 PDF/DOCX/XLSX/PPTX。TUI 有对应默认关闭的勾选框；依赖按实际格式惰性加载，缺依赖报错、不安装、不回退为二进制文本。不执行宏、公式、OCR 或远端链接；解析器在当前进程运行，仅应处理受信文件。解析器选择、key、限额与 suffixes 进入预览摘要，预览后切换必须重新审查；新版本摘要也会使升级前的临时预览失效，不影响已存 trace/plan。

目录默认不递归，`--recursive` 明确启用递归；重复 `--path` 选多项。不提供 path 表示明确的空 manifest，可用于移除上版全部自有点，绝不是扫描当前目录。trace 本身保存提取文本/来源偏移；原始二进制使用独立、显式授权的[原始文件归档 API](knowledge-archives.md)，导入/同步入口不会自动归档。

预览摘要绑定 trace 内容、namespace/version/分块配置、根目录、路径选择、递归开关和目标数据库。保存重新读取文件并校验摘要，变动则在创建/写库前拒绝。保存后的 `trace_digest` 是准备计划必须明确提供的精确输入摘要。

下一版本再次导入，然后 prepare 增加 `--previous-plan-digest PREVIOUS_PLAN_DIGEST --approved-reuse-digest PREVIOUS_CURRENT_INDEX_DIGEST`。前一计划必须已完成；稳定源身份与相同 Embedding 配置下仅新增/变化块调用 Embedding，版本号变化不会全量重嵌入。完全复用可省略 `--confirm-embedding`，但仍须已授权宿主绑定及精确复用摘要。删除仍只取前一 manifest 自有 ID。

## 独立批准及持久状态

| 操作 | 必要批准 | 副作用 |
| --- | --- | --- |
| import 预览 | confirm-read | 只读选中文件 |
| import 保存 | read、record、expected-preview-digest；建库另 create | 明文 trace 本地持久化 |
| prepare | code、read、record、expected-trace-digest；实际新向量另 embedding，建库另 create | 可产生 Embedding 费用；持久 exact plan 并占用 target |
| inspect | read | 只读，不导入工厂 |
| execute | code、read、record、approved-plan-digest；所需 upsert/delete 各自独立摘要 | 仅发送持久向量和精确删除 ID，逐批持久回执 |
| retry-not-sent | read、record、精确 retry 摘要 | 保留旧代次，将明确未发送批次置为下一代 ready；不发送 |
| reconcile | read、record、精确 plan 摘要、applied、inactive、证据引用 | 宿主声明已完成；不查询远端、不重发 |

`--approved-upsert-digest` 与 `--approved-delete-digest` 本身分别是精确远端动作批准。需要删除时必须另传 `--approved-delete-digest DELETE_DIGEST`；不接受用总计划批准替代。删除的是整个 point，包括其所有命名向量/payload，不能共享集合。空计划在明确 prepare/record 后直接推进 head，不需要远端发送；`finished` 表示本地计划已完成，不宣称远端独立验证。

prepare 先验 trace、库和前版状态，加载工厂后在 Embedding 前只读预检目标 head。已知冲突不会再计费，但该预检不是租约；并发者仍可能在 Embedding 后抢先 stage。准备失败/取消没有 Embedding checkpoint 自动恢复，费用可能已发生；不要盲目重复准备。已成功 stage 的计划使用 inspect/execute 继续，不重新 prepare。计划、trace、向量均明文持久化；UI Clear 只清界面，绝不能删除计划来解锁。

## 显式恢复

inspect 的 `retry_candidates` 只为 `not-sent` 提供 batch、当前失败 generation（初代 0）、`retry_digest`。将审查后的这些值手工传给：

```text
python -m w_agent.cli knowledge-sync-retry-not-sent --journal-database ./data/sync.db --plan-digest PLAN_DIGEST --batch 0 --generation 0 --retry-id retry-1 --approved-retry-digest RETRY_DIGEST --confirm-read --confirm-record
```

之后重新 execute 仍要全部独立批准。旧代次不可覆盖，重试 ID 不能重复，最多 64 次/整个计划；耗尽时 inspect 仍成功并返回 `retry_exhausted: true`。pending/unknown/acknowledged 从不生成重试候选，也不会因重复 execute 而重放或推进 head。

只在宿主独立证实已应用且原请求已终止、迟到效果已排空时，才可使用 `knowledge-sync-reconcile --journal-database ... --plan-digest ... --approved-plan-digest ... --batch ... --evidence-ref ... --confirm-read --confirm-record --confirm-applied --confirm-inactive`。此命令仅记录宿主声明，不验证证据真实性；不能虚报完成以解锁。未知结果的 not-applied reset/撤销仍未提供。

## 共享管理接口与生命周期

请求类 `KnowledgeSyncImportRequest/PrepareRequest/InspectRequest/ExecuteRequest/RetryRequest/ReconcileRequest` 对应 `import/prepare/inspect/execute/retry/reconcile_local_knowledge_sync`。`knowledge_sync_summary(plan,status)` 是纯函数，只输出摘要、namespace/version、数量、批次动作/状态，不含正文、向量、源路径、目标 URL、模型键、operation_id 或证据引用。

宿主复用 `KnowledgeIndexHostOptions` / `KnowledgeIndexHostBinding` / `knowledge_index_host_scope`：明确 `confirm_code` 后导入 `module:factory`，工厂返回异步上下文并提供命名绑定；prepare 需要配置了 embedder/修订键/维度的 binding，execute 可仅提供 writer。工厂负责资源清理。取消/错误不被 cleanup 吞掉，cleanup 失败可能发生在远端成功之后，应先 inspect 持久回执。授权宿主代码不是沙箱，宿主工厂自身的任意副作用仍由操作者信任负责。

TUI 使用同一服务，界面收集与消耗一次性确认词及手填摘要，不将预览值自动当成授权。恢复命令先通过 CLI 使用；不提供自动重试。所有参与者须共享同一个 journal，canonical endpoint 检查不能识别真实 DNS 别名/代理同址，也不能约束其他 writer。这不是全局/远端锁。

## 本轮验证与剩余边界

2026-10-01 现有干净 Python 3.11 环境定向命令 `python -m pytest -q tests/test_knowledge_sync_management.py tests/test_knowledge_sync_cli.py tests/test_knowledge_sync.py`：**55 passed**（management 16、CLI 8、底层 31）。使用真实临时 SQLite 与注入传输，覆盖预览锁、增量链路、独立删除授权、重复 prepare 前置拒绝、generation 0 恢复/64 次耗尽、unknown/ack 防重放、取消清理、目标不符和 cleanup 后回执保留。该数字不与其他重叠回归相加，也不挪用上一轮全量结果。

后续格式/归档轮次新增真实 PDF/DOCX/XLSX/PPTX 追溯导入及原始字节归档用例，CLI/TUI 显式 DOCX 开关也有定向回归；最终数量见本轮主任务合并记录，不用上述旧 55 项证明新能力。真实 Ollama/Qdrant 服务、费用/质量评测、人工交互式 UI、跨进程以外的远端协调均未由本页验收。当前 CLI 不提供语义分块或归档操作命令；归档为单独的可替换 Python API，无自动还原/覆盖能力。
