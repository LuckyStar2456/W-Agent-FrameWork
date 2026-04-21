import asyncio
import pytest
from w_agent.core.event_bus import EventBus, Event, ConfigChangedEvent

class TestEventBus:
    """测试事件总线模块"""
    
    def setup_method(self):
        """设置测试环境"""
        self.event_bus = EventBus()
        self.events_received = []
    
    async def test_event_publish_subscribe(self):
        """测试事件发布和订阅"""
        # 订阅事件
        def listener(event):
            self.events_received.append(event)
        
        self.event_bus.on("test_event", listener)
        
        # 发布事件
        event = Event(name="test_event", payload={"key": "value"})
        await self.event_bus.emit(event)
        
        # 验证事件被接收
        assert len(self.events_received) == 1
        assert self.events_received[0].name == "test_event"
        assert self.events_received[0].payload == {"key": "value"}
    
    async def test_async_listener(self):
        """测试异步监听器"""
        # 订阅事件
        async def async_listener(event):
            await asyncio.sleep(0.1)  # 模拟异步操作
            self.events_received.append(event)
        
        self.event_bus.on("test_event", async_listener)
        
        # 发布事件
        event = Event(name="test_event", payload={"key": "value"})
        await self.event_bus.emit(event)
        
        # 验证事件被接收
        assert len(self.events_received) == 1
        assert self.events_received[0].name == "test_event"
    
    async def test_multiple_listeners(self):
        """测试多个监听器"""
        # 订阅多个监听器
        def listener1(event):
            self.events_received.append(f"listener1: {event.name}")
        
        def listener2(event):
            self.events_received.append(f"listener2: {event.name}")
        
        self.event_bus.on("test_event", listener1)
        self.event_bus.on("test_event", listener2)
        
        # 发布事件
        event = Event(name="test_event", payload={"key": "value"})
        await self.event_bus.emit(event)
        
        # 验证所有监听器都被触发
        assert len(self.events_received) == 2
        assert "listener1: test_event" in self.events_received
        assert "listener2: test_event" in self.events_received
    
    async def test_config_changed_event(self):
        """测试ConfigChangedEvent"""
        # 订阅事件
        def listener(event):
            self.events_received.append(event)
        
        self.event_bus.on("config_changed", listener)
        
        # 发布ConfigChangedEvent
        event = ConfigChangedEvent(key="test_key", old_value="old", new_value="new")
        await self.event_bus.emit(event)
        
        # 验证事件被接收
        assert len(self.events_received) == 1
        assert self.events_received[0].name == "config_changed"
        assert self.events_received[0].payload["key"] == "test_key"
        assert self.events_received[0].payload["old"] == "old"
        assert self.events_received[0].payload["new"] == "new"

if __name__ == "__main__":
    test = TestEventBus()
    test.setup_method()
    asyncio.run(test.test_event_publish_subscribe())
    test.setup_method()
    asyncio.run(test.test_async_listener())
    test.setup_method()
    asyncio.run(test.test_multiple_listeners())
    test.setup_method()
    asyncio.run(test.test_config_changed_event())
    print("All event bus tests passed!")
