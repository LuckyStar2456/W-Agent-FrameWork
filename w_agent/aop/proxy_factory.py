from typing import Dict, Any, Callable
import asyncio
import functools
from w_agent.aop.joinpoint import JoinPoint
from w_agent.aop.pointcut import BeforeAdvice, AroundAdvice, AfterAdvice

class AopProxy:
    def __init__(self, target, advices_map):
        self._target = target
        self._advices_map = advices_map
        # 缓存创建的advised方法
        self._advised_methods = {}
        # 预处理advices，分离不同类型的通知
        self._processed_advices = {}
        for method_name, advices in advices_map.items():
            self._processed_advices[method_name] = self._process_advices(advices)
    
    def _process_advices(self, advices):
        """分离不同类型的通知"""
        before_advices = []
        around_advices = []
        after_advices = []
        
        for advice in advices:
            if isinstance(advice, BeforeAdvice):
                before_advices.append(advice)
            elif isinstance(advice, AroundAdvice):
                around_advices.append(advice)
            elif isinstance(advice, AfterAdvice):
                after_advices.append(advice)
        
        return before_advices, around_advices, after_advices
    
    def __getattribute__(self, name):
        if name in ("_target", "_advices_map", "_advised_methods", "_processed_advices", "_create_advised_method", "_process_advices"):
            return object.__getattribute__(self, name)
        target = self._target
        try:
            attr = getattr(target, name)
            if callable(attr) and name in self._advices_map:
                # 检查缓存
                if name not in self._advised_methods:
                    self._advised_methods[name] = self._create_advised_method(attr, self._processed_advices[name])
                return self._advised_methods[name]
            return attr
        except AttributeError:
            raise
    
    def __setattr__(self, name, value):
        if name in ("_target", "_advices_map", "_advised_methods", "_processed_advices"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._target, name, value)
    
    def __delattr__(self, name):
        if name in ("_target", "_advices_map", "_advised_methods", "_processed_advices"):
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
    
    def _create_advised_method(self, original, processed_advices):
        """创建增强方法"""
        before_advices, around_advices, after_advices = processed_advices
        
        if asyncio.iscoroutinefunction(original):
            async def advised(*args, **kwargs):
                # 执行所有 BeforeAdvice
                for before_advice in before_advices:
                    await before_advice(None, lambda: None)
                
                # 执行所有 AroundAdvice 的前半部分和目标方法，以及 AroundAdvice 的后半部分
                # 创建一个只包含 AroundAdvice 的链
                around_chain = around_advices
                joinpoint = JoinPoint(self._target, original, args, kwargs, around_chain)
                result = await joinpoint.proceed()
                
                # 执行所有 AfterAdvice
                for after_advice in after_advices:
                    await after_advice(None, None, result)
                
                return result
        else:
            def advised(*args, **kwargs):
                # 对于同步方法，直接执行通知和目标方法
                # 执行所有 BeforeAdvice
                for before_advice in before_advices:
                    # 对于同步方法中的异步通知，使用 asyncio.run 执行
                    asyncio.run(before_advice(None, lambda: None))
                
                # 执行所有 AroundAdvice 的前半部分和目标方法，以及 AroundAdvice 的后半部分
                # 创建一个只包含 AroundAdvice 的链
                around_chain = around_advices
                joinpoint = JoinPoint(self._target, original, args, kwargs, around_chain)
                result = asyncio.run(joinpoint.proceed())
                
                # 执行所有 AfterAdvice
                for after_advice in after_advices:
                    # 对于同步方法中的异步通知，使用 asyncio.run 执行
                    asyncio.run(after_advice(None, None, result))
                
                return result
        
        # 保留原始方法的元数据
        advised = functools.wraps(original)(advised)
        return advised

class ProxyFactory:
    def create_proxy(self, target, advices_map):
        return AopProxy(target, advices_map)