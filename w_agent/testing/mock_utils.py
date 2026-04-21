from typing import Any, Callable

class AgentTestContext:
    def __init__(self):
        self._prototype_mocks = {}
    
    def mock_value(self, key: str, value: Any):
        """Mock @Value 配置"""
        config_manager = ctx.get_bean("config_manager")
        config_manager._config[key] = value
    
    def mock_prototype_bean(self, name: str, factory: Callable):
        """Mock 原型作用域 Bean"""
        def wrapper():
            return factory()
        self._prototype_mocks[name] = wrapper
    
    def get_mock(self, name: str) -> Callable:
        """获取Mock"""
        return self._prototype_mocks.get(name)

# 全局测试上下文
ctx = None