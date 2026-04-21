import asyncio
import pytest
from w_agent.aop.pointcut import AspectJPointcut, BeforeAdvice, AfterAdvice, AroundAdvice
from w_agent.aop.proxy_factory import ProxyFactory
from w_agent.aop.joinpoint import JoinPoint

class TestAOP:
    """测试AOP功能"""
    
    def test_pointcut_execution_match(self):
        """测试execution切点匹配"""
        # 创建切点
        pointcut = AspectJPointcut("execution(* TestClass.do_something(*))")
        
        # 创建测试类和方法
        class TestClass:
            def do_something(self, value):
                return value
        
        test_obj = TestClass()
        method = TestClass.do_something
        
        # 测试匹配
        assert pointcut.matches(method, TestClass, "test_bean", ("test",))
    
    def test_pointcut_within_match(self):
        """测试within切点匹配"""
        # 创建切点
        pointcut = AspectJPointcut("within(TestClass)")
        
        # 创建测试类
        class TestClass:
            def do_something(self, value):
                return value
        
        method = TestClass.do_something
        
        # 测试匹配
        assert pointcut.matches(method, TestClass, "test_bean", ("test",))
    
    def test_pointcut_bean_match(self):
        """测试bean切点匹配"""
        # 创建切点
        pointcut = AspectJPointcut("bean(test_bean)")
        
        # 创建测试类和方法
        class TestClass:
            def do_something(self, value):
                return value
        
        method = TestClass.do_something
        
        # 测试匹配
        assert pointcut.matches(method, TestClass, "test_bean", ("test",))
        assert not pointcut.matches(method, TestClass, "other_bean", ("test",))
    
    def test_pointcut_args_match(self):
        """测试args切点匹配"""
        # 创建切点
        pointcut = AspectJPointcut("args(str)")
        
        # 创建测试类和方法
        class TestClass:
            def do_something(self, value):
                return value
        
        method = TestClass.do_something
        
        # 测试匹配
        assert pointcut.matches(method, TestClass, "test_bean", ("test",))
        assert not pointcut.matches(method, TestClass, "test_bean", (123,))
    
    async def test_advice_chain(self):
        """测试通知链执行顺序"""
        # 创建目标类
        class Target:
            def do_something(self, value):
                return f"Result: {value}"
        
        # 创建通知
        execution_order = []
        
        async def before_advice(joinpoint):
            execution_order.append("before")
        
        async def after_advice(joinpoint, result):
            execution_order.append("after")
        
        async def around_advice(joinpoint, proceed):
            execution_order.append("around_before")
            result = await proceed()
            execution_order.append("around_after")
            return result
        
        # 创建代理
        proxy_factory = ProxyFactory()
        target = Target()
        advices = [
            BeforeAdvice(before_advice),
            AroundAdvice(around_advice),
            AfterAdvice(after_advice)
        ]
        proxy = proxy_factory.create_proxy(target, {"do_something": advices})
        
        # 调用方法
        result = await proxy.do_something("test")
        
        # 验证执行顺序
        assert execution_order == ["before", "around_before", "around_after", "after"]
        assert result == "Result: test"

if __name__ == "__main__":
    test = TestAOP()
    test.test_pointcut_execution_match()
    test.test_pointcut_within_match()
    test.test_pointcut_bean_match()
    test.test_pointcut_args_match()
    asyncio.run(test.test_advice_chain())
    print("All AOP tests passed!")
