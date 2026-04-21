import asyncio
from typing import Dict
from w_agent.distributed.lock import RedisDistributedLock

class LockRenewalPool:
    """分布式锁续期池"""
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._shutdown = False
    
    def start_renewal(self, lock_id: str, lock: RedisDistributedLock):
        """开始续期锁"""
        if lock_id in self._tasks:
            return
        task = asyncio.create_task(self._renew_loop(lock_id, lock))
        self._tasks[lock_id] = task
    
    async def _renew_loop(self, lock_id: str, lock: RedisDistributedLock):
        """续期循环"""
        try:
            while not self._shutdown:
                await asyncio.sleep(lock.timeout / 3)
                if not await lock._renew():
                    break
        finally:
            self._tasks.pop(lock_id, None)
    
    async def stop_renewal(self, lock_id: str):
        """停止续期"""
        task = self._tasks.pop(lock_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    async def shutdown(self):
        """关闭续期池"""
        self._shutdown = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
