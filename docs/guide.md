# W-Agent 入门指南

本指南将帮助您从零开始创建和使用 W-Agent 框架。

## 1. 安装

首先，安装 W-Agent 框架：

```bash
# 克隆代码库
git clone <repository-url>
cd W-Agent

# 安装框架
pip install -e .

# 安装可选依赖（FastAPI、LangChain等）
pip install -e .[fastapi,langchain,testing]
```

## 2. 创建第一个 Agent

### 2.1 基本 Agent

创建一个名为 `my_agent.py` 的文件：

```python
from w_agent.core.decorators import AgentComponent, PostConstruct, PreDestroy

@AgentComponent(name="my_agent")
class MyAgent:
    def __init__(self):
        self.name = "MyAgent"
    
    async def arun(self, prompt: str) -> str:
        """运行 Agent"""
        return f"Hello from {self.name}! You said: {prompt}"
    
    @PostConstruct
    def initialize(self):
        """初始化方法"""
        print(f"{self.name} is initializing...")
    
    @PreDestroy
    def cleanup(self):
        """销毁方法"""
        print(f"{self.name} is cleaning up...")
```

### 2.2 带有依赖注入的 Agent

创建一个名为 `my_agent_with_dependency.py` 的文件：

```python
from w_agent.core.decorators import AgentComponent, ServiceComponent

@ServiceComponent(name="greeting_service")
class GreetingService:
    def get_greeting(self, name: str) -> str:
        return f"Hello, {name}!"

@AgentComponent(name="my_agent")
class MyAgent:
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
    
    async def arun(self, prompt: str) -> str:
        """运行 Agent"""
        return self.greeting_service.get_greeting(prompt)
```

## 3. 扫描和注册组件

创建一个名为 `app.py` 的文件：

```python
import asyncio
from pathlib import Path
from w_agent.scanner.parallel_scanner import ParallelASTScanner
from w_agent.container.bean_factory import BeanFactory

async def main():
    # 扫描组件
    scanner = ParallelASTScanner()
    result = scanner.scan_package(Path("."))
    
    # 创建 Bean 工厂
    factory = BeanFactory()
    
    # 注册组件
    for component in result.components:
        if component.class_name:
            # 动态导入模块和类
            module_path = component.file_path.relative_to(Path(".")).with_suffix("").as_posix().replace("/", ".")
            module = __import__(module_path, fromlist=[component.class_name])
            cls = getattr(module, component.class_name)
            
            # 创建实例并注册
            instance = cls()
            factory.register_bean(component.name, instance)
    
    # 获取并运行 Agent
    agent = await factory.get_bean("my_agent")
    result = await agent.arun("World")
    print(result)
    
    # 销毁单例
    await factory.destroy_singletons()

if __name__ == "__main__":
    asyncio.run(main())
```

## 4. 使用 FastAPI 集成

创建一个名为 `fastapi_app.py` 的文件：

```python
from w_agent.deployment.fastapi_depends import app, ctx
from w_agent.core.decorators import AgentComponent, ServiceComponent

# 注册组件
@ServiceComponent(name="greeting_service")
class GreetingService:
    def get_greeting(self, name: str) -> str:
        return f"Hello, {name}!"

@AgentComponent(name="default_agent")
class MyAgent:
    def __init__(self, greeting_service: GreetingService):
        self.greeting_service = greeting_service
    
    async def arun(self, prompt: str) -> str:
        return self.greeting_service.get_greeting(prompt)

# 注册到 Bean 工厂
from w_agent.container.bean_factory import BeanDefinition, Scope

greeting_service = GreetingService()
ctx.bean_factory.register_bean("greeting_service", greeting_service)

agent = MyAgent(greeting_service)
ctx.bean_factory.register_bean("default_agent", agent)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

启动服务器：

```bash
python fastapi_app.py
```

然后访问 `http://localhost:8000/docs` 查看 API 文档。

