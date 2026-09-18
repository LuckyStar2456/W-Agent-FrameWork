# 工程装配分享

[English](./project-sharing.en.md) | 简体中文

状态：Manifest、编码/解码、安全预览和本地版本库为 `Implemented`（`2.0.0a1`），CLI 与 TUI 离线预览为 `Experimental`。当前 main（未发布）另外实现可替换的离线依赖规划器，以及独立的通用 YAML 插件预览/加载确认与 TUI 卸载。在线来源目录、包安装和从规划结果自动生成插件加载引用仍为 `Planned`。

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

当前 main 的 `wagent plugin inspect` / `validate-load` 与 TUI Plugins 页可操作用户明确选择的 `module:attribute` YAML 引用，但不会从 `CompositionManifest` 自动生成或执行这些引用。通用插件确认边界已经可用，规划结果到包安装及插件引用之间的执行桥仍未实现。

## 离线依赖计划

当前 main 可在不访问网络、不查询包索引、不导入模块和不安装包的情况下生成计划：

```text
wagent composition plan <code> --inventory plugin-inventory.json --json
```

显式候选清单格式为：

```json
{
  "plugins": [
    {
      "name": "my-company-router",
      "version": "0.4.3",
      "source": "private-index",
      "entry": "my_router.plugin:setup"
    }
  ]
}
```

计划检查 Python/W-Agent 版本约束，并为每个插件产生 `use-installed`、`install`、`change-version`、`review-source`、`select-source` 或 `select-candidate`。它只描述下一步，不包含可执行安装命令。Python API 接受任意 `CompositionDependencyResolver` 实现，因此应用可以接入自己的锁文件、内部 Registry 或包格式，而不改变 Manifest 核心协议。

TUI Composition 页可读取同一候选清单；未指定清单时只参考当前 TUI 中活跃插件的名称和版本。来源未知时不会猜测为可信来源。即使计划为 Ready，插件代码加载仍需独立确认。

## 版本管理

`CompositionStore` 按 `(name, version)` 保存 Manifest 和内容摘要。同名同版本但摘要不同的导入被视为冲突，不能静默覆盖；别名也不能静默改指其他版本。用户可以：

- 保留两个版本并选择运行版本。
- 创建新版本保存自己的改动。
- 比较两个版本的插件、配置和权限差异。
- 导出修改后的新编码。

活跃 Run 固定使用启动时的装配摘要。更新装配不会改变正在执行的 Run。

## 第三方插件

装配编码只声明依赖，不证明插件可信。离线计划显示声明来源、候选版本和下一步动作，但不验证发布者身份。计划中的安装界面还需显示哈希、请求能力和是否需要本地/网络执行。当前通用插件加载要求独立、一次性的代码执行确认；自动安装和自动更新均未实现。
