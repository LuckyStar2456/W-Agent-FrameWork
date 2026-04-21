#!/usr/bin/env python3
"""
系统检查模块
"""
from typing import Dict, List, Tuple
from w_agent.container.bean_factory import BeanFactory
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.lifecycle.manager import LifecycleManager
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox
from w_agent.distributed.lock import RedisDistributedLock
from w_agent.core.event_bus import EventBus
from w_agent.resilience.bulkhead import ResilienceManager


class Doctor:
    """系统检查器"""
    
    def __init__(self):
        """初始化"""
        self.checks = [
            self.check_bean_factory,
            self.check_config_manager,
            self.check_lifecycle_manager,
            self.check_wasm_sandbox,
            self.check_nsjail_sandbox,
            self.check_distributed_lock,
            self.check_event_bus,
            self.check_resilience_manager
        ]
    
    def check_bean_factory(self) -> Tuple[bool, str]:
        """检查BeanFactory"""
        try:
            bean_factory = BeanFactory()
            return True, "BeanFactory initialized successfully"
        except Exception as e:
            return False, f"BeanFactory initialization failed: {e}"
    
    def check_config_manager(self) -> Tuple[bool, str]:
        """检查ConfigManager"""
        try:
            config_manager = DynamicConfigManager()
            config_manager.set("test.key", "test.value")
            value = config_manager.get("test.key")
            if value == "test.value":
                return True, "ConfigManager initialized successfully"
            else:
                return False, "ConfigManager value retrieval failed"
        except Exception as e:
            return False, f"ConfigManager initialization failed: {e}"
    
    def check_lifecycle_manager(self) -> Tuple[bool, str]:
        """检查LifecycleManager"""
        try:
            lifecycle_manager = LifecycleManager()
            return True, "LifecycleManager initialized successfully"
        except Exception as e:
            return False, f"LifecycleManager initialization failed: {e}"
    
    def check_wasm_sandbox(self) -> Tuple[bool, str]:
        """检查WasmSandbox"""
        try:
            sandbox = WasmSkillSandbox()
            return True, f"WasmSandbox initialized successfully (Pyodide available: {sandbox.pyodide_available})"
        except Exception as e:
            return False, f"WasmSandbox initialization failed: {e}"
    
    def check_nsjail_sandbox(self) -> Tuple[bool, str]:
        """检查NsjailSandbox"""
        try:
            sandbox = NsJailSkillSandbox()
            return True, f"NsjailSandbox initialized successfully (Nsjail available: {sandbox.nsjail_available})"
        except Exception as e:
            return False, f"NsjailSandbox initialization failed: {e}"
    
    def check_distributed_lock(self) -> Tuple[bool, str]:
        """检查DistributedLock"""
        try:
            # 尝试导入redis模块
            import redis
            # 尝试创建Redis客户端
            redis_client = redis.Redis(host='localhost', port=6379, db=0)
            # 尝试创建锁
            lock = RedisDistributedLock(redis=redis_client, name="test-lock")
            return True, "RedisDistributedLock initialized successfully"
        except ImportError:
            return False, "RedisDistributedLock initialization failed: redis module not installed"
        except ConnectionError:
            return False, "RedisDistributedLock initialization failed: Redis server not available"
        except Exception as e:
            return False, f"RedisDistributedLock initialization failed: {e}"
    
    def check_event_bus(self) -> Tuple[bool, str]:
        """检查EventBus"""
        try:
            event_bus = EventBus()
            return True, "EventBus initialized successfully"
        except Exception as e:
            return False, f"EventBus initialization failed: {e}"
    
    def check_resilience_manager(self) -> Tuple[bool, str]:
        """检查ResilienceManager"""
        try:
            resilience_manager = ResilienceManager()
            return True, "ResilienceManager initialized successfully"
        except Exception as e:
            return False, f"ResilienceManager initialization failed: {e}"
    
    def run_all_checks(self) -> Dict[str, Tuple[bool, str]]:
        """运行所有检查"""
        results = {}
        for check in self.checks:
            name = check.__name__.replace("check_", "")
            results[name] = check()
        return results
    
    def print_results(self, results: Dict[str, Tuple[bool, str]]):
        """打印检查结果"""
        print("=== System Doctor Check Results ===")
        print("-" * 50)
        
        all_passed = True
        for name, (passed, message) in results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"{name:<25} {status} - {message}")
            if not passed:
                all_passed = False
        
        print("-" * 50)
        if all_passed:
            print("[PASS] All checks passed! System is ready.")
        else:
            print("[FAIL] Some checks failed. Please check the errors above.")
        print("-" * 50)
        
        return all_passed
