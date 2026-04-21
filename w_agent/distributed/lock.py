import asyncio
import uuid
from typing import Optional

class RedisDistributedLock:
    """Redis分布式锁"""
    def __init__(self, redis, name: str, timeout: float = 30.0):
        self.redis = redis
        self.name = name
        self.timeout = timeout
        self._lock_id = str(uuid.uuid4())
    
    async def acquire(self) -> bool:
        """获取锁"""
        try:
            result = await self.redis.set(
                self.name,
                self._lock_id,
                nx=True,
                ex=int(self.timeout)
            )
            return result is True
        except Exception:
            return False
    
    async def release(self) -> bool:
        """释放锁"""
        try:
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1]:
                return redis.call('del', KEYS[1])
            else:
                return 0
            """
            result = await self.redis.eval(
                script,
                1,
                self.name,
                self._lock_id
            )
            return result == 1
        except Exception:
            return False
    
    async def _renew(self) -> bool:
        """续期锁"""
        try:
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1]:
                return redis.call('expire', KEYS[1], ARGV[2])
            else:
                return 0
            """
            result = await self.redis.eval(
                script,
                1,
                self.name,
                self._lock_id,
                int(self.timeout)
            )
            return result == 1
        except Exception:
            return False
