from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
from typing import Optional, Any
from w_agent.container.bean_factory import BeanFactory
from w_agent.observability.health import CompositeHealthIndicator
from w_agent.lifecycle.graceful_shutdown import GracefulShutdownManager

class BaseAgent:
    """基础Agent类"""
    async def arun(self, prompt: str) -> str:
        """异步运行Agent"""
        raise NotImplementedError

class FastAPIContext:
    """FastAPI上下文"""
    def __init__(self):
        self.bean_factory = BeanFactory()
        self.health_indicator = CompositeHealthIndicator()
        self.shutdown_manager = GracefulShutdownManager()

# 全局上下文
ctx = FastAPIContext()

async def get_agent(agent_name: str = "default_agent") -> BaseAgent:
    """FastAPI 依赖项，从容器获取 Agent"""
    return await ctx.bean_factory.get_bean(agent_name)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    # 启动时执行
    print("FastAPI starting...")
    # 这里可以添加初始化逻辑
    
    yield
    
    # 关闭时执行
    print("FastAPI shutting down...")
    await ctx.bean_factory.destroy_singletons()
    await ctx.shutdown_manager.shutdown()

# 创建FastAPI应用实例
app = FastAPI(lifespan=lifespan)

# 注册路由
@app.post("/chat")
async def chat(prompt: str, agent: BaseAgent = Depends(get_agent)):
    """聊天端点"""
    result = await agent.arun(prompt)
    return {"response": result}

# 健康检查端点
@app.get("/health/live")
async def liveness():
    """存活探针"""
    return {"status": "alive"}

@app.get("/health/ready")
async def readiness():
    """就绪探针"""
    health = await ctx.health_indicator.check()
    status_code = 200 if health["status"] == "UP" else 503
    return JSONResponse(status_code=status_code, content=health)

# 优雅关闭中间件
@app.middleware("http")
async def graceful_shutdown_middleware(request: Request, call_next):
    """优雅关闭中间件"""
    if ctx.shutdown_manager.is_shutting_down():
        return Response("Server is shutting down", status_code=503, headers={"Retry-After": "10"})
    async with ctx.shutdown_manager.request_context():
        return await call_next(request)

# 注册Bean的示例
"""
def register_beans():
    # 注册配置管理器
    config_manager = DynamicConfigManager()
    ctx.bean_factory.register_bean("config_manager", config_manager)
    
    # 注册健康指示器
    llm_health_indicator = LLMHealthIndicator(llm_client)
    ctx.health_indicator.register("llm", llm_health_indicator)
    
    # 注册Agent
    class MyAgent(BaseAgent):
        def __init__(self, config_manager):
            self.config_manager = config_manager
        
        async def arun(self, prompt: str) -> str:
            return f"Hello, {prompt}!"
    
    agent = MyAgent(config_manager)
    ctx.bean_factory.register_bean("default_agent", agent)

# 在应用启动时注册Bean
register_beans()
"""
