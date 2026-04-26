# Chat Agent 示例项目

[English](./README_EN.md) | 简体中文

基于 W-Agent 框架开发的完整聊天对话智能体示例，展示了框架的核心功能和最佳实践。

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📚 项目介绍

这是一个基于 W-Agent 框架开发的完整聊天对话智能体示例，展示了如何使用框架的各种功能构建一个生产级的智能体应用。

### 核心特性

- ✅ **LLM 集成**：支持真实的 OpenAI API 调用，可配置不同模型
- ✅ **技能系统**：集成系统信息技能，支持自定义技能扩展
- ✅ **对话管理**：完整的对话历史管理，支持上下文理解
- ✅ **RAG 增强**：向量检索增强生成，支持文档存储和检索
- ✅ **数据存储**：Redis/MySQL 集成，支持缓存和持久化
- ✅ **可观测性**：OpenTelemetry 集成，支持链路追踪和指标监控
- ✅ **系统检查**：内置 Doctor 健康检查，确保系统正常运行
- ✅ **错误处理**：完善的错误处理和异常捕获机制
- ✅ **配置管理**：动态配置管理，支持运行时配置更新
- ✅ **生命周期管理**：组件生命周期管理，支持优雅启动和关闭

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装 W-Agent 框架
pip install -e ..

# 安装可选依赖
pip install -e ..[redis,fastapi,opentelemetry]

# 安装 OpenAI SDK
pip install openai

# 安装数据库依赖（可选）
pip install mysql-connector-python
```

### 2. 配置

编辑 `config/config.json`，填写必要的配置信息：

```json
{
  "llm": {
    "api_key": "YOUR_API_KEY",  // 替换为你的 OpenAI API 密钥
    "model": "gpt-4",
    "temperature": 0.7,
    "max_tokens": 1000,
    "timeout": 30
  },
  "system": {
    "name": "Chat Agent",
    "version": "1.0.0",
    "description": "示例聊天对话智能体",
    "max_history": 50
  },
  "redis": {
    "host": "localhost",
    "port": 6379,
    "db": 0,
    "password": ""
  },
  "mysql": {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "chat_agent"
  },
  "rag": {
    "vector_store": "memory",  // 可选: memory, redis
    "embedding_model": "text-embedding-ada-002",
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "top_k": 3
  },
  "observability": {
    "tracing": {
      "enabled": true,
      "exporter": "otlp"
    },
    "metrics": {
      "enabled": true
    }
  }
}
```

### 3. 运行

```bash
# 启动应用
python app.py

# 或者使用 Python 3.11 运行
python3.11 app.py
```

### 4. 交互

启动后，你可以与聊天智能体进行交互：

```
=== 运行系统检查... ===
✅ 核心组件检查通过，启动应用...

=== 聊天Agent就绪 ===
输入 'exit' 退出
输入 'clear' 清空对话历史
输入 'skills' 查看可用技能

你: 你好
Agent: 你好！我是 Chat Agent，很高兴为你服务。请问有什么我可以帮助你的吗？

你: 今天是什么日期
Agent: 今天是 2026年4月22日

你: 技能
Agent: 可用技能: system_info

你: exit
=== 应用已停止 ===
```

## 📁 项目结构

```
chat-agent/
├── app.py                      # 主应用入口
├── config/
│   └── config.json            # 配置文件
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   └── chat_agent.py      # 聊天 Agent 实现
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py     # LLM 服务
│   │   ├── skill_service.py   # 技能服务
│   │   ├── redis_service.py   # Redis 服务
│   │   ├── mysql_service.py   # MySQL 服务
│   │   └── rag_service.py    # RAG 服务
│   ├── skills/
│   │   ├── __init__.py
│   │   └── system_info.py     # 系统信息技能
│   └── utils/
│       └── __init__.py
├── docs/
│   └── architecture.md        # 架构文档
├── README.md                  # 项目说明
└── README_EN.md               # 英文说明
```

## 🎯 功能模块详解

### Agent 模块

`ChatAgent` 是整个应用的核心，负责处理用户输入、分析意图、调用相应服务并生成回复。

**主要功能**：
- 意图分析：识别用户意图，决定使用技能还是普通对话
- 技能调度：根据意图调用相应的技能
- 对话管理：维护对话历史，提供上下文理解
- 回复生成：根据不同场景生成合适的回复

**使用示例**：

```python
from src.agents.chat_agent import ChatAgent

