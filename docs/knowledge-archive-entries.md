# 显式本地原始归档管理

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

简体中文 | [English](knowledge-archive-entries.en.md)

工作区实现，已随 2.0.0 发布。这是本地开发者 API/CLI，不是服务平台。复用不可变 trace 存储及[原始归档](knowledge-archives.md)契约，不触发 embedding、模型、解析器、外部代码导入、网络调用、执行、目录恢复或垃圾回收。

## 四种分别授权的操作

`knowledge-archive preview` 从 trace 数据库选择**已经保存**的 namespace/version，读取 trace 并返回 SHA-256 摘要及源文件/blob/字节/chunk 数量。不读取源文件，不创建归档；不输出 namespace 标签、源文件名、绝对路径、提取正文或原始内容。

```powershell
wagent knowledge-archive preview --trace-database traces.db --namespace manual --version v1 --confirm-read
```

结合可信导入记录审核数量与摘要。`save` 必须提供独立批准的该摘要，分别确认读取数据库、读取原始文件和写入归档，并显式选择 source root。`--confirm-create` 可选初始化专用归档库，父目录必须已经存在；不提供时归档库必须存在。trace 库与归档库不能是同一个文件，包括硬链接别名；不会接管无关数据库。

```powershell
wagent knowledge-archive save --trace-database traces.db --archive-database raw.db --root ./sources --namespace manual --version v1 --expected-trace-digest <preview-trace-digest> --confirm-read --confirm-sources --confirm-write --confirm-create
```

先验证所选已存 trace，再读取源文件。manifest 中所有原始文件均须匹配保存时的长度和 hash，之后才初始化或写归档。相同 bytes 按内容 hash 去重；不会超出已存 manifest 扫描目录或扩张路径。空 manifest 合法，可生成空 receipt。SQLite 原子提交 receipt 与 blobs，但导入库和文件系统之间没有跨系统事务。中断时可能已提交，重试前先检查。

`inspect` 只读打开归档，验证 receipt 及所有关联 blob hash，仅输出 trace/receipt/blob 摘要和数量。缺失的数据库不会创建。完整性验证会在内部读取归档 bytes，但不会导出它们。

```powershell
wagent knowledge-archive inspect --archive-database raw.db --trace-digest <trace-digest> --confirm-read
```

`export` 从批准的 receipt 选择**单个 blob**，把原始 bytes 写到一个显式指定的**新文件**。读取、导出和路径需分别确认。写入前校验 receipt 归属、批准的 receipt 摘要和原始内容 hash。不创建目录、不覆盖、不恢复目录、不自动打开或执行。

```powershell
wagent knowledge-archive export --archive-database raw.db --trace-digest <trace-digest> --expected-receipt-digest <receipt-digest> --blob-digest <selected-blob-digest> --destination ./review/original.bin --confirm-read --confirm-export --confirm-path
```

输出只有摘要和字节数，不包含原始 bytes 或目标路径。拒绝既有文件、数据库路径、符号链接、Windows reparse point/junction 和带链接的父目录。排他新建避免截断预检之后才出现的文件。部分写失败时，仅清理 device/inode 身份仍属于本次操作的文件，不删除用户后来替换的文件。无法证明身份或清理失败时可能留下部分文件，错误会明确要求检查。取消会等待已启动的 worker 完成，可能留下已成功导出的文件。

## 管理 API 与扩展边界

`w_agent.knowledge_archive_management` 提供：

- `KnowledgeArchivePreviewRequest` → `preview_local_knowledge_archive`。
- `KnowledgeArchiveCreateRequest` → `archive_local_knowledge_sources`。
- `KnowledgeArchiveInspectRequest` → `inspect_local_knowledge_archive`。
- `KnowledgeArchiveExportRequest` → `export_local_knowledge_blob`。

服务均为 async；必需确认必须是精确布尔值，并在文件系统/数据库访问前检查。请求 repr 隐藏路径和 namespace 标签。返回安全 dict，不返回 trace 或 bytes。`w_agent.knowledge_archive_cli` 的 `register_knowledge_archive_commands(app)` 注册 Typer 子命令组，不自动配置、创建全局实例或加载插件。

此管理模板有意使用既有 SQLite 存储。需要其他实现的应用可组合可替换 `KnowledgeRawArchive`/`KnowledgeImportStore` 协议及 `archive_knowledge_sources`，没有另起存储格式。精确 trace 验证复用已有 `to_json`/`from_json` 契约，不自行重建或假定 chunk offset 布局。SQLite 容量、单原文件和批次限制沿用底层归档。

## 安全与剩余范围

数据库和导出 bytes 均为**明文**，可能包含凭据、个人信息、文档宏、可执行文件或恶意载荷。导出不清洗、不消毒，不应自动打开文件。Hash 仅用于完整性，不提供认证、保密或授权；已知内容的 hash 也可能暴露成员关系。宿主须限制数据库、SQLite sidecar、源根目录和输出目录权限。新文件请求 POSIX `0600` 权限；Windows ACL 仍由宿主管理。

所有路径及祖先目录必须可信且静止。链接/reparse 检查与身份清理不是沙箱，不能防御恶意进程并发替换目录。未实现自动 ACL 加固、加密、保留期/GC、批量目录恢复、跨文件系统事务或后台重试。失败后先检查状态，再决定下一步。

定向验收：`python -m pytest tests/test_knowledge_archive_entries.py tests/test_knowledge_archives.py -q`，**42 项通过**，其中新增管理/CLI 测试 28 项。真实临时 SQLite 和精确原始 bytes 导出覆盖同库/硬链接拒绝、Windows junction 拒绝、缺确认不触 I/O、摘要/源文件漂移、篡改、部分写清理及保留并发替换文件。本次无跳过测试、外部服务调用或安装。
