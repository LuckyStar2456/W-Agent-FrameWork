from typing import Callable, Any, List, Dict, Optional, TYPE_CHECKING
from w_agent.core.decorators import ToolComponent
from w_agent.core.event_bus import EventBus, Event

# 尝试导入LangChain
try:
    from langchain.tools import BaseTool
    from langchain.callbacks.base import AsyncCallbackHandler
    from pydantic import BaseModel
    _langchain_available = True
except ImportError:
    _langchain_available = False
    # 定义占位符类
    class BaseTool:
        pass
    class AsyncCallbackHandler:
        pass
    class BaseModel:
        pass

class ToolMetadata:
    """工具元数据"""
    def __init__(self, name: str, description: str, args_schema: Any = None):
        self.name = name
        self.description = description
        self.args_schema = args_schema

class LangChainToolAdapter(BaseTool):
    """将 W-Agent ToolComponent 适配为 LangChain Tool"""
    def __init__(self, tool_func: Callable, metadata: ToolMetadata):
        if not _langchain_available:
            raise ImportError("LangChain is not installed. Please install with: pip install w-agent[langchain]")
        
        super().__init__(
            name=metadata.name,
            description=metadata.description,
            args_schema=metadata.args_schema
        )
        self._func = tool_func
    
    async def _arun(self, **kwargs):
        return await self._func(**kwargs)
    
    def _run(self, **kwargs):
        from asgiref.sync import async_to_sync
        return async_to_sync(self._arun)(**kwargs)

class WAgentCallbackHandler(AsyncCallbackHandler):
    """W-Agent 回调处理器"""
    def __init__(self, event_bus: EventBus):
        if not _langchain_available:
            raise ImportError("LangChain is not installed. Please install with: pip install w-agent[langchain]")
        super().__init__()
        self.event_bus = event_bus
    
    async def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs):
        """工具开始执行"""
        event = Event(
            name="langchain.tool.start",
            payload={"serialized": serialized, "input": input_str}
        )
        await self.event_bus.emit(event)
    
    async def on_tool_end(self, output: Any, **kwargs):
        """工具执行结束"""
        event = Event(
            name="langchain.tool.end",
            payload={"output": output}
        )
        await self.event_bus.emit(event)
    
    async def on_tool_error(self, error: BaseException, **kwargs):
        """工具执行错误"""
        event = Event(
            name="langchain.tool.error",
            payload={"error": str(error)}
        )
        await self.event_bus.emit(event)

def to_langchain_tools(tool_components: List[Callable]) -> List:
    """将 W-Agent ToolComponent 转换为 LangChain Tool 列表"""
    if not _langchain_available:
        return []
    
    tools = []
    for tool_func in tool_components:
        # 提取工具元数据
        name = getattr(tool_func, "__name__", tool_func.__qualname__)
        description = getattr(tool_func, "__doc__", "")
        
        # 提取参数模式（这里简化实现，实际项目中需要从函数签名生成）
        args_schema = None
        
        metadata = ToolMetadata(name=name, description=description, args_schema=args_schema)
        tool = LangChainToolAdapter(tool_func, metadata)
        tools.append(tool)
    
    return tools

def from_langchain_tool(lc_tool) -> Callable:
    """将 LangChain Tool 注册为 W-Agent ToolComponent"""
    if not _langchain_available:
        raise ImportError("LangChain is not installed. Please install with: pip install w-agent[langchain]")
    
    def decorator(func):
        # 动态生成异步函数
        async def wrapper(**kwargs):
            if hasattr(lc_tool, "_arun"):
                return await lc_tool._arun(**kwargs)
            elif hasattr(lc_tool, "run"):
                return lc_tool.run(**kwargs)
            else:
                raise NotImplementedError("LangChain tool does not have run or _arun method")
        
        # 设置函数属性
        wrapper.__name__ = lc_tool.name
        wrapper.__doc__ = lc_tool.description
        
        # 添加 ToolComponent 装饰器
        return ToolComponent(name=lc_tool.name)(wrapper)
    
    return decorator