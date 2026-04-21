"""OpenTelemetry 日志增强功能"""

import structlog
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
        import time
        logger = structlog.get_logger(func.__module__)
        
        def wrapper(*args, **kwargs):
            start_time = time.time()
            
            # 记录输入参数
            if self.log_args:
                logger.info(f"{func.__name__} called", args=args, kwargs=kwargs)
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = (time.time() - start_time) * 1000  # 转换为毫秒
                
                # 记录执行时间
                if self.log_duration:
                    logger.info(f"{func.__name__} completed", duration_ms=duration)
                
                # 记录返回结果
                if self.log_result:
                    # 避免记录过大的结果
                    if isinstance(result, (str, int, float, bool, type(None))):
                        logger.info(f"{func.__name__} result", result=result)
                    else:
                        logger.info(f"{func.__name__} result type", result_type=type(result).__name__)
        
        return wrapper
