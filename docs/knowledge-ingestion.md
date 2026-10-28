# 纯文本知识准备与版本化 SQLite 快照

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-ingestion.en.md) | 简体中文

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。2026-10-01 首轮导入模块定向回归 102 passed / 5 skipped，覆盖临时 SQLite 建库、固定版本检索及真实 DOCX 导入链路。新增[可追溯导入扩展](./knowledge-import-extensions.md)保留解析原文和精确块偏移；原有 `KnowledgeSnapshot` 格式不变。本页早期剩余项以扩展页为准。

## 从宿主文本到固定版本

`prepare_knowledge_snapshot(namespace, version, documents, splitter=...)` 接收宿主已读取/解析的 `KnowledgeDocument` 元组，返回不可变 `KnowledgeSnapshot`。默认纯本地分块，不读取文件、扫描目录、下载来源、加载第三方解析器或调用 Embedding。

需要读取本地文本时，可另行使用已通过本地回归的[文件/目录导入器](./knowledge-files.md)，显式授权读取后将 `loaded.documents` 传入本函数；准备和保存快照不会反向触发导入。

`KnowledgeTextSplitter.split(text)` 是可替换同步协议。默认 `Utf8KnowledgeTextSplitter(max_chunk_bytes=4096)` 按 UTF-8 字节上限切块，不切断 Unicode 码点，不重叠、不做文本正规化；纯空白块跳过，其余块内字符保持原样。它不是语义分块、句子分块、字素簇分块或 Token 分词，组合字符/emoji 序列仍可能跨块。上限可设为 4 字节至 1 MiB，单篇最多 1024 块。

```python
from w_agent import (
    KnowledgeDocument, SQLiteKnowledgeSnapshotStore, Utf8KnowledgeTextSplitter,
    KeywordKnowledgeRetriever, knowledge_search_tool, prepare_knowledge_snapshot,
    ToolSideEffect,
)

snapshot = prepare_knowledge_snapshot(
    "客服手册", "试验方案 A",
    (KnowledgeDocument("refund", "示例：退货期限为七天，并非真实业务政策。", "sample:refund", "退货说明"),),
    splitter=Utf8KnowledgeTextSplitter(max_chunk_bytes=4096),
)

# 父目录必须由宿主预先准备；构造时不建库。
versions = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
await versions.initialize(confirm_create=True)
digest = await versions.save(snapshot, confirm_write=True)

# 重开进程后仍明确指定版本；没有自动 latest。
reopened = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
pinned = await reopened.load("客服手册", "试验方案 A")
documents = pinned.as_document_store()
binding = knowledge_search_tool(
    KeywordKnowledgeRetriever(documents), side_effect=ToolSideEffect.READ,
)
```

`binding` 继续接入[知识工具](./knowledge-tools.md)的注册表/Runtime 通道；`KeywordKnowledgeRetriever(documents)` 也可传入[知识上下文策略](./knowledge-context.md)。已加载的内存文档集固定为该快照，不随其他进程新增版本而改变。无需常驻连接或 `aclose()`；每次 SQLite 操作各自关闭连接。

## 身份、内容与版本语义

- namespace 与 version 是用户自定的精确标签，支持中文，各最多 128 UTF-8 字节，不得全空白或含 ASCII 控制字符。不会自动修剪、正规化、按语义版本比较或当作文件路径；相同标签的大小写/空格差异有意义。namespace 仅为本地分组，不是租户、ACL 或服务平台边界。
- 准备函数输出的 UUID 字符串由格式版本、namespace、version、原文档 ID、块位置、块正文、source、title 的规范 JSON SHA-256 前 128 位生成。变更任一绑定字段会改变 ID；与 Qdrant ID 格式兼容，但不代表已建向量索引。跨不同原文档的排序改变不改变各自块 ID，但会改变整体快照摘要。
- source/title 保留为不可信引用信息，不自动打开或验证。准备后的文档不额外存储原始文档 ID、字节偏移、分块器实现版本或完整原文；UUID 不可反向恢复这些信息。可另存本地导入器的文件级来源指纹；独立[可追溯导入扩展](./knowledge-import-extensions.md)已保留解析原文与精确块偏移；原始二进制仓库及清单自动持久化仍在计划中。
- `KnowledgeSnapshot(namespace, version, documents)` 也可直接构造，以保留宿主自己的 ID/分块结果。该方式不替宿主生成版本绑定 ID；避免跨版本复用同一向量点时覆盖其他版本。
- 快照字段不可变，正文不出现在 repr，标签仍可见。`to_json()` 显式输出包含全文的规范 JSON；`digest` 是该序列化文本的 SHA-256，覆盖顺序、类型、正文和引用。摘要/UUID 不是签名、秘密、授权或匿名化，也不能抵抗攻击者同时篡改内容和摘要。
- 同 namespace/version 的相同规范内容再次保存返回同一摘要；不同内容返回 `knowledge-version-conflict`，不覆盖已有版本。新内容需显式新版本名，没有删除、自动迁移、自动合并、覆盖、回滚或自动选取最新版。

