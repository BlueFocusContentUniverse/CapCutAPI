"""
Logging Middleware for FastAPI.

This module provides a centralized logging middleware that automatically
logs all incoming requests and outgoing responses.
"""

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)


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
        """
        Initialize the logging middleware.

        Args:
            app: FastAPI application instance
            exclude_paths: List of path prefixes to exclude from logging
            log_level: Logging level (default: INFO)
        """
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
        """
        Process the request and log details.

        Args:
            request: Incoming request
            call_next: Next middleware/endpoint handler

        Returns:
            Response from the endpoint
        """
        # Generate request ID for tracing
        request_id = str(uuid.uuid4())[:8]

        # Get request details
        method = request.method
        path = request.url.path
        query = str(request.url.query) if request.url.query else ""
        client_host = request.client.host if request.client else "unknown"

        # Check if we should log this request
        should_log = self._should_log(path)

        if should_log:
            # Log request start
            query_str = f"?{query}" if query else ""
            logger.log(
                self.log_level,
                f"[{request_id}] --> {method} {path}{query_str} | Client: {client_host}",
            )

        # Record start time
        start_time = time.time()

        # Process request
        try:
            response = await call_next(request)
            duration = time.time() - start_time

            if should_log:
                # Log response
                status_code = response.status_code
                log_level = self.log_level if status_code < 400 else logging.WARNING
                if status_code >= 500:
                    log_level = logging.ERROR

                logger.log(
                    log_level,
                    f"[{request_id}] <-- {method} {path} | Status: {status_code} | Duration: {duration:.3f}s",
                )

            # Add request ID to response headers for tracing
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"[{request_id}] <-- {method} {path} | Error: {e!s} | Duration: {duration:.3f}s"
            )
            raise
