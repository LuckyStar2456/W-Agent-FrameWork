#!/usr/bin/env python3
"""
示例Redis服务
"""
from w_agent.core.decorators import PostConstruct, PreDestroy
from w_agent.config.dynamic_config import DynamicConfigManager
import asyncio

# 尝试导入redis模块
try:
    import redis
except ImportError:
    redis = None


class RedisService:
    """示例Redis服务"""
    
    def __init__(self, config_manager):
        """初始化"""
        self.config_manager = config_manager
        self.host = None
        self.port = None
        self.db = None
        self.password = None
        
        # 绑定配置
        self.config_manager.bind("redis.host", self, "host")
        self.config_manager.bind("redis.port", self, "port")
        self.config_manager.bind("redis.db", self, "db")
        self.config_manager.bind("redis.password", self, "password")
        
        self.client = None
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
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
            try:
                self.client.close()
            except Exception as e:
                print(f"Failed to close Redis client: {e}")
        print("RedisService destroyed")
    
    def get(self, key):
        """获取缓存"""
        if not self.client:
            return None
        try:
            return self.client.get(key)
        except Exception as e:
            print(f"Redis get failed: {e}")
            return None
    
    def set(self, key, value, expire=None):
        """设置缓存"""
        if not self.client:
            return False
        try:
            if expire:
                self.client.setex(key, expire, value)
            else:
                self.client.set(key, value)
            return True
        except Exception as e:
            print(f"Redis set failed: {e}")
            return False
    
    def delete(self, key):
        """删除缓存"""
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            print(f"Redis delete failed: {e}")
            return False
    
    def exists(self, key):
        """检查键是否存在"""
        if not self.client:
            return False
        try:
            return self.client.exists(key) > 0
        except Exception as e:
            print(f"Redis exists failed: {e}")
            return False
