# W-Agent 2.1.0 发布记录

[English](./acceptance-2026-10-02-release-2.1.0.en.md) | 简体中文

2026-10-02，`wagent-framework==2.1.0` 正式版已发布至 [PyPI](https://pypi.org/project/wagent-framework/2.1.0/)。用户明确授权发布；未发布 alpha，未进行 Git 提交或推送。

## 内容与验证依据

纳入已完成 M0–M5 验收的 Harness 开发核心，详见[版本说明](./releases/2.1.0.md)。按 Python 包规范统一元数据和导出版本，中英发布文档区分历史验收与实际上传结果。

复用[核心终验](./harness-acceptance.md)的 259 项相关测试、离线制品、隔离安装和仓库外三示例 Python/CLI/TUI 证据。此次没有新增测试、安装、真实模型调用或全局依赖修改。只调整版本、包描述和文档；234 个 Python 模块与 M5 已验收 wheel 逐字节一致，唯一允许差异是 `__version__` 从 2.0.0 改为 2.1.0。

## 制品与远端结果

使用既有工具在独立临时源码目录执行 `python -m build --no-isolation`，先构建 sdist，再从 sdist 构建 wheel。两份制品通过 `twine check --strict`；wheel 的 234 个源码模块、sdist 的 589 个源码/交付文件与冻结工作区一致，敏感文件和缓存未进入制品。

上传前确认 2.1.0 不存在，通过现有项目凭据上传至官方 PyPI，未输出凭据。上传后读取版本 JSON，两份制品均非 yanked，远端摘要与本地一致：

| 制品 | 字节数 | SHA-256 |
|---|---:|---|
| `wagent_framework-2.1.0-py3-none-any.whl` | 630830 | `cea6be92dd62817928337ec863153746dbb05d3a59c42c74aeba536251e86ff9` |
| `wagent_framework-2.1.0.tar.gz` | 1435692 | `bf1f9ad508471f98576823b09364701033261c288f1a8838556934d75009734a` |

本地目录：`C:/Users/97554/AppData/Local/Temp/wagent-release-2.1.0-dc120cdd2d174d3d90e58b2e0f620cda/dist`。本记录和工作区发布状态在上传后写入，不在冻结 sdist 中；没有从 PyPI 重新安装，不声称进行了远端重新安装验收。

## 使用与剩余范围

```bash
python -m pip install --upgrade "wagent-framework==2.1.0"
```

按需添加 `[models,tui]` extras。核心目标与发布均完成；多 Agent、分布式 Workflow、远程沙箱、插件市场、高级热迁移仍保留。全量回归、真实模型质量/计费及全平台组合不是本次已验证项，已有 Experimental 能力不自动升级为稳定。
