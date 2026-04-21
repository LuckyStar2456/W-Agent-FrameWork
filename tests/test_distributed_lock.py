import asyncio
import pytest
from w_agent.distributed.lock import RedisDistributedLock
from w_agent.distributed.lock_pool import LockRenewalPool

class MockRedis:
    """模拟Redis客户端"""
    def __init__(self):
        self.data = {}
        self.expiry = {}
    
    async def set(self, key, value, nx=False, ex=None):
        """模拟set命令"""
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex:
            self.expiry[key] = ex
        return True
    
    async def get(self, key):
        """模拟get命令"""
        return self.data.get(key)
    
    async def delete(self, key):
        """模拟delete命令"""
        if key in self.data:
            del self.data[key]
            return 1
        return 0
    
    async def eval(self, script, numkeys, *args):
        """模拟eval命令"""
        # 模拟释放锁的Lua脚本
        if "get" in script and "del" in script:
            key = args[0]
            value = args[1]
            if self.data.get(key) == value:
                del self.data[key]
                return 1
            return 0
        return 0
    
    async def sismember(self, key, value):
        """模拟sismember命令"""
        return value in self.data.get(key, [])
    
    async def sadd(self, key, value):
        """模拟sadd命令"""
        if key not in self.data:
            self.data[key] = []
        if value not in self.data[key]:
            self.data[key].append(value)
        return 1

class TestDistributedLock:
    """测试分布式锁模块"""
    
    def setup_method(self):
        """设置测试环境"""
        self.redis = MockRedis()
        self.lock = RedisDistributedLock(self.redis, "test_lock", timeout=10)
        self.pool = LockRenewalPool()
    
    async def test_lock_acquire_release(self):
        """测试获取和释放锁"""
        # 获取锁
        acquired = await self.lock.acquire()
        assert acquired
        
        # 尝试再次获取锁（应该失败）
        another_lock = RedisDistributedLock(self.redis, "test_lock", timeout=10)
        acquired_again = await another_lock.acquire()
        assert not acquired_again
        
        # 释放锁
        released = await self.lock.release()
        assert released
        
        # 再次获取锁（应该成功）
        acquired_again = await another_lock.acquire()
        assert acquired_again
    
    async def test_lock_renewal(self):
        """测试锁续期"""
        # 获取锁
        acquired = await self.lock.acquire()
        assert acquired
        
        # 启动续期
        self.pool.start_renewal("test_lock", self.lock)
        
        # 等待一段时间
        await asyncio.sleep(0.1)
        
        # 停止续期
        await self.pool.stop_renewal("test_lock")
        
        # 释放锁
        released = await self.lock.release()
        assert released
    
    async def test_lock_pool_shutdown(self):
        """测试锁池关闭"""
        # 获取锁
        acquired = await self.lock.acquire()
        assert acquired
        
        # 启动续期
        self.pool.start_renewal("test_lock", self.lock)
        
        # 关闭池
        await self.pool.shutdown()
        
        # 释放锁
        released = await self.lock.release()
        assert released

if __name__ == "__main__":
    test = TestDistributedLock()
    test.setup_method()
    asyncio.run(test.test_lock_acquire_release())
    asyncio.run(test.test_lock_renewal())
    asyncio.run(test.test_lock_pool_shutdown())
    print("All distributed lock tests passed!")