## 存储与错误边界

`KnowledgeSnapshotStore` 提供可替换的异步 `save(..., confirm_write=...)` / `load(namespace, version)` 协议；SQLite 模板额外提供显式初始化。

- 构造和准备不建库；`initialize(confirm_create=True)` 才创建/核对专用数据库。已有其他应用数据库、未知 application/schema 版本或变化的表定义会被拒绝，不自动采用或迁移。读取使用只读连接，save 使用现存数据库，不自动创建父目录或丢失的库。
- `confirm_create` 与 `confirm_write` 必须为字面布尔 True。它们是宿主显式调用边界，不是可信用户签名或沙箱；不可由模型/共享工程的声明自动推导许可。文档正文会明文保存在 SQLite 文件，宿主负责路径权限、备份、磁盘加密和清理。
- `BEGIN IMMEDIATE` 使版本冲突检查与写入处于同一事务；多进程同时写入不同内容的同版本时只能有一个成功。外部向量索引与此数据库不在同一事务，不提供跨存储原子性。
- 每批输入/快照最多 1024 篇或块，文档字段总大小最多 16 MiB，规范序列化快照最多 32 MiB。单篇正文继续受 1 MiB 限制。自定义分块结果也需为非空、无空白正文的有界字符串元组，整体扩张有界；空输入允许形成空快照。
- SQLite 默认接收最多 1024 个快照、总 payload 256 MiB，可由宿主显式调整 `max_snapshots`（至 4096）和 `max_total_bytes`（至 2 GiB）。这些是写入接纳限制，不是物理数据库/事务日志/进程内存/Token 配额；相同内容的重复保存不会另占版本。重开时可使用不同接纳限额，现有版本不会因此删除。
- load 先限制 payload 字节数，再核对摘要、JSON 字段/重复键、文档约束及请求标签。读取时损坏或不匹配失败，不返回部分文档，不修改存储。数据库及其父目录仍必须可信；这不是针对恶意 SQLite 文件的隔离解析器。
- 默认 `timeout=5` 秒是 SQLite 锁等待参数，不是整个操作的强制截止时间。I/O 运行在线程中，取消后等待已启动线程完成并关闭连接，再传播 `CancelledError`；不能强制停止事务或假定已回滚，取消时仍可能已提交。应用退出/进程崩溃另由 SQLite 和宿主恢复处理。
- `KnowledgeStoreError.code` 是固定错误标识，不回显路径/正文。`may_have_written=True` 表示写入阶段已进入而成功未确认，不能据此重试覆盖；应 load 对应版本核对摘要。初始化失败可能遗留空文件。取消使用独立异常，同样应核对存储结果。没有自动重试。
- 默认分块器与 SQLite 不产生模型费用；自定义同步分块器是可信宿主代码，可自行产生副作用或阻塞，框架不隔离它。字符/字节限制不是 Token 预算，后续 Embedding 或模型调用仍需另行授权、计量。

## 本轮进度与剩余

纯文本准备与 SQLite 快照本地回归通过，覆盖 UTF-8、身份、重开、冲突/并发、容量、损坏和取消。

本地[文件导入](./knowledge-files.md)、[快照向量准备](./knowledge-vectors.md)和[回执日志](./knowledge-index-journal.md)均有本地回归覆盖，保存正文快照不会自动触发这些操作。[导入扩展](./knowledge-import-extensions.md)已提供可选 PDF/Office 解析、解析原文/偏移及增量解析复用，管理 CLI/TUI 也已接入。剩余为原始二进制仓库、追溯自动持久化、语义/重叠分块、更多 Embedding 模板、远端证据/核验、跨存储同步和真实端到端验收。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