## 5. 使用 CLI 工具

### 5.1 扫描组件

```bash
w-agent scan .
```

### 5.2 运行默认 Agent

```bash
w-agent run "Hello World"
```

### 5.3 启动 FastAPI 服务器

```bash
w-agent server --host 0.0.0.0 --port 8000
```

### 5.4 迁移旧版代码

```bash
w-agent migrate .
```

## 6. 创建 Skill

创建一个名为 `skills/my_skill` 的目录，并在其中创建以下文件：

### 6.1 SKILL.md

```markdown
# My Skill

Description: A simple skill that greets users
```

### 6.2 greet.py

```python
# 技能代码
result = f"Hello, {args.get('name', 'world')}!"
```

### 6.3 加载和执行 Skill

```python
from w_agent.skills.skill import SkillLoader
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox
from pathlib import Path

async def main():
    # 加载技能
    skill = SkillLoader.load_from_directory(Path("skills/my_skill"))
    
    # 创建沙箱
    sandbox = NsJailSkillSandbox()
    
    # 执行技能
    result = await sandbox.execute(skill, "greet", {"name": "Alice"})
    print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## 7. 配置管理

```python
from w_agent.config.dynamic_config import DynamicConfigManager

# 创建配置管理器
config_manager = DynamicConfigManager()

# 设置配置
config_manager.set("api_key", "your-api-key")

# 绑定配置到对象
class MyService:
    def __init__(self):
        self.api_key = None
        config_manager.bind("api_key", self, "api_key")
    
    async def on_config_change(self, key, new_value, old_value):
        print(f"Config changed: {key} = {new_value}")

# 动态更新配置
await config_manager.update_batch({"api_key": "new-api-key"})
```

## 8. AOP 示例

```python
from w_agent.aop.pointcut import AspectJPointcut, BeforeAdvice, AfterAdvice
from w_agent.aop.proxy_factory import ProxyFactory

# 定义目标类
class Target:
    def do_something(self, value):
        print(f"Doing something with {value}")
        return f"Result: {value}"

# 定义通知
async def before_advice(joinpoint):
    print(f"Before: {joinpoint.method.__name__}")

async def after_advice(joinpoint, result):
    print(f"After: {joinpoint.method.__name__}, result: {result}")

# 创建切点
pointcut = AspectJPointcut("execution(* Target.do_something(*))")

# 创建代理
proxy_factory = ProxyFactory()
target = Target()
advices = [BeforeAdvice(before_advice), AfterAdvice(after_advice)]
proxy = proxy_factory.create_proxy(target, {"do_something": advices})

# 调用方法
result = await proxy.do_something("test")
print(f"Final result: {result}")
```

## 9. 健康检查

```python
from w_agent.observability.health import CompositeHealthIndicator, HealthIndicator

class MyHealthIndicator(HealthIndicator):
    async def health(self):
        try:
            # 检查健康状态
            return {"status": "UP", "details": {"service": "ok"}}
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}

# 创建健康指示器
health_indicator = CompositeHealthIndicator()
health_indicator.register("my_service", MyHealthIndicator())

# 检查健康状态
health = await health_indicator.check()
print(health)
```

## 10. 常见问题

### 10.1 组件未被扫描到

- 确保文件位于项目根目录或子目录中
- 确保使用了正确的装饰器（如 `@AgentComponent`）
- 确保装饰器语法正确

### 10.2 依赖注入失败

- 确保依赖项已经注册到 Bean 工厂
- 确保构造函数参数类型注解正确
- 确保没有循环依赖

### 10.3 沙箱执行失败

- 确保 nsjail 已安装（或使用 subprocess fallback）
- 确保技能代码语法正确
- 检查权限和资源限制

## 11. 下一步

- 查看 [API 文档](./api.md) 了解更多细节
- 探索 [示例代码](../examples) 学习更多用例
- 参与 [贡献](./contributing.md) 帮助改进框架
