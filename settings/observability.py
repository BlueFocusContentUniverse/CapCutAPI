"""
可观测性配置模块 - OpenTelemetry 配置，支持导出到腾讯云 APM。
"""

import os

# 腾讯云 APM 配置
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
TENCENT_APM_TOKEN = os.getenv("OTEL_EXPORTER_OTLP_TOKEN")

# 服务配置
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "capcut-api")
SERVICE_VERSION = os.getenv("OTEL_SERVICE_VERSION", "1.9.0")

# OpenTelemetry 开关
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() == "true"

# 采样率配置
OTEL_SAMPLE_RATE = os.getenv("OTEL_SAMPLE_RATE", "always_on")
OTEL_SMART_SAMPLE_NORMAL_RATE = float(os.getenv("OTEL_SMART_SAMPLE_NORMAL_RATE", "0.01"))  # 正常请求采样率（默认 1%）
OTEL_SMART_SAMPLE_SLOW_THRESHOLD = float(os.getenv("OTEL_SMART_SAMPLE_SLOW_THRESHOLD", "1.0"))  # 慢请求阈值（秒，默认 1 秒）

# Headers 配置：优先使用 OTEL_EXPORTER_OTLP_HEADERS，如果没有则使用 x-token={TENCENT_APM_TOKEN}
_otel_headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
if not _otel_headers and TENCENT_APM_TOKEN:
    _otel_headers = f"x-token={TENCENT_APM_TOKEN}"
OTEL_EXPORTER_OTLP_HEADERS = _otel_headers

# 日志追踪集成
OTEL_LOGS_ENABLED = os.getenv("OTEL_LOGS_ENABLED", "true").lower() == "true"

# Metrics 指标导出（默认启用，用于准确统计 QPS 等指标）
OTEL_METRICS_ENABLED = os.getenv("OTEL_METRICS_ENABLED", "true").lower() == "true"
OTEL_METRICS_EXPORT_INTERVAL = int(os.getenv("OTEL_METRICS_EXPORT_INTERVAL", "60000"))  # 导出间隔（毫秒，默认 60 秒）

# 批量导出配置
OTEL_BSP_MAX_QUEUE_SIZE = int(os.getenv("OTEL_BSP_MAX_QUEUE_SIZE", "2048"))  # 最大队列大小
OTEL_BSP_SCHEDULE_DELAY = int(os.getenv("OTEL_BSP_SCHEDULE_DELAY", "5000"))  # 批量导出延迟（毫秒）
OTEL_BSP_EXPORT_TIMEOUT = int(os.getenv("OTEL_BSP_EXPORT_TIMEOUT", "30000"))  # 导出超时（毫秒）
OTEL_BSP_MAX_EXPORT_BATCH_SIZE = int(os.getenv("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "512"))  # 最大批量大小


def get_otel_config() -> dict:
    """
    获取 OpenTelemetry 配置字典

    Returns:
        dict: OpenTelemetry 配置
    """
    return {
        "enabled": OTEL_ENABLED,
        "service_name": SERVICE_NAME,
        "service_version": SERVICE_VERSION,
        "sample_rate": OTEL_SAMPLE_RATE,
        "endpoint": OTEL_EXPORTER_OTLP_ENDPOINT,
        "headers": OTEL_EXPORTER_OTLP_HEADERS,
        "logs_enabled": OTEL_LOGS_ENABLED,
        "max_queue_size": OTEL_BSP_MAX_QUEUE_SIZE,
        "schedule_delay": OTEL_BSP_SCHEDULE_DELAY,
        "export_timeout": OTEL_BSP_EXPORT_TIMEOUT,
        "max_export_batch_size": OTEL_BSP_MAX_EXPORT_BATCH_SIZE,
        "smart_sample_normal_rate": OTEL_SMART_SAMPLE_NORMAL_RATE,
        "smart_sample_slow_threshold": OTEL_SMART_SAMPLE_SLOW_THRESHOLD,
        "metrics_enabled": OTEL_METRICS_ENABLED,
        "metrics_export_interval": OTEL_METRICS_EXPORT_INTERVAL,
    }


def is_otel_enabled() -> bool:
    """检查 OpenTelemetry 是否启用"""
    return OTEL_ENABLED

