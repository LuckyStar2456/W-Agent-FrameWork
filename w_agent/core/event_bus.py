from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
import asyncio
import time

@dataclass
class Event:
    name: str
    payload: Any = None
    retry_count: int = 0
    max_retries: int = 3

class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable]] = {}
        self._dead_letter_queue: List[Event] = []
    
    def on(self, event_name: str, listener: Optional[Callable] = None):
        if listener is not None:
            self._listeners.setdefault(event_name, []).append(listener)
            return listener
        else:
            def decorator(func):
                self._listeners.setdefault(event_name, []).append(func)
                return func
            return decorator
    
    async def emit(self, event: Event):
        for listener in self._listeners.get(event.name, []):
            await self._execute_listener(listener, event)
    
    async def _execute_listener(self, listener: Callable, event: Event):
        """执行监听器，支持重试"""
        retries = 0
        max_retries = event.max_retries
        
        while retries <= max_retries:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(event)
                else:
                    listener(event)
                return  # 执行成功，退出
            except Exception as e:
                print(f"Error in event listener: {e}")
                retries += 1
                if retries > max_retries:
                    # 添加到死信队列
                    self._dead_letter_queue.append(event)
                    print(f"Event {event.name} added to dead letter queue after {max_retries} retries")
                    return
                # 指数退避重试
                await asyncio.sleep(0.1 * (2 ** (retries - 1)))
    
    def get_dead_letter_queue(self) -> List[Event]:
        """获取死信队列"""
        return self._dead_letter_queue
    
    async def process_dead_letter_queue(self):
        """处理死信队列"""
        while self._dead_letter_queue:
            event = self._dead_letter_queue.pop(0)
            print(f"Processing event {event.name} from dead letter queue")
            await self.emit(event)

class ConfigChangedEvent(Event):
    def __init__(self, key: str, old_value: Any, new_value: Any):
        super().__init__("config_changed", {"key": key, "old": old_value, "new": new_value})