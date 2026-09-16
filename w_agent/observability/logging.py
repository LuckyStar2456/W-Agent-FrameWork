"""OpenTelemetry 日志增强功能"""

import structlog
import functools
import inspect
import time
from typing import Dict, Any, Optional

# 尝试导入OpenTelemetry
_otel_available = False
try:
    from opentelemetry import trace
    _otel_available = True
except ImportError:
    pass

def add_otel_context(logger, method_name, event_dict):
    """添加OpenTelemetry上下文到日志"""
    if _otel_available:
        span = trace.get_current_span()
        if span and span.is_recording():
            span_context = span.get_span_context()
            if span_context:
                event_dict["trace_id"] = hex(span_context.trace_id)[2:]
                event_dict["span_id"] = hex(span_context.span_id)[2:]
    return event_dict

def init_logging():
    """初始化日志"""
    # 配置structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            add_otel_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ]
    )

class LogEnable:
    """日志启用装饰器"""
    def __init__(self, log_args: bool = True, log_result: bool = True, log_duration: bool = True):
        self.log_args = log_args
        self.log_result = log_result
        self.log_duration = log_duration
    
    def __call__(self, func):
        logger = structlog.get_logger(func.__module__)

        def log_call(args, kwargs):
            if self.log_args:
                logger.info(f"{func.__name__} called", args=args, kwargs=kwargs)

        def log_completion(start_time, result):
            duration = (time.perf_counter() - start_time) * 1000
            if self.log_duration:
                logger.info(f"{func.__name__} completed", duration_ms=duration)
            if self.log_result:
                if isinstance(result, (str, int, float, bool, type(None))):
                    logger.info(f"{func.__name__} result", result=result)
                else:
                    logger.info(
                        f"{func.__name__} result type",
                        result_type=type(result).__name__,
                    )

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                log_call(args, kwargs)
                result = await func(*args, **kwargs)
                log_completion(start_time, result)
                return result

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            log_call(args, kwargs)
            result = func(*args, **kwargs)
            log_completion(start_time, result)
            return result

        return wrapper
