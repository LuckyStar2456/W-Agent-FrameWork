import asyncio
import pytest
from w_agent import (
    BeanFactory,
    BeanDefinition,
    Scope,
    BeanNotFoundError,
    CircularDependencyError,
    Autowired,
    PreDestroy,
)

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

    async def test_field_and_setter_injection(self):
        class Dependency:
            pass

        class FieldDependent:
            dependency: Dependency

            @Autowired()
            def dependency(self):
                pass

        class SetterDependent:
            def __init__(self):
                self.dependency = None

            @Autowired()
            def set_dependency(self, dependency: Dependency):
                self.dependency = dependency

        factory = BeanFactory()
        dependency = Dependency()
        factory.register_bean("dependency", dependency)
        factory.register_bean_definition(
            "field_dependent", BeanDefinition("field_dependent", FieldDependent)
        )
        factory.register_bean_definition(
            "setter_dependent", BeanDefinition("setter_dependent", SetterDependent)
        )

        field_dependent = await factory.get_bean("field_dependent")
        setter_dependent = await factory.get_bean("setter_dependent")

        assert field_dependent.dependency is dependency
        assert setter_dependent.dependency is dependency

    async def test_field_cycle_uses_early_singleton_references(self):
        class A:
            @Autowired("b")
            def b(self):
                pass

        class B:
            @Autowired("a")
            def a(self):
                pass

        A.__annotations__ = {"b": B}
        B.__annotations__ = {"a": A}

        factory = BeanFactory()
        factory.register_bean_definition("a", BeanDefinition("a", A))
        factory.register_bean_definition("b", BeanDefinition("b", B))

        a = await factory.get_bean("a")
        b = await factory.get_bean("b")

        assert a.b is b
        assert b.a is a
        await factory.destroy_singletons()

    async def test_constructor_cycle_fails_with_clear_error(self):
        class A:
            def __init__(self, b):
                self.b = b

        class B:
            def __init__(self, a):
                self.a = a

        A.__init__.__annotations__["b"] = B
        B.__init__.__annotations__["a"] = A

        factory = BeanFactory()
        factory.register_bean_definition("a", BeanDefinition("a", A))
        factory.register_bean_definition("b", BeanDefinition("b", B))

        with pytest.raises(CircularDependencyError, match="a -> b -> a"):
            await factory.get_bean("a")

    async def test_concurrent_singleton_creation_is_serialized(self):
        class SlowSingleton:
            created = 0

            def __init__(self):
                type(self).created += 1

            async def initialize(self):
                await asyncio.sleep(0.01)

        factory = BeanFactory()
        factory.register_bean_definition(
            "slow",
            BeanDefinition("slow", SlowSingleton, init_method="initialize"),
        )
        first, second = await asyncio.gather(
            factory.get_bean("slow"), factory.get_bean("slow")
        )
        assert first is second
        assert SlowSingleton.created == 1

    async def test_direct_singleton_is_destroyed_and_removed(self):
        class Resource:
            def __init__(self):
                self.destroyed = False

            @PreDestroy
            async def cleanup(self):
                self.destroyed = True

        factory = BeanFactory()
        resource = Resource()
        factory.register_bean("resource", resource)
        await factory.destroy_singletons()
        assert resource.destroyed
        with pytest.raises(BeanNotFoundError):
            await factory.get_bean("resource")

if __name__ == "__main__":
    asyncio.run(TestBeanFactory().test_register_and_get_bean())
    asyncio.run(TestBeanFactory().test_bean_not_found())
    asyncio.run(TestBeanFactory().test_prototype_scope())
    asyncio.run(TestBeanFactory().test_singleton_scope())
    asyncio.run(TestBeanFactory().test_constructor_injection())
    print("All tests passed!")
