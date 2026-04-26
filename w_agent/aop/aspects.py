"""AOP切面实现"""

from typing import Callable, Any
import asyncio
import time
from w_agent.aop.pointcut import AroundAdvice
from w_agent.core.event_bus import EventBus, Event
from w_agent.observability.tracing import global_tracer

class RetryAspect:
    """重试切面"""
    def __init__(self, event_bus: EventBus = None):
        self.event_bus = event_bus
    
    def create_advice(self, func: Callable) -> AroundAdvice:
        """创建重试通知"""
        max_attempts = getattr(func, "__retry_max_attempts__", 3)
        delay = getattr(func, "__retry_delay__", 0.1)
        backoff = getattr(func, "__retry_backoff__", 2.0)
        retry_exceptions = getattr(func, "__retry_exceptions__", (Exception,))
        
        async def advice(joinpoint, proceed):
            span = global_tracer.start_span("aop.retry", attributes={"function": f"{func.__module__}.{func.__name__}", "max_attempts": max_attempts})
            attempts = 0
            current_delay = delay
            fallback_method = getattr(func, "__retry_fallback__", None)
            
            try:
                while attempts < max_attempts:
                    try:
                        if self.event_bus:
                            await self.event_bus.emit(Event(
                                name="retry.attempt",
                                payload={"attempt": attempts + 1, "max_attempts": max_attempts}
                            ))
                        
                        sub_span = global_tracer.start_span("aop.retry.attempt", attributes={"attempt": attempts + 1})
                        result = await proceed()
                        global_tracer.end_span(sub_span)
                        return result
                    except retry_exceptions as e:
                        attempts += 1
                        if attempts >= max_attempts:
                            if self.event_bus:
                                await self.event_bus.emit(Event(
                                    name="retry.failed",
                                    payload={"attempts": attempts, "error": str(e)}
                                ))
                            # 尝试调用fallback方法
                            if fallback_method and hasattr(joinpoint.target, fallback_method):
                                try:
                                    fallback = getattr(joinpoint.target, fallback_method)
                                    return fallback(*joinpoint.args, **joinpoint.kwargs)
                                except Exception as fallback_error:
                                    raise Exception(f"Retry failed after {max_attempts} attempts, and fallback method {fallback_method} also failed: {str(fallback_error)}") from e
                            raise Exception(f"Retry failed after {max_attempts} attempts: {str(e)}") from e
                        
                        if self.event_bus:
                            await self.event_bus.emit(Event(
                                name="retry.retrying",
                                payload={"attempt": attempts, "delay": current_delay, "error": str(e)}
                            ))
                        
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            finally:
                global_tracer.end_span(span)
        
        return AroundAdvice(advice)

class CircuitBreakerAspect:
    """断路器切面"""
    def __init__(self, event_bus: EventBus = None):
        self.event_bus = event_bus
        self._state = {}
    
    def create_advice(self, func: Callable) -> AroundAdvice:
        """创建断路器通知"""
        failure_threshold = getattr(func, "__circuit_breaker_failure_threshold__", 5)
        recovery_timeout = getattr(func, "__circuit_breaker_recovery_timeout__", 30.0)
        fallback_method = getattr(func, "__circuit_breaker_fallback_method__", None)
        
        func_key = f"{func.__module__}.{func.__name__}"
        
        # 初始化状态
        if func_key not in self._state:
            self._state[func_key] = {
                "state": "CLOSED",  # CLOSED, OPEN, HALF_OPEN
                "failure_count": 0,
                "last_failure_time": 0,
                "consecutive_successes": 0
            }
        
        async def advice(joinpoint, proceed):
            span = global_tracer.start_span("aop.circuit_breaker", attributes={"function": func_key, "state": self._state[func_key]["state"]})
            state = self._state[func_key]
            
            try:
                # 检查是否应该从OPEN状态切换到HALF_OPEN
                if state["state"] == "OPEN":
                    if time.time() - state["last_failure_time"] > recovery_timeout:
                        state["state"] = "HALF_OPEN"
                        if self.event_bus:
                            await self.event_bus.emit(Event(
                                name="circuit_breaker.half_open",
                                payload={"function": func_key}
                            ))
                    else:
                        # 快速失败
                        if self.event_bus:
                            await self.event_bus.emit(Event(
                                name="circuit_breaker.open",
                                payload={"function": func_key}
                            ))
                        if fallback_method and hasattr(joinpoint.target, fallback_method):
                            try:
                                fallback = getattr(joinpoint.target, fallback_method)
                                return fallback(*joinpoint.args, **joinpoint.kwargs)
                            except Exception as fallback_error:
                                raise Exception(f"Circuit breaker is open, and fallback method {fallback_method} also failed: {str(fallback_error)}")
                        raise Exception(f"Circuit breaker is open for {func_key}")
                
                try:
                    sub_span = global_tracer.start_span("aop.circuit_breaker.execute")
                    result = await proceed()
                    global_tracer.end_span(sub_span)
                    
                    # 处理成功
                    if state["state"] == "HALF_OPEN":
                        state["consecutive_successes"] += 1
                        if state["consecutive_successes"] >= 3:  # 连续成功3次后关闭
                            state["state"] = "CLOSED"
                            state["failure_count"] = 0
                            state["consecutive_successes"] = 0
                            if self.event_bus:
                                await self.event_bus.emit(Event(
                                    name="circuit_breaker.closed",
                                    payload={"function": func_key}
                                ))
                    else:
                        state["failure_count"] = 0
                    
                    return result
                except Exception as e:
                    # 处理失败
                    state["failure_count"] += 1
                    state["last_failure_time"] = time.time()
                    state["consecutive_successes"] = 0
                    
                    if state["state"] == "CLOSED" and state["failure_count"] >= failure_threshold:
                        state["state"] = "OPEN"
                        if self.event_bus:
                            await self.event_bus.emit(Event(
                                name="circuit_breaker.opened",
                                payload={"function": func_key, "failure_count": state["failure_count"]}
                            ))
                    
                    raise
            finally:
                global_tracer.end_span(span)
        
        return AroundAdvice(advice)