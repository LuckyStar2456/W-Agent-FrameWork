#!/usr/bin/env python3
"""
示例MySQL服务
"""
from w_agent import PostConstruct, PreDestroy, DynamicConfigManager
import asyncio

# 尝试导入mysql.connector模块
try:
    import mysql.connector
except ImportError:
    mysql = None
    mysql_connector = None
else:
    mysql_connector = mysql.connector


class MySQLService:
    """示例MySQL服务"""
    
    def __init__(self, config_manager):
        """初始化"""
        self.config_manager = config_manager
        self.host = None
        self.port = None
        self.user = None
        self.password = None
        self.database = None
        
        # 绑定配置
        self.config_manager.bind("mysql.host", self, "host")
        self.config_manager.bind("mysql.port", self, "port")
        self.config_manager.bind("mysql.user", self, "user")
        self.config_manager.bind("mysql.password", self, "password")
        self.config_manager.bind("mysql.database", self, "database")
        
        self.connection = None
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        try:
            if mysql_connector is None:
                print("MySQLService initialized: mysql-connector-python not installed")
                self.connection = None
                return
            
            self.connection = mysql_connector.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database
            )
            print("MySQLService initialized successfully")
        except Exception as e:
            print(f"Failed to initialize MySQL connection: {e}")
            self.connection = None
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        if self.connection:
            try:
                self.connection.close()
            except Exception as e:
                print(f"Failed to close MySQL connection: {e}")
        print("MySQLService destroyed")
    
    def execute(self, query, params=None):
        """执行SQL查询"""
        if not self.connection:
            return None
        try:
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(query, params or ())
            result = cursor.fetchall()
            self.connection.commit()
            cursor.close()
            return result
        except Exception as e:
            print(f"MySQL execute failed: {e}")
            if self.connection:
                self.connection.rollback()
            return None
    
    def insert(self, table, data):
        """插入数据"""
        if not self.connection:
            return False
        try:
            columns = list(data.keys())
            values = list(data.values())
            placeholders = ', '.join(['%s'] * len(values))
            query = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            
            cursor = self.connection.cursor()
            cursor.execute(query, values)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"MySQL insert failed: {e}")
            if self.connection:
                self.connection.rollback()
            return False
    
    def update(self, table, data, condition):
        """更新数据"""
        if not self.connection:
            return False
        try:
            set_clause = ', '.join([f"{key} = %s" for key in data.keys()])
            values = list(data.values())
            query = f"UPDATE {table} SET {set_clause} WHERE {condition}"
            
            cursor = self.connection.cursor()
            cursor.execute(query, values)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"MySQL update failed: {e}")
            if self.connection:
                self.connection.rollback()
            return False
    
    def delete(self, table, condition):
        """删除数据"""
        if not self.connection:
            return False
        try:
            query = f"DELETE FROM {table} WHERE {condition}"
            
            cursor = self.connection.cursor()
            cursor.execute(query)
            self.connection.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"MySQL delete failed: {e}")
            if self.connection:
                self.connection.rollback()
            return False
