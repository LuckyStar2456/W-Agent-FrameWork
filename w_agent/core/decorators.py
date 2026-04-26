"""W-Agent 组件装饰器"""

from typing import Optional, Dict, Any
import functools

class Component:
    """组件装饰器基类"""
    def __init__(self, name: Optional[str] = None, **kwargs):
        self.name = name
        self.kwargs = kwargs
    
    def __call__(self, cls_or_func):
        # 设置组件元数据
        setattr(cls_or_func, "__component__", True)
        setattr(cls_or_func, "__component_name__", self.name)
        setattr(cls_or_func, "__component_kwargs__", self.kwargs)
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

class PostConstruct:
    """初始化后执行装饰器"""
    def __init__(self, order: int = 0):
        self.order = order
    
    def __call__(self, func):
        # 直接在函数上设置属性
        func.__post_construct__ = True
        func.__post_construct_order__ = self.order
        # 定义一个包装函数，调用被装饰的函数
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        # 在包装函数上也设置相应的属性
        wrapper.__post_construct__ = True
        wrapper.__post_construct_order__ = self.order
        # 返回包装函数
        return wrapper

class PreDestroy:
    """销毁前执行装饰器"""
    def __init__(self, order: int = 0):
        self.order = order
    
    def __call__(self, func):
        # 直接在函数上设置属性
        func.__pre_destroy__ = True
        func.__pre_destroy_order__ = self.order
        # 定义一个包装函数，调用被装饰的函数
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        # 在包装函数上也设置相应的属性
        wrapper.__pre_destroy__ = True
        wrapper.__pre_destroy_order__ = self.order
        # 返回包装函数
        return wrapper

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
        setattr(func, "__retry__", True)
        setattr(func, "__retry_max_attempts__", self.max_attempts)
        setattr(func, "__retry_delay__", self.delay)
        setattr(func, "__retry_backoff__", self.backoff)
        setattr(func, "__retry_exceptions__", self.retry_exceptions)
        return func

class CircuitBreaker:
    """断路器装饰器"""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, 
                 fallback_method: str = None):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fallback_method = fallback_method
    
    def __call__(self, func):
        setattr(func, "__circuit_breaker__", True)
        setattr(func, "__circuit_breaker_failure_threshold__", self.failure_threshold)
        setattr(func, "__circuit_breaker_recovery_timeout__", self.recovery_timeout)
        setattr(func, "__circuit_breaker_fallback_method__", self.fallback_method)
        return func
