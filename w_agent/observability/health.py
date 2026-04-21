from abc import ABC, abstractmethod
from typing import Dict, Any

class HealthIndicator(ABC):
    @abstractmethod
    async def health(self) -> Dict[str, Any]: ...

class CompositeHealthIndicator:
    def __init__(self):
        self._indicators: Dict[str, HealthIndicator] = {}
    
    def register(self, name: str, indicator: HealthIndicator):
        self._indicators[name] = indicator
    
    async def check(self) -> Dict[str, Any]:
        results = {}
        overall = "UP"
        for name, ind in self._indicators.items():
            try:
                status = await ind.health()
                results[name] = status
                if status.get("status") != "UP":
                    overall = "DOWN"
            except Exception as e:
                results[name] = {"status": "DOWN", "error": str(e)}
                overall = "DOWN"
        return {"status": overall, "components": results}

class LLMHealthIndicator(HealthIndicator):
    def __init__(self, llm):
        self.llm = llm
    
    async def health(self):
        try:
            await self.llm.acheck()  # 轻量探测
            return {"status": "UP", "latency_ms": 0}  # 实际项目中需要计算延迟
        except Exception as e:
            return {"status": "DOWN", "error": str(e)}