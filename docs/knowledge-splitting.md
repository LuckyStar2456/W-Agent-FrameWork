# 结构优先与重叠分块

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](knowledge-splitting.en.md) · [同步入口](knowledge-sync-entries.md) · [原始归档](knowledge-archives.md)

工作区提供无 I/O 的 `KnowledgeSpanSplitter` 协议和 `StructureKnowledgeSpanSplitter` 模板。模板按段落/句子标点优先切分，保留原文，不调用模型、Embedding、网络或分词服务。这是结构启发式，不是 Embedding 语义理解，也不承诺检索质量改善。

## 使用与边界

```python
from w_agent.knowledge_splitters import StructureKnowledgeSpanSplitter
from w_agent.knowledge_provenance import prepare_traced_knowledge_import

splitter = StructureKnowledgeSpanSplitter(max_chunk_bytes=4096, overlap_chars=128)
spans = splitter.split_spans(text)
chunks = splitter.split(text)  # 兼容现有 KnowledgeTextSplitter，span 是权威位置

trace = prepare_traced_knowledge_import(
    "manual", "v2", imported,
    chunk_bytes=4096, splitter="structure", overlap_chars=128,
)
```

`KnowledgeTextSpan` 是半开 `[char_start,char_end)` / `[byte_start,byte_end)`，分别对应原始提取文本的 Unicode 字符索引与 UTF-8 字节索引。不是 token、grapheme、PDF 页坐标或原始 Office/PDF 二进制偏移。中文/emoji 不会被切成无效 UTF-8，但组合字符/ZWJ 序列可跨块。

每个窗口先计算严格 UTF-8 上限，在窗口后半区优先取最后一个段落空行结束，否则取最后一个句末，再否则按完整字符硬切。若剩余文本已在上限内则直接保留。英文句末采用 `.?!` 后的空白/行尾，中文采用 `。！？`；缩写、代码、表格及无标点语言没有语义识别。保留空白，不做规范化；纯空白块不输出，所有非空白原字符仍被覆盖。

下一窗口最多重叠 `overlap_chars` 个 Unicode 字符；必要时缩短以保持严格推进。参数必须是整数（不接受 bool），`4 <= chunk_bytes <= 1 MiB`，`0 <= overlap_chars <= min(1024, chunk_bytes // 8)`。保守的半窗口规则为最坏四字节字符预留空间，故小字节窗口不能配置过多 ASCII 重叠。跨度 start/end 均严格递增，不循环、不重排，单输入最多 1 MiB、1024 块，整份 trace 最多 1024 块且输出连同元数据受既有 16 MiB 限制；超限整体拒绝，不悄悄截断。大量重复文本的位置来自 span，不依赖搜索相同字符串。

`KnowledgeSpanSplitter` 可由宿主替换并纯组合使用；模板同时实现已有 `KnowledgeTextSplitter.split`。持久 trace 目前仅接受内建 `utf8` / `structure` 确定算法，不从存档加载任意 Python 或分块插件；自定义 span 分块的持久 codec/注册仍需后续显式设计。

## 版本与稳定身份

默认 `splitter="utf8", overlap_chars=0` 仍调用原非重叠分块链路，输出 `wagent-traced-knowledge-import-v1`，原 `to_json` 字节、digest、snapshot IDs 与 `wagent-knowledge-sync-point-v1` 算法不变。UTF-8 legacy 模式拒绝非零 overlap。

结构模式产生 `wagent-traced-knowledge-import-v2`，增加严格 `splitting` 对象：`algorithm="structure-v1"`、`chunk_bytes`、`overlap_chars`。载入验证摘要、字段集合、原文切片、char/byte 偏移、上限与推进关系，并用内建算法重建整个 snapshot/origins 后比较规范序列化；即便重新计算外层哈希，篡改策略、偏移、配置或块内容也拒绝。

v2 snapshot chunk ID 和同步 `point-v2` 均绑定完整分块配置及源 span。改变策略/重叠参数，即便刚好输出相同文本也不会复用错误身份。相同源和配置仅改变 snapshot version，稳定同步点 ID 保持相同，可复用前版已批准的向量。更换策略可能导致全量相关源点重嵌入并删除旧 ID，这是明确配置变更，不是“增量只变版本”。旧 snapshot/index 不自动迁移。

trace store、sync index/plan 与 raw archive 无须改 SQLite schema：它们通过严格 `TracedKnowledgeImport.from_json/to_json` 读写 v1/v2。raw archive 仍绑定精确 trace digest，保存原始 bytes，不把重叠内容另存成原文件。

## CLI / TUI / 管理服务

`KnowledgeSyncImportRequest` 末尾新增 `splitter="utf8"`、`overlap_chars=0`，保持既有位置参数兼容。CLI 示例（摘要/保存审批沿用同步入口）：

```text
python -m w_agent.cli knowledge-sync-import --root ./manual --path . --namespace manual --version v2 --trace-database ./data/traces.db --chunk-bytes 4096 --splitter structure --overlap-chars 128 --confirm-read
```

如需 PDF/Office，再显式加 `--document-formats`；结构分块作用于提取文本。TUI 新字段“Splitter: utf8 or structure”和“Structure overlap characters”默认 `utf8` / `0`，不自动选择结构策略或授权读取。预览摘要绑定所有分块配置；保存前改策略/参数/源文本必须重新预览。默认 v1 预览算法保持原样。

管理入口在 worker 内做纯 CPU 分块，避免阻塞 TUI 事件循环。取消会等待已启动 worker 结束，随后传播取消且不继续创建/保存 trace；这不是强制终止线程。其他既有 SQLite/远端操作取消仍不代表回滚。

## 本轮验证与剩余

2026-10-01 现有干净 Python 3.11：新 `tests/test_knowledge_splitting.py` 40 项、`tests/test_knowledge_splitting_tui.py` 1 项，加相关导入/sync/management/原始归档/四格式/TUI 共 **137 passed**（17.45s，无 skip）；六个改动模块 compileall 通过。覆盖 legacy v1 字节/ID 参考算法、v2 严格重建、重复文本/中文/emoji、极端 overlap/输出上界、相同输出不同配置 IDs、预览锁、取消不保存、真实 CLI/TUI v2 持久重开、增量零重复 Embedding 及 raw archive 往返。最终合并证据由主任务汇总；不与重叠测试数相加。

未使用外部模型/付费服务，未安装依赖、发布或运行全量。语义模型分块、多语言句法、质量收益、人工真实服务 UI 与可恢复自定义分块 codec 均未验收/未提供。
