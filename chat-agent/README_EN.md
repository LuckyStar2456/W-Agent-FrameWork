# Chat Agent Example Project

[English](./README_EN.md) | [简体中文](./README.md)

A complete chat dialogue agent example developed based on the W-Agent framework, demonstrating core functionalities and best practices.

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 📚 Project Introduction

This is a complete chat dialogue agent developed based on the W-Agent framework, demonstrating how to build a production-grade agent application using various framework features.

### Core Features

- ✅ **LLM Integration**: Supports real OpenAI API calls, configurable models
- ✅ **Skills System**: Integrated system info skills, supports custom skill extension
- ✅ **Conversation Management**: Complete conversation history management, context understanding
- ✅ **RAG Augmentation**: Vector retrieval augmented generation, document storage and retrieval
- ✅ **Data Storage**: Redis/MySQL integration, caching and persistence
- ✅ **Observability**: OpenTelemetry integration, distributed tracing and metrics
- ✅ **System Check**: Built-in Doctor health checks, ensures system正常运行
- ✅ **Error Handling**: Comprehensive error handling and exception capture
- ✅ **Configuration Management**: Dynamic configuration, runtime config updates
- ✅ **Lifecycle Management**: Component lifecycle, graceful startup and shutdown

## 🚀 Quick Start

### 1. Install Dependencies

```bash
# Install W-Agent framework
pip install -e ..

# Install optional dependencies
pip install -e ..[redis,fastapi,opentelemetry]

# Install OpenAI SDK
pip install openai

# Install database dependencies (optional)
pip install mysql-connector-python
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
    "vector_store": "memory",
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

### 3. Run

```bash
# Start application
python app.py

# Or use Python 3.11
python3.11 app.py
```

### 4. Interact

After startup, you can interact with the chat agent:

```
=== Running system check... ===
✅ Core components check passed, starting application...

=== Chat Agent Ready ===
Enter 'exit' to quit
Enter 'clear' to clear conversation history
Enter 'skills' to view available skills

You: Hello
Agent: Hello! I'm Chat Agent, nice to serve you. How can I help you today?

You: What's the date today
Agent: Today is April 22, 2026

You: skills
Agent: Available skills: system_info

You: exit
=== Application stopped ===
```

## 📁 Project Structure

```
chat-agent/
├── app.py                      # Main application entry
├── config/
│   └── config.json            # Configuration file
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   └── chat_agent.py      # Chat Agent implementation
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_service.py     # LLM service
│   │   ├── skill_service.py   # Skill service
│   │   ├── redis_service.py   # Redis service
│   │   ├── mysql_service.py   # MySQL service
│   │   └── rag_service.py    # RAG service
│   ├── skills/
│   │   ├── __init__.py
│   │   └── system_info.py     # System information skill
│   └── utils/
│       └── __init__.py
├── docs/
│   └── architecture.md        # Architecture documentation
├── README.md                  # Project documentation (Chinese)
├── README_EN.md               # Project documentation (English)
└── LICENSE                    # MIT License
```

## 🎯 Functional Modules

### Agent Module

`ChatAgent` is the core of the entire application, responsible for processing user input, analyzing intent, calling corresponding services and generating responses.

**Main Functions**:
- Intent analysis: Identify user intent, decide whether to use skills or regular chat
- Skill scheduling: Call corresponding skills based on intent
- Conversation management: Maintain conversation history, provide context understanding
- Response generation: Generate appropriate responses for different scenarios

**Usage Example**:

```python
from src.agents.chat_agent import ChatAgent

# Create Agent
chat_agent = ChatAgent(llm_service, skill_service, rag_service, config_manager)

# Process user input
response = await chat_agent.arun("Hello, how's the weather today?")
print(f"Agent: {response}")

# Clear conversation history
chat_agent.clear_history()

# Get available skills
skills = chat_agent.get_available_skills()
print(f"Available skills: {', '.join(skills)}")
```

### LLM Service

`LLMService` is responsible for interacting with OpenAI API, processing text generation requests.

**Main Functions**:
- API client management: Initialize and manage OpenAI client
- Text generation: Call LLM to generate text responses
- Error handling: Handle API call errors and exceptions

**Configuration Options**:
- `llm.api_key`: OpenAI API key
- `llm.model`: Model name to use
- `llm.temperature`: Randomness of generated text
- `llm.max_tokens`: Maximum length of generated text
- `llm.timeout`: API call timeout

### Skills Service

`SkillService` is responsible for managing and executing various skills.

**Main Functions**:
- Skill loading: Load skills from specified directory
- Skill execution: Execute skills in secure sandbox environment
- Skill management: Register and manage skills

**Built-in Skills**:
- `system_info`: Query system information, supports time, date, OS and Python version

**Adding Custom Skills**:

1. Create skill file in `src/skills/`:

```python
# src/skills/weather_skill.py
"""
Weather query skill
"""
import requests

async def execute(params):
    """Execute weather query"""
    city = params.get("city", "Beijing")
    return {"result": f"Weather in {city} is sunny, temperature 25°C"}
```

2. Register skill in `SkillService`:

```python
# src/services/skill_service.py
def _load_skills(self):
    # Load system info skill
    from src.skills.system_info import execute as system_info_execute
    self.skills["system_info"] = system_info_execute
    
    # Load weather skill
    try:
        from src.skills.weather_skill import execute as weather_execute
        self.skills["weather"] = weather_execute
    except ImportError:
        pass
