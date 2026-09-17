# 工程装配分享

[English](./project-sharing.en.md) | 简体中文

状态：Manifest、编码/解码、安全预览和本地版本库为 `Implemented`（`2.0.0a1`）；依赖安装、插件加载确认和 CLI/TUI 页面为 `Planned`。

当前公共 API 为 `CompositionManifest`、`PluginRequirement`、`encode_composition()`、`decode_composition()`、`inspect_composition()` 和 `CompositionStore`。这些 API 只处理数据，不访问网络、不安装包、不导入或执行插件。

## 概念

一个 `CompositionManifest` 描述“如何装配框架”，不等于源代码包、虚拟环境或运行快照。用户自行定义名称和版本，例如：

```yaml
schema_version: 1
name: lucky-coding-stack
version: 2.1.0
requires_python: ">=3.11"
requires_wagent: ">=2.0,<3.0"
plugins:
  - name: wagent-openai
    version: ">=1.2,<2.0"
  - name: my-company-router
    version: "==0.4.3"
profiles:
  default: coding
policies:
  sandbox: docker
```

用户可以保存同一名称的多个版本，也可以为同一版本创建本地别名。Manifest 的正式版本不可因别名变化而变化。

## 编码格式

首版使用带前缀的版本化编码：

```text
wagent-compose:v1:<base64url-compressed-canonical-json>:<checksum>
```

- `v1` 是编码模式版本，不是用户装配版本。
- 内容使用键排序、无多余空白的规范 JSON，zlib 压缩后使用 Base64URL。
- SHA-256 校验值检测传输损坏，不代表发布者身份。
- 解码限制压缩输入与解压后 JSON 大小，拒绝畸形、不完整和超限载荷。
- 数字签名和信任网络为 `Reserved`。

## 可以包含

- 装配名称、版本和描述。
- Python 与 W-Agent 版本约束。
- 插件名称、版本约束和公开来源标识。
- Profile、路由、Workflow 和工具的可移植配置。
- Sandbox 类型与最小权限要求。
- 可选资源的内容摘要或相对引用。

## 不能包含

- API Key、Token、密码和私钥。
- `UnsafeLocalSandbox` 授权。
- 未声明的绝对本地路径。
- 未经明确选择嵌入的任意插件源码。
- 自动安装、自动执行或跳过确认的指令。

## 导出流程

```text
当前装配
  → 解析并冻结依赖约束
  → 删除秘密值并保留凭据引用
  → 校验可移植性
  → 生成规范 Manifest
  → 压缩、编码和校验
```

导出时如果发现不可移植绝对路径、匿名本地插件或内嵌秘密，默认失败并报告具体字段。

## 导入流程

```text
编码
  → 解码和校验完整性
  → 校验模式版本
  → 生成只读预览
  → 解析依赖与冲突
  → 展示安全风险和配置差异
  → 用户确认安装
  → 用户确认加载
```

解码和预览阶段不访问网络、不安装包、不导入插件模块，也不运行任何插件代码。安装和加载是两个独立确认步骤。

## 版本管理

`CompositionStore` 按 `(name, version)` 保存 Manifest 和内容摘要。同名同版本但摘要不同的导入被视为冲突，不能静默覆盖；别名也不能静默改指其他版本。用户可以：

- 保留两个版本并选择运行版本。
- 创建新版本保存自己的改动。
- 比较两个版本的插件、配置和权限差异。
- 导出修改后的新编码。

活跃 Run 固定使用启动时的装配摘要。更新装配不会改变正在执行的 Run。

## 第三方插件

装配编码只声明依赖，不证明插件可信。导入界面显示插件来源、版本、哈希、请求能力和是否需要本地/网络执行。未知插件首次加载需要确认；自动更新默认关闭。
