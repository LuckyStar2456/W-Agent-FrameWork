"""Agent基类"""

class BaseAgent:
    """基础Agent类"""
    async def arun(self, prompt: str) -> str:
        """异步运行Agent"""
        raise NotImplementedError
