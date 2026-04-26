#!/usr/bin/env python3
"""
示例Redis服务
"""
from w_agent import PostConstruct, PreDestroy, DynamicConfigManager
import redis
import asyncio


class RedisService:
    """示例Redis服务"""

    
    def __init__(self, config_manager):
        """初始化"""
        self.config_manager = config_manager
        self.host = None
        self.port = None
        self.password = None
        self.db = None
        self.client = None
        
        # 绑定配置
        self.config_manager.bind("redis.host", self, "host")
        self.config_manager.bind("redis.port", self, "port")
        self.config_manager.bind("redis.password", self, "password")
        self.config_manager.bind("redis.db", self, "db")
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        try:
            # 创建Redis客户端
            self.client = redis.Redis(
                host=self.host or "localhost",
                port=self.port or 6379,
                password=self.password or None,
                db=self.db or 0,
                decode_responses=True
            )
            # 测试连接
            self.client.ping()
            print("RedisService initialized successfully")
        except Exception as e:
            print(f"Failed to initialize Redis client: {e}")
            self.client = None
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        if self.client:
            self.client.close()
            print("RedisService destroyed")
    
    async def get(self, key):
        """获取值"""
        if not self.client:
            return None
        try:
            return self.client.get(key)
        except Exception as e:
            print(f"Redis get error: {e}")
            return None
    
    async def set(self, key, value, expire=None):
        """设置值"""
        if not self.client:
            return False
        try:
            if expire:
                self.client.setex(key, expire, value)
            else:
                self.client.set(key, value)
            return True
        except Exception as e:
            print(f"Redis set error: {e}")
            return False
    
    async def delete(self, key):
        """删除键"""
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            print(f"Redis delete error: {e}")
            return False
    
    async def exists(self, key):
        """检查键是否存在"""
        if not self.client:
            return False
        try:
            return bool(self.client.exists(key))
        except Exception as e:
            print(f"Redis exists error: {e}")
            return False
    
    async def increment(self, key, amount=1):
        """递增键值"""
        if not self.client:
            return None
        try:
            return self.client.incrby(key, amount)
        except Exception as e:
            print(f"Redis increment error: {e}")
            return None
    
    async def decrement(self, key, amount=1):
        """递减键值"""
        if not self.client:
            return None
        try:
            return self.client.decrby(key, amount)
        except Exception as e:
            print(f"Redis decrement error: {e}")
            return None
    
    async def hget(self, key, field):
        """获取哈希字段值"""
        if not self.client:
            return None
        try:
            return self.client.hget(key, field)
        except Exception as e:
            print(f"Redis hget error: {e}")
            return None
    
    async def hset(self, key, field, value):
        """设置哈希字段值"""
        if not self.client:
            return False
        try:
            self.client.hset(key, field, value)
            return True
        except Exception as e:
            print(f"Redis hset error: {e}")
            return False
    
    async def hgetall(self, key):
        """获取哈希所有字段"""
        if not self.client:
            return {}
        try:
            return self.client.hgetall(key)
        except Exception as e:
            print(f"Redis hgetall error: {e}")
            return {}
    
    async def lpush(self, key, *values):
        """左侧推入列表"""
        if not self.client:
            return 0
        try:
            return self.client.lpush(key, *values)
        except Exception as e:
            print(f"Redis lpush error: {e}")
            return 0
    
    async def rpush(self, key, *values):
        """右侧推入列表"""
        if not self.client:
            return 0
        try:
            return self.client.rpush(key, *values)
        except Exception as e:
            print(f"Redis rpush error: {e}")
            return 0
    
    async def lrange(self, key, start, stop):
        """获取列表范围"""
        if not self.client:
            return []
        try:
            return self.client.lrange(key, start, stop)
        except Exception as e:
            print(f"Redis lrange error: {e}")
            return []