# 创建 Agent
chat_agent = ChatAgent(llm_service, skill_service, rag_service, config_manager)

# 处理用户输入
response = await chat_agent.arun("你好，今天天气怎么样？")
print(f"Agent: {response}")

# 清空对话历史
chat_agent.clear_history()

# 获取可用技能
skills = chat_agent.get_available_skills()
print(f"可用技能: {', '.join(skills)}")
```

### LLM 服务

`LLMService` 负责与 OpenAI API 交互，处理文本生成请求。

**主要功能**：
- API 客户端管理：初始化和管理 OpenAI 客户端
- 文本生成：调用 LLM 生成文本回复
- 错误处理：处理 API 调用错误和异常

**配置选项**：
- `llm.api_key`：OpenAI API 密钥
- `llm.model`：使用的模型名称
- `llm.temperature`：生成文本的随机性
- `llm.max_tokens`：生成文本的最大长度
- `llm.timeout`：API 调用超时时间

### 技能服务

`SkillService` 负责管理和执行各种技能。

**主要功能**：
- 技能加载：从指定目录加载技能
- 技能执行：在安全的沙箱环境中执行技能
- 技能管理：注册和管理技能

**内置技能**：
- `system_info`：查询系统信息，支持时间、日期、操作系统和 Python 版本等

**添加自定义技能**：

1. 在 `src/skills/` 目录创建技能文件：

```python
# src/skills/weather_skill.py
"""
天气查询技能
"""
import requests

async def execute(params):
    """执行天气查询"""
    city = params.get("city", "北京")
    # 这里应该调用真实的天气 API
    return {"result": f"{city}的天气晴朗，温度 25°C"}
```

2. 在 `SkillService` 中注册技能：

```python
# src/services/skill_service.py
def _load_skills(self):
    # 加载系统信息技能
    from src.skills.system_info import execute as system_info_execute
    self.skills["system_info"] = system_info_execute
    
    # 加载天气技能
    try:
        from src.skills.weather_skill import execute as weather_execute
        self.skills["weather"] = weather_execute
    except ImportError:
        pass
```

### RAG 服务

`RAGService` 负责检索增强生成，提高回复的准确性和相关性。

**主要功能**：
- 文档存储：存储文档到向量存储
- 文档检索：根据查询检索相关文档
- 增强生成：使用检索到的文档增强 LLM 生成

**配置选项**：
- `rag.vector_store`：向量存储类型（memory 或 redis）
- `rag.embedding_model`：用于生成嵌入的模型
- `rag.chunk_size`：文档分块大小
- `rag.chunk_overlap`：分块重叠大小
- `rag.top_k`：检索的文档数量

**使用示例**：

```python
# 存储文档
await rag_service.store_document("doc1", "这是要检索的文档内容")

# 检索相关文档
documents = await rag_service.retrieve_documents("查询内容", top_k=3)

# 使用 RAG 生成回复
response = await rag_service.generate_with_rag("问题")
```

### Redis 服务

`RedisService` 负责与 Redis 交互，提供缓存和会话管理。

**主要功能**：
- 连接管理：初始化和管理 Redis 连接
- 缓存操作：提供 get、set、delete 等缓存操作
- 会话管理：存储和管理对话会话

**配置选项**：
- `redis.host`：Redis 主机地址
- `redis.port`：Redis 端口
- `redis.db`：Redis 数据库编号
- `redis.password`：Redis 密码

### MySQL 服务

`MySQLService` 负责与 MySQL 交互，提供数据持久化。

**主要功能**：
- 连接管理：初始化和管理 MySQL 连接
- 数据操作：执行 SQL 查询、插入、更新和删除
- 事务管理：支持数据库事务

**配置选项**：
- `mysql.host`：MySQL 主机地址
- `mysql.port`：MySQL 端口
- `mysql.user`：MySQL 用户名
- `mysql.password`：MySQL 密码
- `mysql.database`：MySQL 数据库名称

## 🔧 开发指南

### 扩展 Agent 能力

你可以通过继承 `ChatAgent` 类来扩展 Agent 的能力：

```python
from src.agents.chat_agent import ChatAgent

