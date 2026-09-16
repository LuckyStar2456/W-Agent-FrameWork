import asyncio
from functools import wraps
from typing import Dict
from w_agent.aop.aspects import RetryAspect, CircuitBreakerAspect
from w_agent.aop.proxy_factory import ProxyFactory

class Bulkhead:
    """舱壁隔离：限制并发调用数"""
    def __init__(self, name: str, max_concurrent_calls: int, max_waiting_requests: int = 0):
        self.name = name
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._waiting_queue = asyncio.Queue(maxsize=max_waiting_requests) if max_waiting_requests > 0 else None
    
    async def execute(self, coro):
        async with self._semaphore:
            return await coro

class ResilienceManager:
    def __init__(self, event_bus=None):
        self._bulkheads: Dict[str, Bulkhead] = {}
        self._retry_aspect = RetryAspect(event_bus)
        self._circuit_breaker_aspect = CircuitBreakerAspect(event_bus)
        self._proxy_factory = ProxyFactory()
    
    def bulkhead(self, name: str, max_concurrent: int):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                bh = self._bulkheads.setdefault(name, Bulkhead(name, max_concurrent))
                return await bh.execute(func(*args, **kwargs))
            return wrapper
        return decorator
    
    def retry(self, max_attempts: int = 3, delay: float = 0.1, backoff: float = 2.0, 
              retry_exceptions: tuple = (Exception,)):
        def decorator(func):
            if hasattr(func, "__retry__"):
                return func
            from w_agent.core.decorators import Retry
            return Retry(max_attempts, delay, backoff, retry_exceptions)(func)
        return decorator
    
    def circuit_breaker(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, 
                       fallback_method: str = None):
        def decorator(func):
            if hasattr(func, "__circuit_breaker__"):
                return func
            from w_agent.core.decorators import CircuitBreaker
            return CircuitBreaker(
                failure_threshold, recovery_timeout, fallback_method
            )(func)
        return decorator
