import asyncio
import pytest
from w_agent.container.bean_factory import BeanFactory, BeanDefinition, Scope
from w_agent.exceptions.framework_errors import BeanNotFoundError, InjectionError

class TestBeanFactory:
    """测试BeanFactory"""
    
    async def test_register_and_get_bean(self):
        """测试注册和获取Bean"""
        factory = BeanFactory()
        
        # 定义一个测试类
        class TestService:
            def __init__(self):
                self.value = "test"
        
        # 注册Bean
        factory.register_bean("test_service", TestService())
        
        # 获取Bean
        service = await factory.get_bean("test_service")
        assert service.value == "test"
    
    async def test_bean_not_found(self):
        """测试Bean不存在的情况"""
        factory = BeanFactory()
        
        with pytest.raises(BeanNotFoundError):
            await factory.get_bean("non_existent_bean")
    
    async def test_prototype_scope(self):
        """测试原型作用域"""
        factory = BeanFactory()
        
        # 定义一个测试类
        class TestPrototype:
            def __init__(self):
                self.id = id(self)
        
        # 注册原型Bean
        definition = BeanDefinition(
            name="test_prototype",
            bean_type=TestPrototype,
            scope=Scope.PROTOTYPE
        )
        factory.register_bean_definition("test_prototype", definition)
        
        # 获取两个实例，应该是不同的
        instance1 = await factory.get_bean("test_prototype")
        instance2 = await factory.get_bean("test_prototype")
        assert instance1.id != instance2.id
    
    async def test_singleton_scope(self):
        """测试单例作用域"""
        factory = BeanFactory()
        
        # 定义一个测试类
        class TestSingleton:
            def __init__(self):
                self.id = id(self)
        
        # 注册单例Bean
        definition = BeanDefinition(
            name="test_singleton",
            bean_type=TestSingleton,
            scope=Scope.SINGLETON
        )
        factory.register_bean_definition("test_singleton", definition)
        
        # 获取两个实例，应该是相同的
        instance1 = await factory.get_bean("test_singleton")
        instance2 = await factory.get_bean("test_singleton")
        assert instance1.id == instance2.id
    
    async def test_constructor_injection(self):
        """测试构造器注入"""
        factory = BeanFactory()
        
        # 定义依赖类
        class Dependency:
            def __init__(self):
                self.value = "dependency"
        
        # 定义依赖注入类
        class Dependent:
            def __init__(self, dependency: Dependency):
                self.dependency = dependency
        
        # 注册依赖
        factory.register_bean("dependency", Dependency())
        
        # 注册依赖注入类
        definition = BeanDefinition(
            name="dependent",
            bean_type=Dependent
        )
        factory.register_bean_definition("dependent", definition)
        
        # 获取实例并验证注入
        dependent = await factory.get_bean("dependent")
        assert dependent.dependency.value == "dependency"

if __name__ == "__main__":
    asyncio.run(TestBeanFactory().test_register_and_get_bean())
    asyncio.run(TestBeanFactory().test_bean_not_found())
    asyncio.run(TestBeanFactory().test_prototype_scope())
    asyncio.run(TestBeanFactory().test_singleton_scope())
    asyncio.run(TestBeanFactory().test_constructor_injection())
    print("All tests passed!")
