from typing import Any, Callable, List
import asyncio

class JoinPoint:
    """连接点抽象，支持 proceed 链式调用"""
    def __init__(self, target, method, args, kwargs, chain: List[Callable]):
        self.target = target
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self._chain = chain
        self._current_index = 0
    
    async def proceed(self):
        if self._current_index >= len(self._chain):
            # 执行原始方法
            if asyncio.iscoroutinefunction(self.method):
                # 检查是否是方法调用（target是对象且method是方法）
                if hasattr(self.method, '__self__') and self.method.__self__ is not None:
                    # 方法调用，不需要传递target
                    return await self.method(*self.args, **self.kwargs)
                else:
                    # 函数调用，直接调用
                    return await self.method(*self.args, **self.kwargs)
            else:
                # 检查是否是方法调用（target是对象且method是方法）
                if hasattr(self.method, '__self__') and self.method.__self__ is not None:
                    # 方法调用，不需要传递target
                    return self.method(*self.args, **self.kwargs)
                else:
                    # 函数调用，直接调用
                    return self.method(*self.args, **self.kwargs)
        advice = self._chain[self._current_index]
        self._current_index += 1
        return await advice(self, self._proceed_next)
    
    async def _proceed_next(self):
        return await self.proceed()