from typing import Dict, List, Tuple, Any, Callable
from w_agent.lifecycle.order import LifecycleOrder
import asyncio

class LifecycleManager:
    def __init__(self):
        self._post_construct_map: Dict[int, List[Tuple[Any, Callable]]] = {}
        self._pre_destroy_map: Dict[int, List[Tuple[Any, Callable]]] = {}
    
    def register(self, instance: Any, order: LifecycleOrder = LifecycleOrder.SERVICE):
        # 检查类的方法
        cls = type(instance)
        for name, method in cls.__dict__.items():
            # 跳过私有方法和特殊方法
            if name.startswith("_"):
                continue
            
            if callable(method):
                # 检查方法是否有生命周期装饰器
                if hasattr(method, "__post_construct__"):
                    # 获取实例的绑定方法
                    bound_method = getattr(instance, name)
                    self._post_construct_map.setdefault(order, []).append((instance, bound_method))
                if hasattr(method, "__pre_destroy__"):
                    # 获取实例的绑定方法
                    bound_method = getattr(instance, name)
                    self._pre_destroy_map.setdefault(order, []).append((instance, bound_method))
    
    async def post_construct_all(self):
        for order in sorted(self._post_construct_map.keys()):
            for inst, func in sorted(self._post_construct_map[order], key=lambda x: getattr(x[1], "__post_construct_order__", 0)):
                await self._invoke(func, inst)
    
    async def pre_destroy_all(self):
        # 销毁顺序与初始化相反
        for order in sorted(self._pre_destroy_map.keys(), reverse=True):
            for inst, func in sorted(self._pre_destroy_map[order], key=lambda x: getattr(x[1], "__pre_destroy_order__", 0), reverse=True):
                await self._invoke(func, inst)
    
    async def _invoke(self, func: Callable, instance: Any):
        if asyncio.iscoroutinefunction(func):
            await func()
        else:
            func()