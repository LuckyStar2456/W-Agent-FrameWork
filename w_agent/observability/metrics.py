"""OpenTelemetry 指标功能"""

from typing import Optional, Dict, Any
import os

# 尝试导入OpenTelemetry
_otel_available = False
try:
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
    _otel_available = True
except ImportError:
    pass

class Metrics:
    """指标管理类"""
    def __init__(self, name: str):
        self.name = name
        self.meter = None
        self._counters = {}
        self._histograms = {}
        if _otel_available:
            self.meter = metrics.get_meter(name)
    
    def counter(self, name: str, description: str = ""):
        """获取或创建计数器"""
        if not _otel_available or not self.meter:
            return None
        if name not in self._counters:
            self._counters[name] = self.meter.create_counter(
                name,
                description=description,
                unit="1"
            )
        return self._counters[name]
    
    def histogram(self, name: str, description: str = ""):
        """获取或创建直方图"""
        if not _otel_available or not self.meter:
            return None
        if name not in self._histograms:
            self._histograms[name] = self.meter.create_histogram(
                name,
                description=description,
                unit="ms"
            )
        return self._histograms[name]

def init_metrics(service_name: str = "w-agent"):
    """初始化指标功能"""
    if not _otel_available:
        return
    
    # 创建MeterProvider
    provider = MeterProvider()
    
    # 添加MetricReader
    # 控制台导出器（用于开发）
    console_exporter = ConsoleMetricExporter()
    console_reader = PeriodicExportingMetricReader(console_exporter, export_interval_millis=10000)
    provider.add_metric_reader(console_reader)
    
    # OTLP导出器（用于生产）
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    otlp_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
    otlp_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=10000)
    provider.add_metric_reader(otlp_reader)
    
    # 设置全局MeterProvider
    metrics.set_meter_provider(provider)

def track(func):
    """指标追踪装饰器"""
    import time
    
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration = (time.time() - start_time) * 1000  # 转换为毫秒
            # 记录指标
            metrics_instance = Metrics(func.__module__)
            histogram = metrics_instance.histogram(
                f"{func.__name__}_duration",
                f"Duration of {func.__name__} function"
            )
            if histogram:
                histogram.record(duration)
    
    return wrapper

# 全局指标实例
global_metrics = Metrics("w-agent")
