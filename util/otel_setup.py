"""
OpenTelemetry 初始化工具模块
"""

# import logging
# import random
# from typing import Optional

# from opentelemetry import metrics, trace
# from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
# from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# from opentelemetry.instrumentation.logging import LoggingInstrumentor
# from opentelemetry.sdk.resources import Resource
# from opentelemetry.sdk.trace import TracerProvider
# from opentelemetry.sdk.trace.export import BatchSpanProcessor
# from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, TraceIdRatioBased
# from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

# from settings.observability import get_otel_config, is_otel_enabled


import logging
import random
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

from settings.observability import get_otel_config, is_otel_enabled

# 日志配置
logging.getLogger("opentelemetry.sdk._shared_internal").setLevel(logging.WARNING)
logging.getLogger("opentelemetry.exporter.otlp.proto.grpc").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

class SmartSpanExporter(SpanExporter):
    """智能过滤器：仅在导出阶段决定哪些 Trace 进入后端"""
    def __init__(self, delegate: SpanExporter, normal_rate: float, slow_threshold: float):
        """
        Args:
            delegate: 底层导出器
            normal_rate: 正常请求的采样率（0.0-1.0）
            slow_threshold: 慢请求阈值（秒）
        """
        self.delegate = delegate
        self.normal_rate = normal_rate
        self.slow_threshold = slow_threshold
        logger.info(f"log导出器初始化: 导出错误和慢请求(>{slow_threshold}秒), 正常请求采样率={normal_rate*100}%")

    def export(self, spans):
        """
        导出 Span，过滤掉不需要的 Span
        """
        # 静默模式：normal_rate < 0 时，完全不导出任何 Trace（包括错误和慢请求）
        if self.normal_rate < 0:
            return SpanExportResult.SUCCESS
        
        filtered = []
        for span in spans:
            # 策略 1: 总是导出错误请求 (HTTP >= 400 或 SDK 标记错误)
            http_status = span.attributes.get("http.status_code") if span.attributes else None
            is_error = (http_status and int(http_status) >= 400) or not span.status.is_ok
            
            # 策略 2: 总是导出慢请求
            duration = (span.end_time - span.start_time) / 1e9 if span.end_time else 0
            is_slow = duration > self.slow_threshold
            
            # 策略 3: 正常请求概率采样
            if is_error or is_slow or (random.random() < self.normal_rate):
                filtered.append(span)
        
        return self.delegate.export(filtered) if filtered else SpanExportResult.SUCCESS

    def shutdown(self):
        """关闭导出器"""
        return self.delegate.shutdown()


def setup_opentelemetry() -> Optional[FastAPIInstrumentor]:
    """
    初始化 OpenTelemetry：通过 ALWAYS_ON 保证 Metrics 准确，通过后端过滤控制 Trace 成本
    """
    if not is_otel_enabled():
        logger.info("OpenTelemetry 未启用，放弃上传日志系统")
        return None

    try:
        config = get_otel_config()
        logger.info(f"正在初始化 OpenTelemetry: service={config['service_name']}, endpoint={config['endpoint']}")

        resource = Resource.create(
            {
                "service.name": config["service_name"],
                "service.version": config["service_version"],
            }
        )

        # 1. Trace配置
        trace_mode = str(config.get("sample_rate", "always_on")).lower()
        sampler = ALWAYS_ON

        # 2. 解析 Header（GRPC 格式）
        header_str = config.get("headers", "")
        token = next((kv.split("=")[1].strip() for kv in header_str.split(",") 
                     if "=" in kv and kv.split("=")[0].strip().lower() in ["x-token", "authorization"]), None)
        headers = (("authorization", token),) if token else ()

        # --- 3. Trace 链路初始化 ---
        otlp_trace_exporter = OTLPSpanExporter(endpoint=config["endpoint"], headers=headers, insecure=True)

        # 决定生效的采样率
        if trace_mode == "always_off":
            effective_rate = -1.0  # 触发 SmartSpanExporter 的静默模式
            logger.info("OTel 运行状态: Metrics=ON, Trace=OFF)")
        else:
            effective_rate = float(config.get("smart_sample_normal_rate", 0.01))
            logger.info(f"OTel 运行状态: Metrics=ON, Trace=ON (采样率: {effective_rate})")
                    
        # 挂载智能过滤装饰器
        smart_exporter = SmartSpanExporter(
            otlp_trace_exporter,
            normal_rate=effective_rate,
            slow_threshold=float(config.get("smart_sample_slow_threshold", 1.0))
        )

        # 配置 Trace Provider
        tp = TracerProvider(resource=resource, sampler=sampler)
        tp.add_span_processor(BatchSpanProcessor(
            smart_exporter,
            max_queue_size=config.get("max_queue_size", 2048),
            schedule_delay_millis=config.get("schedule_delay", 5000),
        ))
        trace.set_tracer_provider(tp)
        
        # --- 4. Metrics 初始化 (独立于 Trace) ---
        if config.get("metrics_enabled", True):
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=config["endpoint"], headers=headers, insecure=True),
                export_interval_millis=config.get("metrics_export_interval", 60000)
            )
            metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))

        # --- 5. 插桩配置日志 ---
        if config.get("logs_enabled"):
            LoggingInstrumentor().instrument()
            
        return FastAPIInstrumentor()

    except Exception as e:
        logger.error(f"OTel Setup Failed: {e}", exc_info=True)
        return None

def shutdown_opentelemetry():
    """关闭 OpenTelemetry，清理资源"""
    try:
        tracer_provider = trace.get_tracer_provider()
        if hasattr(tracer_provider, "shutdown"):
            tracer_provider.shutdown()
            logger.info("OpenTelemetry 已关闭")
    except Exception as e:
        logger.warning(f"关闭 OpenTelemetry 时出错: {e}")