```

### RAG Service

`RAGService` is responsible for retrieval augmented generation, improving response accuracy and relevance.

**Main Functions**:
- Document storage: Store documents to vector storage
- Document retrieval: Retrieve relevant documents based on query
- Augmented generation: Use retrieved documents to augment LLM generation

**Configuration Options**:
- `rag.vector_store`: Vector storage type (memory or redis)
- `rag.embedding_model`: Model for generating embeddings
- `rag.chunk_size`: Document chunk size
- `rag.chunk_overlap`: Chunk overlap size
- `rag.top_k`: Number of documents to retrieve

**Usage Example**:

```python
# Store documents
await rag_service.store_document("doc1", "Document content to retrieve")

# Retrieve relevant documents
documents = await rag_service.retrieve_documents("query content", top_k=3)

# Generate response using RAG
response = await rag_service.generate_with_rag("question")
```

### Redis Service

`RedisService` is responsible for interacting with Redis, providing caching and session management.

**Main Functions**:
- Connection management: Initialize and manage Redis connections
- Cache operations: Provide get, set, delete operations
- Session management: Store and manage conversation sessions

**Configuration Options**:
- `redis.host`: Redis host address
- `redis.port`: Redis port
- `redis.db`: Redis database number
- `redis.password`: Redis password

### MySQL Service

`MySQLService` is responsible for interacting with MySQL, providing data persistence.

**Main Functions**:
- Connection management: Initialize and manage MySQL connections
- Data operations: Execute SQL queries, inserts, updates and deletes
- Transaction management: Support database transactions

**Configuration Options**:
- `mysql.host`: MySQL host address
- `mysql.port`: MySQL port
- `mysql.user`: MySQL username
- `mysql.password`: MySQL password
- `mysql.database`: MySQL database name

## 🔧 Development Guide

### Extending Agent Capabilities

You can extend Agent capabilities by inheriting from `ChatAgent`:

```python
from src.agents.chat_agent import ChatAgent

class CustomChatAgent(ChatAgent):
    """Custom chat Agent"""
    
    async def _analyze_intent(self, prompt):
        """Custom intent analysis"""
        if "weather" in prompt:
            return "weather"
        return await super()._analyze_intent(prompt)
    
    async def _handle_chat_request(self, prompt):
        """Custom chat handling"""
        return await super()._handle_chat_request(prompt)
```

### Adding New Skills

1. **Create Skill File**: Create new skill file in `src/skills/`
2. **Implement Execute Function**: Each skill file needs to implement an `execute` function, receiving parameters and returning results
3. **Register Skill**: Register new skill in `SkillService`'s `_load_skills` method
4. **Update Intent Analysis**: Add recognition of new skill in `ChatAgent`'s `_analyze_intent` method

### Configuration Management

The project uses dynamic configuration management, supporting runtime config updates:

```python
# Load configuration
config_manager = DynamicConfigManager()
await config_manager.load_from_file("config/config.json")

# Bind config to object
class ServiceConfig:
    def __init__(self):
        self.api_key = None
        config_manager.bind("llm.api_key", self, "api_key")
    
    async def on_config_change(self, key, new_value, old_value):
        print(f"Config changed: {key} = {new_value}")

# Dynamically update config
await config_manager.update_batch({"llm.temperature": 0.8})
```

### Observability

The project integrates OpenTelemetry, supporting distributed tracing and metrics:

- **Distributed Tracing**: Track complete processing of requests
- **Metrics Monitoring**: Collect system operation metrics
- **Log Management**: Structured log recording

## 📖 Architecture Design

### System Architecture

Chat Agent uses layered architecture:

1. **Interface Layer**: `app.py` as application entry, handle user input and output
2. **Agent Layer**: `ChatAgent` as core, coordinate various services
3. **Service Layer**: Various services (LLM, Skills, RAG, Storage)
4. **Infrastructure Layer**: Core functionality provided by W-Agent framework

### Data Flow

1. User input → `app.py` → `ChatAgent.arun()`
2. `ChatAgent` analyzes intent → calls corresponding service
3. Service processes → returns result to `ChatAgent`
4. `ChatAgent` generates response → returns to user

## 🛠️ Troubleshooting

### Common Issues

1. **API Key Error**
   - Symptom: `LLM generation failed: Invalid API key`
   - Solution: Check if `llm.api_key` in `config.json` is correct

2. **Redis Connection Failed**
   - Symptom: `Failed to initialize Redis client`
   - Solution: Ensure Redis service is running, check `redis` config

3. **MySQL Connection Failed**
   - Symptom: `Failed to initialize MySQL connection`
   - Solution: Ensure MySQL service is running, check `mysql` config

4. **Skill Execution Failed**
   - Symptom: `Skill execution failed: ...`
   - Solution: Check if skill script is correct, sandbox environment is normal

### Log Viewing

The application outputs detailed logs during runtime to help troubleshoot issues:

- **INFO**: Normal operation information
- **WARNING**: Warning information
- **ERROR**: Error information
- **DEBUG**: Debug information

## 📖 Documentation

- [Architecture Documentation](./docs/architecture.md): Detailed architecture design documentation
- [W-Agent Framework Documentation](../README.md): Complete framework documentation
- [User Guide](../docs/guide.md): Detailed usage tutorial

## 📄 License

This project is licensed under the [MIT License](../LICENSE).
