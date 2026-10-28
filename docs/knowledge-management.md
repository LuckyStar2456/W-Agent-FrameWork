# 本地知识管理入口

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](./knowledge-management.en.md) | 简体中文

2.0.0 Experimental，已随 2.0.0 发布，不属于 2.0.0a9。2026-10-01 首轮导入定向回归 102 passed / 5 skipped，包括管理 API、CLI、TUI 现有回归及真实 DOCX 导入保存检索；不是人工 GUI 验收。新增 `--document-formats` 与 `--expected-preview-digest`，详见[导入扩展](./knowledge-import-extensions.md)。

## 能力与边界

`LocalKnowledgeRequest` 捕获一次操作；`manage_local_knowledge(request)` 是 CLI/TUI 共用的本地模板，不是后台服务。默认复用 UTF-8 `.txt`/`.md` 导入器，也可显式启用 PDF/Office 可选解析模板；使用 UTF-8 分块、不可变 SQLite 快照和本地关键词检索。不加载宿主工厂、不调用模型/Embedding、不操作远端索引、不自动修改 Runtime 配置。

底层导入器、分块器、快照存储和检索器仍可替换；该便利入口目前固定使用内置实现。新增可选 `KnowledgeSnapshotCatalog` 协议及 `KnowledgeSnapshotInfo`，不会要求现有 `KnowledgeSnapshotStore` 插件新增方法。

## CLI

```powershell
# 只读取与预览，不打开/创建数据库
wagent knowledge-import --database .wagent/knowledge.sqlite3 --root ./manuals --path faq.md --namespace support --version draft-1 --confirm-read

# 重新读取源文件，准备并保存；父目录必须已存在
wagent knowledge-import --database .wagent/knowledge.sqlite3 --root ./manuals --path faq.md --namespace support --version draft-1 --confirm-read --confirm-write --confirm-create

wagent knowledge-list --database .wagent/knowledge.sqlite3 --namespace support --confirm-read
wagent knowledge-search --database .wagent/knowledge.sqlite3 --namespace support --version draft-1 --query refund --confirm-read
# 需要正文时另加 --include-text
```

- `--path` 可重复，使用 POSIX 相对路径；显式 `--path .` 选择根目录，递归另需 `--recursive`。隐藏项默认关闭，链接/重解析点拒绝；不是文件系统沙箱。
- 所有操作要求 `--confirm-read`。导入默认只返回文件/文档/分块数量、版本和摘要，不展示正文，也不保存导入清单。
- `--confirm-write` 才保存；`--confirm-create` 还须配合写入确认。缺少建库确认时只打开已有库，不隐式创建文件或父目录。已有版本只能同内容幂等写入，冲突不覆盖。
- 预览和保存是两次独立读取，不是锁定预览摘要的提交协议。源文件可能变化，需核对最终返回摘要。导入清单摘要并不等于清单已归档。
- 目录按命名空间/版本字典序显示，最多 4096 项，超出则报错而非静默截断；不推断“最新”。`body_integrity_verified=false` 表示只读取库中声明的摘要和字节数，不证明正文完整或可信。
- 检索要求明确命名空间、版本和查询；先加载并校验该快照的规范序列化与摘要。默认只输出匹配 ID、来源和标题；`--include-text` 才显示正文。读取许可已经允许读取正文用于检索，展示许可另管输出。标题/来源/标签也可能敏感；完整性不是来源认证。
- JSON 输出转义非 ASCII 和控制字符，避免正文成为终端控制序列。失败不回显原始文件/数据库异常或正文。取消或失败后写入可能已经发生，先检查准确版本再决定是否重试；创建和保存不是一个原子事务。

默认继承文件导入器的限额：128 个文件、单文件 1 MiB、总原始/解析文本各 16 MiB；分块默认 4096 UTF-8 字节（`--chunk-bytes`），快照总块数不超过 1024。详见[文件导入](./knowledge-files.md)和[快照存储](./knowledge-ingestion.md)。可信目录应保持稳定，不能将链接检查当作对恶意并发文件替换的隔离。

## TUI

Knowledge 页提供数据库、命名空间、固定版本、导入根目录、相对路径 JSON 数组、分块大小、查询和结果数量。

每次操作输入 `READ KNOWLEDGE`；导入保存还需 `WRITE KNOWLEDGE`，建库再加 `CREATE KNOWLEDGE`；检索显示正文需 `SHOW TEXT`。确认词每次捕获后清空，错误拼写会拒绝。导入预览/版本目录/固定检索三个按钮共用管理 API，未切换页面就自动读取的行为不存在。相对数据库/根目录以 TUI 工作区为基准，CLI 相对路径则以调用目录为基准。

请求捕获后字段锁定，在后台协程执行；取消或退出会等待已经开始的存储/文件线程结束，不声称撤销已提交写入。取消后提示先核对版本。结果只展示在当前面板，不自动写日志；终端历史、截图等仍由用户管理。headless TUI 回归已通过；人工布局和生产交互效果仍待验收。

## 与 Agent 装配

该管理页和 [Run 知识上下文](./knowledge-runtime.md) 是两个入口。宿主仍需在受信工厂里显式 `await SQLiteKnowledgeSnapshotStore(path).load(namespace, version)`，将快照构建的 `KeywordKnowledgeRetriever(snapshot.as_document_store())` 包装为 `LocalKnowledgeBinding`。管理页不会自动读取 `.env`、加载 Python 工厂、选择一个版本或把正文发送给模型。

## 进度与剩余

本地管理 API/CLI 和 headless TUI 回归通过。[导入扩展](./knowledge-import-extensions.md)已实现可选 PDF/Office 解析、增量解析复用、解析原文/偏移和预览锁定提交；[构建恢复](./knowledge-build-recovery.md)、混合检索/Workflow/评测 API 属于独立模块。剩余为原始二进制仓库、追溯/缓存自动持久化、向量差异同步、统一准备费用归集、真实检索质量和人工生产界面验收。

本地回归通过；最终干净环境统一结果见[2026-10-01 验收记录](./acceptance-2026-10-01.md)。这不代表真实服务、费用、质量或人工生产界面已验收。
