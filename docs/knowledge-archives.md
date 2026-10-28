# 原始知识文件归档

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](knowledge-archives.en.md) · [同步入口](knowledge-sync-entries.md) · [归档管理 CLI](knowledge-archive-entries.md)

`knowledge_archives` 提供可替换 `KnowledgeRawArchive` 协议与本地 `SQLiteKnowledgeRawArchive` 模板。它单独保存原始字节，不替代 trace 中的提取文本/来源偏移，也不改变索引身份。默认不读源、不建库、不归档、不恢复覆盖任何文件。

## 显式工作流

已提供 `wagent knowledge-archive preview/save/inspect/export`，按已存 namespace/version 审查摘要、分别确认原文件读取和归档写入，并支持 receipt 只读检查及单 blob 原始 bytes 导出。导出只写显式指定的新文件，不覆盖、不跟随链接、不自动执行；**单文件导出不是目录还原**。管理 API、独立授权与失败清理边界详见[归档管理入口](knowledge-archive-entries.md)。下例仍展示可替换底层协议。

先通过同步入口保存并审查 trace；宿主从 `SQLiteKnowledgeImportStore.load(namespace,version)` 载入。摘要必须是操作者独立批准的那个版本，不能将刚读到的 `trace.digest` 自动当作授权。

```python
from pathlib import Path
from w_agent.knowledge_archives import SQLiteKnowledgeRawArchive, archive_knowledge_sources

# 仅在独立批准创建本地归档库后运行；父目录必须已存在。
archive = SQLiteKnowledgeRawArchive(Path("data/raw-archive.sqlite3"))
await archive.initialize(confirm_create=True)

# trace 是已经载入并验证的 TracedKnowledgeImport。
# approved_trace_digest 来自主机独立审查，不从 trace 自动填入。
receipt = await archive_knowledge_sources(
    trace, Path("manual"), archive,
    expected_trace_digest=approved_trace_digest,
    confirm_read=True, confirm_write=True,
)

# 只读原始 bytes；返回最多 1 MiB 的完整内存对象，不执行/解析。
saved = await archive.receipt(approved_trace_digest, confirm_read=True)
raw = await archive.load(saved.blob_digests[0], confirm_read=True)
```

`archive_knowledge_sources` 先用精确批准摘要 roundtrip 验证完整 trace，再只读 manifest 中的全部原文件。它复用导入器的路径/链接限制：拒绝路径穿越、链接/reparse 源与非普通文件，校验打开前后 stat、字节长度及 SHA-256 raw digest。全批源数据均通过后才调用 archive.save；任一源已变化、缺失或超界，整个存储调用都不发生。源树仍需可信：这不是面对恶意并发目录替换的文件系统沙箱。

相同内容只保存一份，键为原始字节 SHA-256。`KnowledgeArchiveReceipt` 绑定精确 trace 摘要与有序唯一 blob digests；trace 本身保存每个源路径→raw digest/长度映射。receipt 自有版本化摘要随库持久保存，重开校验关联摘要和每个 blob 内容。receipt 不披露源路径，调用方须保留相应 trace。底层 `save(receipt,blobs)` 是受信主机 API；自行构造 receipt 是宿主声明，不能凭任意摘要认证来源，应优先使用上述验证完整来源的 helper。

## 存储、替换与授权边界

- `KnowledgeRawArchive.save` 接收完整已验证批次及 receipt；`load` 与 `receipt` 都需要 `confirm_read=True`，写入需要独立 `confirm_write=True`。构造不 I/O，初始化另需 `confirm_create=True`；读取缺失库不创建文件。
- SQLite 使用独立 application_id、user_version 1 的三表 schema；不接受其他知识库、不迁移、不覆盖已有 blob/receipt。已有精确对象保存幂等；相同 trace 关联不同 blob 拒绝。
- 单 blob 最多 1 MiB，单源批次最多 1024 文件/16 MiB；默认最多 4096 唯一 blob、1024 trace、512 MiB 逻辑 payload。SQLite 批次在一个事务内校验容量并插入 blob/关联；失败不保留部分批次。计数限额不是物理磁盘/WAL 或解析器资源配额。
- 自定义 store 可以替代模板，但需自行提供耐久、原子性与权限语义；helper 检查返回 receipt 精确相等。没有跨 trace/sync/raw 三库事务，也不回滚之前已成功的 trace 导入或模型费用。
- 所有 raw 内容明文保存，可能含宏、敏感元数据、隐藏工作表或未提取信息。底层归档只把 bytes 当数据，不解压、不解析、不加载依赖、不请求网络、不写出源文件、不自动还原。独立管理导出可以写出单个新文件，其中内容可能可执行或含宏，组件不会打开/执行；若宿主交给别的软件，需另行授权与安全处置。
- 取消会等待已启动的 SQLite/文件 worker；写入可能已经提交。SHA-256 是完整性校验，不是认证、签名或防恶意管理员篡改。文件、父目录与 SQLite 权限由宿主保护。无删除/GC、云存储模板、保留策略或自动同步归档。

## 底层归档增量证据

更新的管理 API/CLI 定向验收见[归档管理入口](knowledge-archive-entries.md)，不与下列已有底层测试集合相加。

2026-10-01 现有干净 Python 3.11，定向 `tests/test_knowledge_archives.py tests/test_knowledge_sync_formats.py tests/test_knowledge_sync_management.py tests/test_knowledge_sync_cli.py tests/test_tui_knowledge_sync.py`：**58 passed**（11.74s，无 skip）。包含真实本地 PDF/DOCX/XLSX/PPTX→trace→原始字节对等归档、CLI/TUI DOCX 开关、选择/配置/源漂移锁、去重重开、独立授权、容量原子拒绝、损坏拒绝、空版本、错误自定义 receipt、非普通源文件及其他数据库拒绝。四个改动模块 compileall 通过。与旧轮次/其他重叠集合不相加，最终以主任务合并定向结果为准。无真实外部服务、费用/质量验收、依赖安装或发布。
