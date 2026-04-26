import asyncio
import pytest
from w_agent import DynamicConfigManager

class TestConfigManager:
    """测试配置管理"""
    
    async def test_set_and_get(self):
        """测试设置和获取配置"""
        config_manager = DynamicConfigManager()
        
        # 设置配置
        config_manager.set("test_key", "test_value")
        
        # 获取配置
        assert config_manager.get("test_key") == "test_value"
        assert config_manager.get("non_existent_key", "default") == "default"
    
    async def test_bind_and_update(self):
        """测试绑定和更新配置"""
        config_manager = DynamicConfigManager()
        
        # 创建测试类
        class TestClass:
            def __init__(self):
                self.value = None
                self.change_count = 0
            
            async def on_config_change(self, key, new_value, old_value):
                self.change_count += 1
        
        # 绑定配置
        test_obj = TestClass()
        config_manager.bind("test_key", test_obj, "value")
        
        # 初始值应为None
        assert test_obj.value is None
        
        # 更新配置
        await config_manager.update_batch({"test_key": "test_value"})
        assert test_obj.value == "test_value"
        assert test_obj.change_count == 1
        
        # 再次更新
        await config_manager.update_batch({"test_key": "new_value"})
        assert test_obj.value == "new_value"
        assert test_obj.change_count == 2
    
    async def test_batch_update(self):
        """测试批量更新"""
        config_manager = DynamicConfigManager()
        
        # 创建测试类
        class TestClass:
            def __init__(self):
                self.value1 = None
                self.value2 = None
                self.change_count = 0
            
            async def on_config_change(self, key, new_value, old_value):
                self.change_count += 1
        
        # 绑定配置
        test_obj = TestClass()
        config_manager.bind("key1", test_obj, "value1")
        config_manager.bind("key2", test_obj, "value2")
        
        # 批量更新
        await config_manager.update_batch({"key1": "value1", "key2": "value2"})
        assert test_obj.value1 == "value1"
        assert test_obj.value2 == "value2"
        assert test_obj.change_count == 2
    
    async def test_bind_duplicate(self):
        """测试重复绑定"""
        config_manager = DynamicConfigManager()
        
        # 创建测试类
        class TestClass:
            def __init__(self):
                self.value = None
                self.change_count = 0
            
            async def on_config_change(self, key, new_value, old_value):
                self.change_count += 1
        
        # 绑定配置
        test_obj = TestClass()
        
        # 第一次绑定
        config_manager.bind("test_key", test_obj, "value")
        
        # 第二次绑定（应该被去重）
        config_manager.bind("test_key", test_obj, "value")
        
        # 更新配置
        await config_manager.update_batch({"test_key": "test_value"})
        
        # 只应该触发一次回调
        assert test_obj.change_count == 1

if __name__ == "__main__":
    asyncio.run(TestConfigManager().test_set_and_get())
    asyncio.run(TestConfigManager().test_bind_and_update())
    asyncio.run(TestConfigManager().test_batch_update())
    asyncio.run(TestConfigManager().test_bind_duplicate())
    print("All config tests passed!")
