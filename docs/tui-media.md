# 回放媒体展示

> 适用版本：2.0.0。`Experimental` 仍为实验性接口；`Planned` / `Reserved` 不表示已实现。验证范围见[正式版记录](./acceptance-2026-10-01-stable-release.md)。

[English](tui-media.en.md)

状态：Experimental。本地回放现可展示真正的 PNG/JPEG/WebP 字符亮度图，而非仅打印媒体 JSON；音频可展示元信息并显式导出。它不是播放器，也不执行模型或工具。

## 使用

图片解码是可选能力，源码安装可选 `pip install '.[tui,media-preview]'`；只用核心框架不会导入 Pillow/Textual。缺少 Pillow 时预览明确报缺依赖，不自动安装。当前环境已因文档解析依赖具有 Pillow 12.3.0，本轮未安装或重新安装依赖；新增 extra 尚未做安装验收。

在 TUI 的回放页选择 Run/Session，输出媒体 `media=content` 或 Session 输入媒体 `input-media=content`，输入 `VIEW CONTENT` 后读取一批。现有 `metadata` 默认不变，`references` 不提供内联字节。

下方独立“媒体预览”区域只列出媒体种类与位置。选择上一项/下一项，手输 `VIEW MEDIA` 并点击“预览所选”：

- PNG/JPEG/WebP 静态图片转换为最多 64 列、24 行 ASCII 亮度图；保留比例、透明度合成白底，不绘制远端图片。字符图不是原分辨率显示，颜色信息会丢失。
- WAV 使用标准库解析声道、采样率、位深、时长。不播放、不转码；其他音频只显示已声明 MIME/字节数，不声称验证其编解码器或时长。
- URL 仅显示清理过的文本，不请求网络、不读取 `file:`、不打开浏览器。链接本身也可能敏感，仅在独立确认后显示。

导出需填写**已有的本地目录**，再次输入 `EXPORT MEDIA` 并点击导出。文件名由内容 SHA-256 和固定扩展名表生成；未知 MIME 使用 `.bin`。不自动建目录，不覆盖已有文件，不从记录中接受文件名，拒绝目录祖先符号链接/Windows reparse point。原始导出字节未必是有效或安全文件，不自动打开。

回放的 `VIEW CONTENT` 与预览/导出的授权互不替代；每次动作会消耗输入的确认词。切换媒体或清空/重读快照会隐藏先前预览，并丢弃旧任务的 UI 结果。已开始的本地文件写入可能在清空或退出后完成，取消不代表回滚。

## 开放扩展

`w_agent.media_display` 不强制依赖 TUI 或 Pillow；默认图片解码器首次预览才导入 Pillow。没有 Pillow 时给出明确错误，不自动安装。现有 `knowledge-documents` 依赖组合通常已通过 python-pptx 带入 Pillow，但不能依赖其始终存在。

```python
from pathlib import Path
from w_agent.media_display import MediaPreview
from w_agent.tui_replay import ReplayPanel

class MyDisplay:
    def render(self, block, *, confirmed=False):
        if confirmed is not True:
            raise ValueError("confirmation required")
        return MediaPreview("Host-defined presentation", "your bounded image art")

panel = ReplayPanel(Path.cwd(), media_renderer=MyDisplay())
```

`MediaDisplay` 是结构化协议；宿主可替换模板，但替换器是受信 Python，不是沙箱。禁止在模板中暗中联网、播放或执行；TUI 仅能限制最终展示文本，无法隔离自定义代码。默认模板也可通过 `MediaDisplayLimits` 调整字节/像素/字符维度。

## 边界与验证

默认内联字节上限 8 MiB、像素上限 400 万；配置硬上限 32 MiB、1600 万像素、128×64 字符。校验 base64、字节数和 SHA-256；图片只用指定解码器、校验完整性并拒绝动画。终端输出去除控制字符、双向控制符和隐藏格式字符，禁止 Rich markup/ANSI 注入。仅从标准 Run 输出媒体槽与 Session 输入媒体槽提取，忽略工具结果中的同形对象；目录最多 256 项，超限不展示部分结果。

导出路径检查不是对抗具有同目录写权限的恶意本地进程的安全沙箱；检查期间并发替换目录的竞态尚未通过跨平台 handle-relative 文件 API 消除。应使用自己控制的目录。摘要证明数据一致性，不证明可信来源。快照/屏幕滚动历史/导出文件含敏感内容，清屏不会抹除系统外部记录。

本轮相关验证覆盖真实 PNG 字符图与 WAV、授权/大小/摘要/MIME/控制字符/导出无覆盖、Session 输入和 Run 输出、可替换模板、失效异步交付、实际回放到子面板接线。无外部服务、自动播放、全量测试、依赖安装或发布。

保留：彩色/高分辨率终端协议、波形/音频播放、更多媒体编解码器、用户明确授权的远端获取、可选原生应用打开、隔离解码进程。目前均未实现。
