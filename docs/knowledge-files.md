# 本地文本文件与目录导入

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-files.en.md) | 简体中文

状态：2.0.0 `Experimental`，已随 2.0.0 发布，不属于 `2.0.0a9`。2026-10-01 首轮导入模块定向回归 102 passed / 5 skipped；真实 DOCX 导入、保存和检索已通过。可选解析、可追溯分块、增量解析复用与预览提交锁见[导入扩展](./knowledge-import-extensions.md)。本页基础模板默认仍为 UTF-8；早期剩余项以扩展页为准。后续已获批准在项目专用临时虚拟环境安装可选解析依赖，四类真实解析验证见扩展页；已随 2.0.0 发布。

## 显式读取，单独保存

`KnowledgeFileImporter.load(paths, confirm_read=...)` 是可替换异步协议。`LocalTextKnowledgeImporter` 提供本地文本模板，返回不可变 `KnowledgeTextImport`，不保存数据库、不生成 Embedding、不写入索引、不运行导入文件中的代码。

```python
from pathlib import Path
from w_agent import (
    LocalTextKnowledgeImporter, SQLiteKnowledgeSnapshotStore,
    Utf8KnowledgeTextSplitter, prepare_knowledge_snapshot,
)

# 宿主选择一个可信、读取期间不被其他进程修改的目录。
importer = LocalTextKnowledgeImporter(Path("my-knowledge"), recursive=True)
loaded = await importer.load(("manuals", "faq.txt"), confirm_read=True)
snapshot = prepare_knowledge_snapshot(
    "客服知识", "本地试验 A", loaded.documents,
    splitter=Utf8KnowledgeTextSplitter(max_chunk_bytes=4096),
)

# 这是另一项授权，不由读取许可推导；父目录须已存在。
store = SQLiteKnowledgeSnapshotStore("knowledge.sqlite")
await store.initialize(confirm_create=True)
await store.save(snapshot, confirm_write=True)

# 显式序列化来源清单，由宿主决定如何保存；此调用不写文件。
source_manifest = loaded.to_manifest_json()
```

保存后按现有[快照文档](./knowledge-ingestion.md)固定版本读取，或接入[快照向量](./knowledge-vectors.md)。SQLite 正文库不会附带保存 `loaded.records`，宿主需将来源清单与快照摘要关联保管；尚无跨存储原子提交或专用清单仓库。

## 选择、读取与限额

- 构造只保存绝对 root 和配置，不访问文件系统。`confirm_read` 必须为字面布尔 True；它是宿主调用边界，不是用户身份认证、模型授权或沙箱。空选择 `()` 返回空结果，不探测 root。
- paths 为最多 1024 个唯一相对路径的元组，用 `/` 分隔；`.` 显式选择整个 root 目录。拒绝绝对路径、盘符、反斜杠、`..`、空组件、通配符、控制字符、冒号/备用数据流及结尾点/空格。路径按原样区分；不会自动正规化大小写或 Unicode。
- 默认只接纳 `.txt`、`.md`，扩展名匹配不区分大小写，可显式配置其他后缀。目录中未匹配的文件跳过；直接指定未支持后缀的文件报错。后缀筛选不是内容安全检查或秘密扫描。
- `recursive=False` 默认只扫描所选目录第一层。显式列出一个子目录仍会扫描该子目录。`include_hidden=False` 跳过扫描中的点开头/Windows hidden 条目；直接指定隐藏路径会拒绝。开启后可能读取 `.env` 等敏感内容，宿主须审查选择及后缀。
- 接纳文件按相对路径排序。重叠选择遇到同一相对路径只读取一次；未声明对硬链接、不同大小写拼写或其他文件系统别名进行内容去重。
- 默认最多 128 个文件、4096 个枚举条目、16 层目录、单文件 1 MiB、原始字节合计 16 MiB；解析文本单篇/合计也受配置字节限额约束。配置上限分别为 1024、65536、64、1 MiB、16 MiB。隐藏/未匹配条目仍消耗枚举额度；超限失败，不静默截断。
- 最终文档还受既有 1024 篇、含 ID/source/title 的 16 MiB 限额约束。文件数包含空白文件；正文最大值并不保证加上引用后仍能接纳。读取前检查选中文件大小，读取时再以限额加 1 字节探测增长。
- root 及祖先、所选路径组件拒绝符号链接和 Windows reparse point；仅读取普通文件，拒绝设备/FIFO 等。可用时启用 `O_NOFOLLOW`，并核对打开前后文件身份、大小和修改时间。未匹配/未递归的链接可能被跳过，但不会有意跟随。
- 这些检查不是跨平台无竞态的路径隔离：root、祖先、文件及解析器必须可信，读取期间不得被并发替换。硬链接、挂载点、网络文件系统和具有文件系统写权限的攻击者不构成隔离边界；需要强隔离时由宿主放入沙箱。
- 文件集合不具备原子快照语义；检测到变化会失败，但没有检测到不证明内容始终不变。失败不返回部分结果、不自动重试；此前已读取的数据或已执行的自定义解析器副作用无法撤销。

## 解析与来源身份

`KnowledgeFileTextParser` 定义 `parser_key` 与同步 `parse(data, relative_path=...) -> str`。默认 `Utf8KnowledgeFileParser` 严格解码 UTF-8，移除一个初始 BOM，保留 CR/LF 和其余字符，不替换坏字节、不执行 Markdown/脚本，拒绝 NUL。空文件或解析后纯空白文件仍有来源记录，但不生成 `KnowledgeDocument`。

宿主可以注入自己的解析器并显式设置接纳后缀。`parser_key` 是最多 128 UTF-8 字节的宿主版本标签，不验证实际实现；自定义解析器是受信代码，运行在线程内，可能阻塞或产生副作用，需宿主自行审核/隔离。接口预留 PDF/Office 等解析能力，首个模板并未实现这些格式。

每个 `KnowledgeFileRecord` 保存相对路径、原始 SHA-256/字节数、解析文本 SHA-256/UTF-8 字节数和可空文档 ID。文档 ID 是格式版本、相对路径、原始摘要、解析摘要和 parser_key 绑定的确定性 UUID；移动到相同结构的另一 root 不改变身份，改路径/原始字节/解析文本/解析器标签会改变身份。source 为 `local:<相对路径>`，title 为文件名；source 是引用，不是自动打开的 URL。

`to_manifest_json()` 显式输出规范来源清单，不含绝对 root、正文或原始文件；`digest` 是此清单 SHA-256。默认 repr 隐藏正文和相对路径，显式 JSON 不隐藏路径/摘要。它们不是签名、匿名化或秘密；低熵正文可被摘要猜测。来源清单没有归档原文件，也没有原文字节到分块的偏移映射；不能据此反向恢复丢失原文。

## 取消与剩余工作

读取/解析在线程中运行。取消后排空已启动工作并关闭句柄，再传播取消；不能强行停止阻塞文件系统或任意解析器，外部超时不是即时停止保证。固定 `KnowledgeFileImportError` 不回显路径、正文或解析器异常细节。

权限、路径、UTF-8/BOM、选择范围、限额、来源指纹、源变化、解析器替换和取消本地回归通过；Windows 链接/FIFO 测试仍有平台跳过。[导入扩展](./knowledge-import-extensions.md)已提供可选 PDF/Office 解析、解析原文/偏移、增量解析复用及 CLI/TUI 摘要锁定提交。原始二进制仓库、追溯/缓存自动持久化、向量差异同步、OCR、语义分块和生产验收仍未完成。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
