from typing import Dict, Any, Callable, Set, Tuple
import asyncio

class DynamicConfigManager:
    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable]] = {}
        self._bound_attrs: Dict[str, Set[Tuple[object, str]]] = {}  # 去重
        self._update_lock = asyncio.Lock()
    
    def bind(self, key: str, target: Any, attribute: str):
        """绑定配置到对象属性，自动去重"""
        key_id = (id(target), attribute)
        if key in self._bound_attrs and key_id in self._bound_attrs[key]:
            return  # 已绑定，不再重复
        self._bound_attrs.setdefault(key, set()).add(key_id)
        
        initial_value = self.get(key)
        setattr(target, attribute, initial_value)
        
        async def updater(new_value, old_value):
            setattr(target, attribute, new_value)
            if hasattr(target, "on_config_change"):
                await target.on_config_change(key, new_value, old_value)
        
        self._listeners.setdefault(key, []).append(updater)
    
    async def update_batch(self, changes: Dict[str, Any]):
        """批量原子更新：先全量更新内存，再统一触发监听器"""
        async with self._update_lock:
            old_values = {k: self._config.get(k) for k in changes}
            self._config.update(changes)
            # 先收集所有受影响的监听器，避免重复触发
            affected_keys = set(changes.keys())
            for key in affected_keys:
                for listener in self._listeners.get(key, []):
                    await listener(changes[key], old_values.get(key))
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置单个配置值"""
        self._config[key] = value
    
    def remove(self, key: str):
        """移除配置值"""
        if key in self._config:
            del self._config[key]