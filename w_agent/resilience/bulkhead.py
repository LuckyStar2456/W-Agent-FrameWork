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
            # 检查函数是否已经被装饰
            if hasattr(func, "__retry__"):
                return func
            
            # 添加重试装饰器
            from w_agent.core.decorators import Retry
            retry_decorator = Retry(max_attempts, delay, backoff, retry_exceptions)
            decorated_func = retry_decorator(func)
            
            # 创建代理
            advice = self._retry_aspect.create_advice(decorated_func)
            
            # 为了支持直接调用，我们需要一个特殊的代理
            class RetryProxy:
                def __init__(self, target, advice):
                    self._target = target
                    self._advice = advice
                
                async def __call__(self, *args, **kwargs):
                    # 手动创建joinpoint并执行advice
                    from w_agent.aop.joinpoint import JoinPoint
                    joinpoint = JoinPoint(self._target, self._target, args, kwargs, [self._advice])
                    return await joinpoint.proceed()
            
            return RetryProxy(decorated_func, advice)
        return decorator
    
    def circuit_breaker(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, 
                       fallback_method: str = None):
        def decorator(func):
            # 检查函数是否已经被装饰
            if hasattr(func, "__circuit_breaker__"):
                return func
            
            # 添加断路器装饰器
            from w_agent.core.decorators import CircuitBreaker
            cb_decorator = CircuitBreaker(failure_threshold, recovery_timeout, fallback_method)
            decorated_func = cb_decorator(func)
            
            # 创建代理
            advice = self._circuit_breaker_aspect.create_advice(decorated_func)
            
            # 为了支持直接调用，我们需要一个特殊的代理
            class CircuitBreakerProxy:
                def __init__(self, target, advice):
                    self._target = target
                    self._advice = advice
                
                async def __call__(self, *args, **kwargs):
                    # 手动创建joinpoint并执行advice
                    from w_agent.aop.joinpoint import JoinPoint
                    joinpoint = JoinPoint(self._target, self._target, args, kwargs, [self._advice])
                    return await joinpoint.proceed()
            
            return CircuitBreakerProxy(decorated_func, advice)
        return decorator