"""
Logging Middleware for FastAPI.

This module provides a centralized logging middleware that automatically
logs all incoming requests and outgoing responses.
"""

import logging
import time
import uuid
from typing import List, Optional

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

def _get_trace_id() -> str:
    """获取当前 OpenTelemetry Trace ID"""
    try:
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, "032x")
    except Exception:
        pass
    return ""

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for comprehensive request/response logging.

    Features:
    - Logs all incoming requests with method, path, and client info
    - Logs response status and duration
    - Adds request ID for tracing
    - Configurable excluded paths (e.g., health checks)
    """
    def __init__(
        self,
        app,
        exclude_paths: list[str] | None = None,
        log_level: int = logging.INFO,
    ):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        self.log_level = log_level

    def _should_log(self, path: str) -> bool:
        """Check if the request path should be logged."""
        return not any(path.startswith(excluded) for excluded in self.exclude_paths)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if not self._should_log(path):
            return await call_next(request)

        # 1. 准备请求元数据
        request_id = str(uuid.uuid4())[:8]
        method = request.method
        client_host = request.client.host if request.client else "unknown"
        start_time = time.perf_counter() # 使用更精确的性能计数器

        # 2. 获取 Trace ID
        trace_id = _get_trace_id()
        trace_tag = f"[trace:{trace_id}] " if trace_id else ""

        # 3. 记录请求进入
        query_str = f"?{request.url.query}" if request.url.query else ""
        logger.log(
            self.log_level,
            f"{trace_tag}[{request_id}] --> {method} {path}{query_str} | Client: {client_host}"
        )

        try:
            response = await call_next(request)
            
            # 4. 计算耗时与日志级别
            duration = time.perf_counter() - start_time
            status_code = response.status_code
            
            # 自动根据状态码调整日志级别
            current_level = self.log_level
            if status_code >= 500:
                current_level = logging.ERROR
            elif status_code >= 400:
                current_level = logging.WARNING

            # 5. 记录响应返回
            logger.log(
                current_level,
                f"{trace_tag}[{request_id}] <-- {method} {path} | Status: {status_code} | Time: {duration:.3f}s"
            )

            # 6. 响应头注入
            response.headers["X-Request-ID"] = request_id
            if trace_id:
                response.headers["X-Trace-ID"] = trace_id

            return response

        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.exception(
                f"{trace_tag}[{request_id}] <-- {method} {path} | ERROR: {str(e)} | Time: {duration:.3f}s"
            )
            raise