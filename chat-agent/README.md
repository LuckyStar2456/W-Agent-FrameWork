# 示例聊天对话智能体

## 项目介绍

这是一个基于W-Agent框架开发的示例聊天对话智能体，具有以下特点：

- 支持真实的OpenAI API调用
- 集成系统信息技能
- 对话历史管理
- 示例架构设计
- 完善的错误处理
- 系统健康检查

## 项目结构

```
chat-agent/
├── app.py              # 主应用文件
├── config/             # 配置目录
│   └── config.json     # 配置文件
├── src/                # 源代码目录
│   ├── agents/         # Agent目录
│   │   └── chat_agent.py  # 聊天Agent
│   ├── services/       # 服务目录
│   │   ├── llm_service.py  # LLM服务
│   │   └── skill_service.py  # 技能服务
│   ├── skills/         # 技能目录
│   │   └── system_info.py  # 系统信息技能
│   └── utils/          # 工具目录
├── docs/               # 文档目录
└── tests/              # 测试目录
```

## 配置说明

在`config/config.json`中配置以下信息：

```json
{
  "llm": {
    "api_key": "",  // 填写OpenAI API密钥
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
  }
}
```

## 安装依赖

```bash
# 安装W-Agent框架
pip install -e ..

# 安装OpenAI SDK
pip install openai
```

## 使用方法

1. **配置API密钥**：在`config/config.json`中填写OpenAI API密钥

2. **运行应用**：
   ```bash
   python app.py
   ```

3. **与Agent交互**：
   - 输入普通问题：`你好，今天怎么样？`
   - 输入系统信息查询：`当前时间是多少？`
   - 输入`exit`退出应用
   - 输入`clear`清空对话历史
   - 输入`skills`查看可用技能

## 技能说明

### 系统信息技能 (system_info)

- **type=time**：获取当前时间
- **type=date**：获取当前日期
- **type=os**：获取操作系统信息
- **type=python**：获取Python版本信息
- **type=all**：获取所有系统信息

## 开发指南

### 添加新技能

1. 在`src/skills`目录中创建新的技能文件
2. 实现`execute`函数，接收`params`参数并返回结果
3. 重启应用，技能会自动加载

### 扩展Agent能力

1. 修改`src/agents/chat_agent.py`中的`_analyze_intent`方法，添加新的意图识别
2. 修改`_extract_skill_info`方法，添加新的技能参数提取逻辑
3. 修改`_handle_skill_request`方法，添加新的技能处理逻辑

## 示例部署

1. **环境变量配置**：在示例环境中，可以通过环境变量覆盖配置文件中的设置

2. **容器化部署**：
   ```bash
   # 构建镜像
   docker build -t chat-agent .
   
   # 运行容器
   docker run -d -p 8000:8000 --name chat-agent chat-agent
   ```

3. **监控与日志**：集成Prometheus和Grafana进行监控，使用ELK stack进行日志管理

## 安全注意事项

1. **API密钥保护**：不要将API密钥硬编码到代码中，使用配置文件或环境变量
2. **输入验证**：对用户输入进行验证，防止注入攻击
3. **速率限制**：实现API调用速率限制，防止滥用
4. **错误处理**：妥善处理API错误，避免敏感信息泄露

## 性能优化

1. **缓存**：缓存频繁使用的响应
2. **异步处理**：使用异步IO提高并发性能
3. **批处理**：批量处理多个请求，减少API调用次数
4. **资源管理**：合理管理连接池和内存使用

## 故障处理

1. **API故障**：实现重试机制和降级策略
2. **服务降级**：当LLM服务不可用时，使用默认回复
3. **监控告警**：设置关键指标的监控和告警

## 许可证

MIT