class CustomChatAgent(ChatAgent):
    """自定义聊天 Agent"""
    
    async def _analyze_intent(self, prompt):
        """自定义意图分析"""
        # 增强的意图分析逻辑
        if "天气" in prompt:
            return "weather"
        return super()._analyze_intent(prompt)
    
    async def _handle_chat_request(self, prompt):
        """自定义聊天处理"""
        # 增强的聊天处理逻辑
        # ...
        return await super()._handle_chat_request(prompt)
```

### 添加新技能

1. **创建技能文件**：在 `src/skills/` 目录创建新的技能文件
2. **实现 execute 函数**：每个技能文件需要实现一个 `execute` 函数，接收参数并返回结果
3. **注册技能**：在 `SkillService` 的 `_load_skills` 方法中注册新技能
4. **更新意图分析**：在 `ChatAgent` 的 `_analyze_intent` 方法中添加对新技能的识别

### 配置管理

项目使用动态配置管理，支持运行时配置更新：

```python
# 加载配置
config_manager = DynamicConfigManager()
await config_manager.load_from_file("config/config.json")

# 绑定配置到对象
class ServiceConfig:
    def __init__(self):
        self.api_key = None
        config_manager.bind("llm.api_key", self, "api_key")
    
    async def on_config_change(self, key, new_value, old_value):
        print(f"配置变更: {key} = {new_value}")

# 动态更新配置
await config_manager.update_batch({"llm.temperature": 0.8})
```

### 可观测性

项目集成了 OpenTelemetry，支持链路追踪和指标监控：

- **链路追踪**：跟踪请求的完整处理过程
- **指标监控**：收集系统运行指标
- **日志管理**：结构化日志记录

## 📖 架构设计

### 系统架构

Chat Agent 采用分层架构设计：

1. **接口层**：`app.py` 作为应用入口，处理用户输入和输出
2. **Agent 层**：`ChatAgent` 作为核心，协调各服务
3. **服务层**：各种服务（LLM、技能、RAG、存储）
4. **基础设施层**：W-Agent 框架提供的核心功能

### 数据流

1. 用户输入 → `app.py` → `ChatAgent.arun()`
2. `ChatAgent` 分析意图 → 调用相应服务
3. 服务处理 → 返回结果给 `ChatAgent`
4. `ChatAgent` 生成回复 → 返回给用户

## 🛠️ 故障排查

### 常见问题

1. **API 密钥错误**
   - 症状：`LLM生成失败: Invalid API key`
   - 解决：检查 `config.json` 中的 `llm.api_key` 是否正确

2. **Redis 连接失败**
   - 症状：`Failed to initialize Redis client`
   - 解决：确保 Redis 服务正在运行，检查 `redis` 配置

3. **MySQL 连接失败**
   - 症状：`Failed to initialize MySQL connection`
   - 解决：确保 MySQL 服务正在运行，检查 `mysql` 配置

4. **技能执行失败**
   - 症状：`技能执行失败: ...`
   - 解决：检查技能脚本是否正确，沙箱环境是否正常

### 日志查看

应用运行时会输出详细日志，帮助排查问题：

- **INFO**：正常运行信息
- **WARNING**：警告信息
- **ERROR**：错误信息
- **DEBUG**：调试信息

## 📄 文档

- [架构设计](./docs/architecture.md)：详细的架构设计文档
- [W-Agent 框架文档](../README.md)：框架的完整文档
- [使用指南](../docs/guide.md)：详细的使用教程

## 📄 许可证

本项目采用 [MIT 许可证](../LICENSE)。
