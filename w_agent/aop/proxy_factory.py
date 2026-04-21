from typing import Dict, Any, Callable
from w_agent.aop.joinpoint import JoinPoint

class AopProxy:
    def __init__(self, target, advices_map):
        self._target = target
        self._advices_map = advices_map
    
    def __getattribute__(self, name):
        if name in ("_target", "_advices_map"):
            return object.__getattribute__(self, name)
        target = self._target
        try:
            attr = getattr(target, name)
            if callable(attr) and name in self._advices_map:
                return self._create_advised_method(attr, self._advices_map[name])
            return attr
        except AttributeError:
            raise
    
    def __setattr__(self, name, value):
        if name in ("_target", "_advices_map"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._target, name, value)
    
    def __delattr__(self, name):
        if name in ("_target", "_advices_map"):
            object.__delattr__(self, name)
        else:
            delattr(self._target, name)
    
    def __call__(self, *args, **kwargs):
        # 直接调用目标函数
        if callable(self._target):
            return self._target(*args, **kwargs)
        # 否则，尝试调用同名方法
        method_name = getattr(self._target, "__name__", None)
        if method_name and hasattr(self._target, method_name):
            method = getattr(self, method_name)
            return method(*args, **kwargs)
        raise TypeError(f"'{type(self._target).__name__}' object is not callable")
    
    def _create_advised_method(self, original, advices):
        import asyncio
        import functools
        
        if asyncio.iscoroutinefunction(original):
            async def advised(*args, **kwargs):
                joinpoint = JoinPoint(self._target, original, args, kwargs, advices)
                return await joinpoint.proceed()
        else:
            def advised(*args, **kwargs):
                joinpoint = JoinPoint(self._target, original, args, kwargs, advices)
                # 对于同步方法，直接调用proceed
                return joinpoint.proceed()
        
        # 保留原始方法的元数据
        advised = functools.wraps(original)(advised)
        return advised

class ProxyFactory:
    def create_proxy(self, target, advices_map):
        return AopProxy(target, advices_map)