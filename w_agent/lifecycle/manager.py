from typing import Dict, List, Tuple, Any, Callable
from w_agent.lifecycle.order import LifecycleOrder
import asyncio
import inspect

class LifecycleManager:
    def __init__(self):
        # 存储结构: {lifecycle_order_value: [(method_order, instance, bound_method), ...]}
        self._post_construct_map: Dict[int, List[Tuple[int, Any, Callable]]] = {}
        self._pre_destroy_map: Dict[int, List[Tuple[int, Any, Callable]]] = {}

    def register(self, instance: Any, order: LifecycleOrder = LifecycleOrder.SERVICE):
        cls = type(instance)
        
        # 直接遍历类的__dict__，查找所有方法
        for name, value in cls.__dict__.items():
            # 跳过私有方法和特殊方法
            if name.startswith('_'):
                continue
            
            try:
                # 检查是否是函数或方法，或者是装饰器对象
                if callable(value) or hasattr(value, 'func') or name in ['post_construct', 'pre_destroy']:
                    # 处理装饰器对象的情况
                    actual_func = value
                    
                    # 对于所有情况，都从实例中获取绑定的方法
                    actual_func = getattr(instance, name)
                    
                    # 检查是否有生命周期装饰器标记
                    has_post = hasattr(actual_func, '__post_construct__') or hasattr(value, '__post_construct__')
                    has_pre = hasattr(actual_func, '__pre_destroy__') or hasattr(value, '__pre_destroy__')
                    
                    # 特殊处理：直接检查方法名
                    if name == 'post_construct':
                        has_post = True
                    elif name == 'pre_destroy':
                        has_pre = True
                    
                    if has_post or has_pre:
                        # 直接使用从实例中获取的方法，不需要再手动绑定
                        bound_method = actual_func
                        
                        if has_post:
                            # 获取order值
                            method_order = getattr(actual_func, '__post_construct_order__', 0)
                            # 确保method_order是整数
                            if not isinstance(method_order, int):
                                method_order = 0
                            self._post_construct_map.setdefault(order.value, []).append(
                                (method_order, instance, bound_method)
                            )
                        
                        if has_pre:
                            # 获取order值
                            method_order = getattr(actual_func, '__pre_destroy_order__', 0)
                            # 确保method_order是整数
                            if not isinstance(method_order, int):
                                method_order = 0
                            self._pre_destroy_map.setdefault(order.value, []).append(
                                (method_order, instance, bound_method)
                            )
            except Exception as e:
                pass

    async def post_construct_all(self):
        # 收集所有方法（按 lifecycle order 排序）
        all_methods = []
        for lifecycle_order in sorted(self._post_construct_map.keys()):
            all_methods.extend(self._post_construct_map[lifecycle_order])
        
        # 按方法自身的 order 值升序（数值小的先执行）
        sorted_methods = sorted(all_methods, key=lambda x: x[0])

        # 执行
        for method_order, instance, func in sorted_methods:
            await self._invoke(func)

    async def pre_destroy_all(self):
        # 销毁顺序：先按 lifecycle order 降序，再按方法自身的 order 值降序
        for lifecycle_order in sorted(self._pre_destroy_map.keys(), reverse=True):
            methods = self._pre_destroy_map[lifecycle_order]
            sorted_methods = sorted(methods, key=lambda x: x[0], reverse=True)
            for method_order, instance, func in sorted_methods:
                await self._invoke(func)

    async def _invoke(self, func: Callable):
        """统一调用，支持同步/异步"""
        # 直接调用绑定方法，不需要获取原始函数
        if asyncio.iscoroutinefunction(func):
            result = await func()
            return result
        else:
            result = func()
            return result