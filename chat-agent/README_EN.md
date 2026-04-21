# Chat Agent Example Project

[English](./README_EN.md) | [简体中文](./README.md)

A sample chat dialogue agent developed based on the W-Agent framework.

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📚 Project Introduction

This is a sample chat dialogue agent developed based on the W-Agent framework, with the following features:

- ✅ Support for real OpenAI API calls
- ✅ Integrated system information skills
- ✅ Conversation history management
- ✅ RAG retrieval augmentation support
- ✅ Redis/MySQL integration
- ✅ OpenTelemetry observability
- ✅ Comprehensive error handling
- ✅ System health checks

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install W-Agent framework
pip install -e ..

# Install optional dependencies
pip install -e ..[redis,fastapi]

# Install OpenAI SDK
pip install openai
```

### 2. Configuration

Edit `config/config.json`:

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
    "description": "Sample Chat Dialogue Agent",
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

### 3. Run

```bash
python app.py
```

## 📁 Project Structure

```
chat-agent/
├── app.py                      # Main application entry
├── config/
│   └── config.json            # Configuration file
├── src/
│   ├── agents/
│   │   └── chat_agent.py      # Chat Agent implementation
│   ├── services/
│   │   ├── llm_service.py     # LLM service
│   │   ├── skill_service.py   # Skill service
│   │   ├── redis_service.py   # Redis service
│   │   ├── mysql_service.py   # MySQL service
│   │   └── rag_service.py    # RAG service
│   ├── skills/
│   │   └── system_info.py     # System information skill
│   └── utils/
├── docs/
│   └── architecture.md        # Architecture documentation
└── README.md
```

## 🎯 Functional Modules

### Agent Module

Agent implementation based on W-Agent framework, supporting:

- Intent analysis
- Skill scheduling
- Conversation history management

### Skills System

| Skill | Description | Parameters |
|-------|-------------|------------|
| `system_info` | System information query | `type`: time/date/os/python/all |

### RAG Service

Supports vector retrieval augmented generation:

```python
# Store documents
await rag_service.store_document("doc1", "Document content to retrieve")

# Retrieve relevant documents
documents = await rag_service.retrieve_documents("query content", top_k=3)

# Generate response using RAG
response = await rag_service.generate_with_rag("question")
```

## 📖 Documentation

- [Architecture Documentation](./docs/architecture.md)
- [W-Agent Framework Documentation](../README.md)

## 📄 License

This project is licensed under the [MIT License](../LICENSE).
