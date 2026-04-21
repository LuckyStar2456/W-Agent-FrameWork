"""OpenTelemetry 追踪功能"""

from typing import Optional, Dict, Any
import os

# 尝试导入OpenTelemetry
_otel_available = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    _otel_available = True
except ImportError:
    pass

class Tracer:
    """追踪器包装类"""
    def __init__(self, name: str):
        self.name = name
        self.tracer = None
        if _otel_available:
            self.tracer = trace.get_tracer(name)
    
    def start_span(self, name: str, attributes: Dict[str, Any] = None) -> Optional[Any]:
        """开始一个span"""
        if not _otel_available or not self.tracer:
            return None
        return self.tracer.start_span(name, attributes=attributes)
    
    def end_span(self, span: Any):
        """结束一个span"""
        if _otel_available and span:
            span.end()

def init_tracing(service_name: str = "w-agent"):
    """初始化追踪功能"""
    if not _otel_available:
        return
    
    # 创建TracerProvider
    provider = TracerProvider()
    
    # 添加SpanProcessor
    # 控制台导出器（用于开发）
    console_exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(console_exporter))
    
    # OTLP导出器（用于生产）
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    
    # 设置全局TracerProvider
    trace.set_tracer_provider(provider)

# 全局追踪器
global_tracer = Tracer("w-agent")
