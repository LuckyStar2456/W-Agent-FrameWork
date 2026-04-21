import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

class GracefulShutdownManager:
    def __init__(self, timeout: float = 30.0):
        self._active_requests = 0
        self._shutdown_event = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._timeout = timeout
        self._lock = asyncio.Lock()
    
    @asynccontextmanager
    async def request_context(self):
        """请求上下文管理器，记录活跃请求"""
        async with self._lock:
            self._active_requests += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active_requests -= 1
                if self._shutdown_event.is_set() and self._active_requests == 0:
                    self._shutdown_complete.set()
    
    async def shutdown(self):
        """触发关闭，等待活跃请求完成或超时"""
        self._shutdown_event.set()
        # 停止接收新请求（由 web 框架中间件实现）
        try:
            await asyncio.wait_for(self._shutdown_complete.wait(), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("Graceful shutdown timeout, forcing exit")
        finally:
            await self._force_cleanup()
    
    async def _force_cleanup(self):
        """强制清理资源"""
        pass
    
    def is_shutting_down(self):
        """检查是否正在关闭"""
        return self._shutdown_event.is_set()