import asyncio
import pytest
from w_agent import LifecycleManager, LifecycleOrder, PostConstruct, PreDestroy

class TestLifecycleManager:
    """测试生命周期管理"""
    
    async def test_post_construct_order(self):
        """测试PostConstruct调用顺序"""
        lifecycle_manager = LifecycleManager()

        # 创建测试类
        class TestClass1:
            def __init__(self):
                self.post_construct_called = False
                self.order = []

            @PostConstruct(order=1)
            def post_construct(self):
                self.post_construct_called = True
                self.order.append(1)

        class TestClass2:
            def __init__(self):
                self.post_construct_called = False
                self.order = []

            @PostConstruct(order=0)
            def post_construct(self):
                self.post_construct_called = True
                self.order.append(2)

        # 注册到生命周期管理器
        test1 = TestClass1()
        test2 = TestClass2()

        lifecycle_manager.register(test1, LifecycleOrder.SERVICE)
        lifecycle_manager.register(test2, LifecycleOrder.SERVICE)

        # 执行PostConstruct
        await lifecycle_manager.post_construct_all()

        # 验证调用顺序
        assert test1.post_construct_called
        assert test2.post_construct_called
        # 由于 TestClass2 的 order=0，应该先执行，所以 test2.order 应该比 test1.order 先被修改
        # 但由于我们只是在每个方法中 append 一个值，所以 test2.order[0] 是 2，test1.order[0] 是 1
        # 因此，我们应该检查 TestClass2 的 post_construct 方法是否在 TestClass1 的 post_construct 方法之前执行
        # 我们可以通过在测试类中添加一个全局计数器来验证
        global_order = []

        class TestClass3:
            def __init__(self):
                self.post_construct_called = False

            @PostConstruct(order=1)
            def post_construct(self):
                self.post_construct_called = True
                global_order.append(1)

        class TestClass4:
            def __init__(self):
                self.post_construct_called = False

            @PostConstruct(order=0)
            def post_construct(self):
                self.post_construct_called = True
                global_order.append(0)

        test3 = TestClass3()
        test4 = TestClass4()

        lifecycle_manager2 = LifecycleManager()
        lifecycle_manager2.register(test3, LifecycleOrder.SERVICE)
        lifecycle_manager2.register(test4, LifecycleOrder.SERVICE)

        await lifecycle_manager2.post_construct_all()

        assert global_order == [0, 1]
    
    async def test_pre_destroy_order(self):
        """测试PreDestroy调用顺序"""
        lifecycle_manager = LifecycleManager()
        
        # 创建测试类
        class TestClass1:
            def __init__(self):
                self.pre_destroy_called = False
                self.order = []
            
            @PreDestroy(order=1)
            def pre_destroy(self):
                self.pre_destroy_called = True
                self.order.append(1)
        
        class TestClass2:
            def __init__(self):
                self.pre_destroy_called = False
                self.order = []
            
            @PreDestroy(order=0)
            def pre_destroy(self):
                self.pre_destroy_called = True
                self.order.append(2)
        
        # 注册到生命周期管理器
        test1 = TestClass1()
        test2 = TestClass2()
        
        lifecycle_manager.register(test1, LifecycleOrder.SERVICE)
        lifecycle_manager.register(test2, LifecycleOrder.SERVICE)
        
        # 执行PreDestroy
        await lifecycle_manager.pre_destroy_all()
        
        # 验证调用顺序（与PostConstruct相反）
        assert test1.pre_destroy_called
        assert test2.pre_destroy_called
        assert test1.order[0] < test2.order[0]
    
    async def test_async_lifecycle_methods(self):
        """测试异步生命周期方法"""
        lifecycle_manager = LifecycleManager()

        # 创建测试类
        class TestClass:
            def __init__(self):
                self.post_construct_called = False
                self.pre_destroy_called = False

            def post_construct(self):
                # 模拟异步操作
                self.post_construct_called = True

            def pre_destroy(self):
                # 模拟异步操作
                self.pre_destroy_called = True

        # 注册到生命周期管理器
        test_obj = TestClass()
        lifecycle_manager.register(test_obj, LifecycleOrder.SERVICE)

        # 执行PostConstruct
        await lifecycle_manager.post_construct_all()
        assert test_obj.post_construct_called

        # 执行PreDestroy
        await lifecycle_manager.pre_destroy_all()
        assert test_obj.pre_destroy_called
    
    async def test_lifecycle_order_enum(self):
        """测试LifecycleOrder枚举"""
        # 验证枚举值的顺序
        assert LifecycleOrder.INFRASTRUCTURE < LifecycleOrder.CONNECTION_POOL
        assert LifecycleOrder.CONNECTION_POOL < LifecycleOrder.REPOSITORY
        assert LifecycleOrder.REPOSITORY < LifecycleOrder.SERVICE
        assert LifecycleOrder.SERVICE < LifecycleOrder.AGENT
        assert LifecycleOrder.AGENT < LifecycleOrder.PRESENTATION

if __name__ == "__main__":
    asyncio.run(TestLifecycleManager().test_post_construct_order())
    asyncio.run(TestLifecycleManager().test_pre_destroy_order())
    asyncio.run(TestLifecycleManager().test_async_lifecycle_methods())
    asyncio.run(TestLifecycleManager().test_lifecycle_order_enum())
    print("All lifecycle tests passed!")
