# Chat Agent 示例项目

[English](./README_EN.md) | 简体中文

基于 W-Agent 框架开发的示例聊天对话智能体。

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📚 项目介绍

这是一个基于 W-Agent 框架开发的示例聊天对话智能体，具有以下特点：

- ✅ 支持真实的 OpenAI API 调用
- ✅ 集成系统信息技能
- ✅ 对话历史管理
- ✅ RAG 检索增强支持
- ✅ Redis/MySQL 集成
- ✅ OpenTelemetry 可观测性
- ✅ 完善的错误处理
- ✅ 系统健康检查

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装 W-Agent 框架
pip install -e ..

# 安装可选依赖
pip install -e ..[redis,fastapi]

# 安装 OpenAI SDK
pip install openai
```

### 2. 配置

编辑 `config/config.json`：

```json
{
  "llm": {
    "api_key": "YOUR_API_KEY",
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
    "db": 0
  },
  "rag": {
    "vector_store": "memory",
    "embedding_model": "text-embedding-ada-002",
    "top_k": 3
  }
}
```

### 3. 运行

```bash
python app.py
```

## 📁 项目结构

```
chat-agent/
├── app.py                      # 主应用入口
├── config/
│   └── config.json            # 配置文件
├── src/
│   ├── agents/
│   │   └── chat_agent.py      # 聊天 Agent 实现
│   ├── services/
│   │   ├── llm_service.py     # LLM 服务
│   │   ├── skill_service.py   # 技能服务
│   │   ├── redis_service.py   # Redis 服务
│   │   ├── mysql_service.py   # MySQL 服务
│   │   └── rag_service.py    # RAG 服务
│   ├── skills/
│   │   └── system_info.py     # 系统信息技能
│   └── utils/
├── docs/
│   └── architecture.md        # 架构文档
└── README.md
```

## 🎯 功能模块

### Agent 模块

基于 W-Agent 框架的 Agent 实现，支持：

- 意图分析
- 技能调度
- 对话历史管理

```python
from src.agents.chat_agent import ChatAgent

agent = ChatAgent(config_manager, llm_service, skill_service)
response = await agent.process("你好，今天天气怎么样？")
```

### 技能系统

| 技能 | 描述 | 参数 |
|------|------|------|
| `system_info` | 系统信息查询 | `type`: time/date/os/python/all |

### RAG 服务

支持向量检索增强生成：

```python
# 存储文档
await rag_service.store_document("doc1", "这是要检索的文档内容")

# 检索相关文档
documents = await rag_service.retrieve_documents("查询内容", top_k=3)

# 使用 RAG 生成回复
response = await rag_service.generate_with_rag("问题")
```

## ⚙️ 配置说明

### LLM 配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `llm.api_key` | string | - | OpenAI API 密钥 |
| `llm.model` | string | "gpt-4" | 模型名称 |
| `llm.temperature` | float | 0.7 | 温度参数 |
| `llm.max_tokens` | int | 1000 | 最大 token 数 |

### Redis 配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `redis.host` | string | "localhost" | Redis 主机 |
| `redis.port` | int | 6379 | Redis 端口 |
| `redis.db` | int | 0 | 数据库编号 |

### RAG 配置

| 配置项 | 类型 | 默认值 | 描述 |
|--------|------|--------|------|
| `rag.vector_store` | string | "memory" | 向量存储：redis/memory |
| `rag.embedding_model` | string | "text-embedding-ada-002" | 嵌入模型 |
| `rag.top_k` | int | 3 | 检索数量 |

## 🔧 开发指南

### 添加新技能

1. 在 `src/skills/` 目录创建技能文件：

```python
# src/skills/my_skill.py
async def execute(params):
    skill_type = params.get("type")
    # 实现技能逻辑
    return {"result": "skill result"}
```

2. 在 `SkillService` 中注册技能：

```python
skill_service.register_skill("my_skill", execute)
```

### 扩展 Agent 能力

```python
# 修改意图分析方法
class CustomChatAgent(ChatAgent):
    async def _analyze_intent(self, message):
        # 自定义意图分析
        pass
```

## 📖 文档

- [架构设计](./docs/architecture.md)
- [W-Agent 框架文档](../README.md)

## 📄 许可证

本项目采用 [MIT 许可证](../LICENSE)。
