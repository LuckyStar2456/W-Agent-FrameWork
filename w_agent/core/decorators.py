"""W-Agent 组件装饰器"""

from typing import Optional, Dict, Any
import asyncio
import functools
import inspect
import time

class Component:
    """组件装饰器基类"""
    def __new__(cls, name: Optional[str] = None, **kwargs):
        # Support both @ServiceComponent and @ServiceComponent(...).
        if callable(name) and not isinstance(name, str):
            target = name
            instance = super().__new__(cls)
            instance.name = None
            instance.kwargs = kwargs
            return instance(target)
        return super().__new__(cls)

    def __init__(self, name: Optional[str] = None, **kwargs):
        self.name = name
        self.kwargs = kwargs
    
    def __call__(self, cls_or_func):
        # 设置组件元数据
        setattr(cls_or_func, "__component__", True)
        setattr(cls_or_func, "__component_name__", self.name)
        setattr(cls_or_func, "__component_kwargs__", self.kwargs)
        setattr(
            cls_or_func,
            "__component_type__",
            type(self).__name__.replace("Component", "").lower(),
        )
        return cls_or_func

class AgentComponent(Component):
    """Agent组件装饰器"""
    pass

class ServiceComponent(Component):
    """Service组件装饰器"""
    pass

class ToolComponent(Component):
    """Tool组件装饰器"""
    def __init__(self, name: Optional[str] = None, description: Optional[str] = None, **kwargs):
        super().__init__(name=name, description=description, **kwargs)

class RepositoryComponent(Component):
    """Repository组件装饰器"""
    pass

class ControllerComponent(Component):
    """Controller组件装饰器"""
    pass

def PostConstruct(func=None, *, order: int = 0):
    """Mark a lifecycle initializer.

    Both ``@PostConstruct`` and ``@PostConstruct(order=1)`` are supported.
    The original callable is returned unchanged so coroutine functions retain
    their async identity.
    """
    def decorator(target):
        target.__post_construct__ = True
        target.__post_construct_order__ = order
        return target

    if func is None:
        return decorator
    return decorator(func)


def PreDestroy(func=None, *, order: int = 0):
    """Mark a lifecycle cleanup method; supports both decorator forms."""
    def decorator(target):
        target.__pre_destroy__ = True
        target.__pre_destroy_order__ = order
        return target

    if func is None:
        return decorator
    return decorator(func)

class Value:
    """配置值注入装饰器"""
    def __init__(self, key: str, default: Any = None):
        self.key = key
        self.default = default
    
    def __call__(self, func):
        setattr(func, "__value_key__", self.key)
        setattr(func, "__value_default__", self.default)
        return func

class Autowired:
    """自动注入装饰器"""
    def __init__(self, name: Optional[str] = None):
        self.name = name
    
    def __call__(self, func):
        setattr(func, "__autowired__", True)
        setattr(func, "__autowired_name__", self.name)
        return func

class Qualifier:
    """限定符装饰器，用于指定Bean名称"""
    def __init__(self, name: str):
        self.name = name
    
    def __call__(self, func):
        setattr(func, "__qualifier__", self.name)
        return func

class Retry:
    """重试装饰器"""
    def __init__(self, max_attempts: int = 3, delay: float = 0.1, backoff: float = 2.0, 
                 retry_exceptions: tuple = (Exception,)):
        self.max_attempts = max_attempts
        self.delay = delay
        self.backoff = backoff
        self.retry_exceptions = retry_exceptions
    
    def __call__(self, func):
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        def mark(target):
            setattr(target, "__retry__", True)
            setattr(target, "__retry_max_attempts__", self.max_attempts)
            setattr(target, "__retry_delay__", self.delay)
            setattr(target, "__retry_backoff__", self.backoff)
            setattr(target, "__retry_exceptions__", self.retry_exceptions)
            return target

        mark(func)
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                current_delay = self.delay
                for attempt in range(1, self.max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)
                    except self.retry_exceptions:
                        if attempt >= self.max_attempts:
                            raise
                        await asyncio.sleep(current_delay)
                        current_delay *= self.backoff

            return mark(async_wrapper)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = self.delay
            for attempt in range(1, self.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except self.retry_exceptions:
                    if attempt >= self.max_attempts:
                        raise
                    time.sleep(current_delay)
                    current_delay *= self.backoff

        return mark(wrapper)

class CircuitBreaker:
    """断路器装饰器"""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, 
                 fallback_method: str = None):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fallback_method = fallback_method
    
    def __call__(self, func):
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        state = {"status": "CLOSED", "failures": 0, "opened_at": 0.0}

        def mark(target):
            setattr(target, "__circuit_breaker__", True)
            setattr(target, "__circuit_breaker_failure_threshold__", self.failure_threshold)
            setattr(target, "__circuit_breaker_recovery_timeout__", self.recovery_timeout)
            setattr(target, "__circuit_breaker_fallback_method__", self.fallback_method)
            setattr(target, "__circuit_breaker_state__", state)
            return target

        def allow_call():
            if state["status"] != "OPEN":
                return True
            if time.monotonic() - state["opened_at"] >= self.recovery_timeout:
                state["status"] = "HALF_OPEN"
                return True
            return False

        def record_success():
            state.update(status="CLOSED", failures=0, opened_at=0.0)

        def record_failure():
            state["failures"] += 1
            if state["status"] == "HALF_OPEN" or state["failures"] >= self.failure_threshold:
                state["status"] = "OPEN"
                state["opened_at"] = time.monotonic()

        def get_fallback(args):
            if self.fallback_method and args and hasattr(args[0], self.fallback_method):
                return getattr(args[0], self.fallback_method)
            return None

        mark(func)
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not allow_call():
                    fallback = get_fallback(args)
                    if fallback:
                        result = fallback(*args[1:], **kwargs)
                        return await result if inspect.isawaitable(result) else result
                    raise RuntimeError(f"Circuit breaker is open for {func.__qualname__}")
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    record_failure()
                    raise
                record_success()
                return result

            return mark(async_wrapper)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not allow_call():
                fallback = get_fallback(args)
                if fallback:
                    return fallback(*args[1:], **kwargs)
                raise RuntimeError(f"Circuit breaker is open for {func.__qualname__}")
            try:
                result = func(*args, **kwargs)
            except Exception:
                record_failure()
                raise
            record_success()
            return result

        return mark(wrapper)
