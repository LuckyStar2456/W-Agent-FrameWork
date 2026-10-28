# 可选文档解析、可追溯导入与预览提交锁

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-import-extensions.en.md) | 简体中文

2.0.0 Experimental，已随 2.0.0 发布。2026-10-01 首轮导入模块回归为 **102 passed / 5 skipped**。用户随后批准在专用虚拟环境安装 pypdf 6.19.0、openpyxl 3.1.5、python-pptx 1.0.2，复用 python-docx 1.2.0；扩展测试重跑 **15 passed，无跳过**。真实 DOCX 完成段落/表格提取→预览→摘要锁定保存→SQLite 检索；真实 PDF 校验非空正文提取，XLSX/PPTX 校验单元格/幻灯片文本。Windows symlink/FIFO 的两个原有测试仍受平台限制。没有模型/付费调用、远端写入或发布；统一结果见[验收记录](./acceptance-2026-10-01.md)。

## 显式选择解析模板

后续已加入可替换的解析 trace SQLite 持久化、精确向量缓存复用与文件级增量 upsert/delete，见[知识同步](./knowledge-sync.md)及其 [CLI/TUI 入口](./knowledge-sync-entries.md)。[原始二进制归档](./knowledge-archives.md)提供独立显式授权的存储模板；普通快照导入不自动归档，也不自动迁移本页的快照索引。

源码安装可选依赖组为 `knowledge-documents`，基础安装不强制引入文档解析库。该新增依赖组尚未随新版 PyPI 包发布。

```python
from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_parsers import OptionalDocumentKnowledgeParser

parser = OptionalDocumentKnowledgeParser(parser_key="host-pinned-parsers-v1")
importer = LocalTextKnowledgeImporter(root, parser=parser, suffixes=parser.suffixes)
loaded = await importer.load(("manual.docx",), confirm_read=True)
```

默认导入器仍只接受 `.txt`/`.md`；显式模板支持 PDF→pypdf、DOCX→python-docx、XLSX→openpyxl、PPTX→python-pptx，仅在所选格式解析时加载依赖。DOCX 按正文段落/表格顺序提取；PDF 提取页文本；XLSX 输出工作表名称及单元格缓存值，公式不计算；PPTX 提取顶层文本框/表格。无 OCR、宏执行、链接下载、legacy `.doc/.xls/.ppt`、页眉页脚/批注/备注完整保真承诺。

单文件读取默认/最大 1 MiB；解析文本最多 1 MiB；Office ZIP 默认最多 4096 项、声明解压合计 32 MiB；XLSX 最多遍历 100000 个单元格。限额不是 CPU/内存沙箱；解析器和目录仍须可信。缺依赖直接使用 parser 时返回固定 `KnowledgeParserDependencyError`；通过导入器调用时依旧统一隐藏解析内部异常。宿主固定依赖版本，解析逻辑/配置改变时更新 `parser_key`。

## 增量解析与变更摘要

`await importer.load(paths, confirm_read=True, previous=loaded)` 仍读取并计算全部所选文件的 SHA-256，仅对相对路径、原始字节摘要/长度及 parser_key 相同的非空文档复用解析结果。空白原文没有保留文档，仍重新解析。`previous` 是可信宿主缓存，摘要不是签名。

`compare_knowledge_imports(previous, current)` 返回 sorted `added/changed/removed/unchanged` 相对路径元组。选择范围缩小时，未选旧路径也计为 removed；这仅是差异报告，不会删除文件、旧版本或远端索引。该入口不是目录 watcher，也不自动做增量 Embedding/向量删除。

## 精确追溯与可导出原文

```python
from w_agent.knowledge_provenance import TracedKnowledgeImport, prepare_traced_knowledge_import

traced = prepare_traced_knowledge_import("manual", "v1", loaded, chunk_bytes=4096)
snapshot = traced.snapshot
archive_json = traced.to_json()  # 含完整解析原文；宿主显式归档时注意权限
restored = TracedKnowledgeImport.from_json(archive_json, expected_digest=traced.digest)
```

`origins` 对应每个快照块，包含原文档 ID、字符和 UTF-8 字节的半开区间。区间指向**解析后的原文**，不是原始 PDF/Office 二进制字节或版面坐标；跳过的空白仍留在原文中。导出包含来源文件指纹、解析原文、快照、分块配置和偏移；重读核对规范 JSON、摘要、来源记录、块切片及重新准备结果。不改变原有快照 JSON/SQLite schema。默认 UTF-8 非重叠策略仍是 trace v1；显式 `splitter="structure", overlap_chars=...` 使用自验证 v2，见[结构/重叠分块](./knowledge-splitting.md)，这是结构启发式而非模型语义理解。trace 与原始二进制均已有独立显式持久化入口；仍不自动归档、不提供跨存储原子提交。

## 预览锁定写入

CLI 首次 `knowledge-import ... --confirm-read` 返回无正文摘要。保存时重用相同参数并加 `--confirm-write --expected-preview-digest <preview_digest>`；需建库时再加 `--confirm-create`。启用文档格式加 `--document-formats`，TUI 也提供对应勾选和摘要输入。

锁包含源根目录、选中路径、递归/格式开关、分块配置、原始/解析摘要、版本内容及目标数据库路径。任何变化返回 `knowledge-preview-conflict`，在数据库初始化前失败；无需创建空库。原文 BOM 等只改变 raw hash 的变化也会失配。它不是用户签名或跨进程锁，不保证保存完成时磁盘源文件仍保持原样；保存的是本次读到且与预览一致的不可变快照。旧的一步确认保存仍可用，结果明确 `preview_locked=False`。

本页旧 `knowledge-import` 管理结果含 `preview_digest`、`trace_digest`，同时明确 `manifest_persisted=False`、`trace_persisted=False`；该入口只保存正文快照。需要持久 trace、结构分块及增量缓存时使用独立 `knowledge-sync-import` / 同步入口和专用库，不把旧命令的限制扩大为整个模块缺失能力；所有入口均不会把正文悄悄输出到 CLI。
