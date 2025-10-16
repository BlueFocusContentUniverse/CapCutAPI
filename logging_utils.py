"""
Centralized logging utilities for CapCut API.

This module provides decorators and utilities for consistent logging across
APIs, services, and MCP tools.
"""

import functools
import logging
import time
import traceback
from typing import Any, Callable, Dict, Optional

from flask import Request, request

# Configure logging format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """
    Setup application-wide logging configuration.
    
    Args:
        level: Logging level (default: logging.INFO)
    """
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT
    )


def log_api_request(logger: logging.Logger, request_obj: Request) -> None:
    """
    Log incoming API request details.
    
    Args:
        logger: Logger instance
        request_obj: Flask request object
    """
    logger.info(
        f"API Request - Method: {request_obj.method}, "
        f"Path: {request_obj.path}, "
        f"Remote: {request_obj.remote_addr}"
    )

    # Log request data (excluding sensitive information)
    if request_obj.is_json:
        data = request_obj.get_json()
        # Sanitize data - remove potentially sensitive fields
        sanitized_data = {k: v for k, v in data.items() if k not in ["password", "token", "secret"]}
        logger.debug(f"Request Data: {sanitized_data}")


def log_api_response(logger: logging.Logger, response: Dict[str, Any], duration: float) -> None:
    """
    Log API response details.
    
    Args:
        logger: Logger instance
        response: Response dictionary
        duration: Request duration in seconds
    """
    success = response.get("success", False)
    level = logging.INFO if success else logging.ERROR

    logger.log(
        level,
        f"API Response - Success: {success}, Duration: {duration:.3f}s"
    )

    if not success and "error" in response:
        logger.error(f"Error Details: {response['error']}")


def api_endpoint_logger(func: Callable) -> Callable:
    """
    Decorator for Flask API endpoints to add comprehensive logging.
    
    Logs:
    - Request details (method, path, remote IP)
    - Request data (sanitized)
    - Response status
    - Execution time
    - Errors with stack traces
    
    Usage:
        @bp.route("/endpoint", methods=["POST"])
        @api_endpoint_logger
        def my_endpoint():
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        endpoint_name = func.__name__

        start_time = time.time()

        try:
            # Log request
            logger.info(f"=== Starting API Endpoint: {endpoint_name} ===")
            log_api_request(logger, request)

            # Execute endpoint
            response = func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time

            # Log response
            if hasattr(response, "get_json"):
                response_data = response.get_json()
                log_api_response(logger, response_data, duration)

            logger.info(f"=== Completed API Endpoint: {endpoint_name} in {duration:.3f}s ===")

            return response

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"=== API Endpoint Error: {endpoint_name} ===\n"
                f"Error: {e!s}\n"
                f"Duration: {duration:.3f}s\n"
                f"Traceback:\n{traceback.format_exc()}"
            )
            raise

    return wrapper


def service_logger(func: Callable) -> Callable:
    """
    Decorator for service functions to add comprehensive logging.
    
    Logs:
    - Function entry with parameters
    - Function exit with return value
    - Execution time
    - Errors with stack traces
    
    Usage:
        @service_logger
        def add_video_track(video_url: str, draft_id: str, ...):
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        service_name = func.__name__

        start_time = time.time()

        try:
            # Log service entry
            logger.info(f">>> Service Start: {service_name}")

            # Log key parameters (sanitize sensitive data)
            if kwargs:
                sanitized_kwargs = {
                    k: v for k, v in kwargs.items()
                    if k not in ["password", "token", "secret"] and not k.startswith("_")
                }
                # Only log non-URL parameters to avoid noise
                log_params = {
                    k: v for k, v in sanitized_kwargs.items()
                    if not (isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")))
                }
                if log_params:
                    logger.debug(f"Parameters: {log_params}")

            # Execute service
            result = func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time

            # Log service completion
            logger.info(f"<<< Service Complete: {service_name} in {duration:.3f}s")

            # Log result structure (not full content to avoid noise)
            if isinstance(result, dict):
                logger.debug(f"Result keys: {list(result.keys())}")

            return result

        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"<<< Service Error: {service_name} ===\n"
                f"Error: {e!s}\n"
                f"Duration: {duration:.3f}s\n"
                f"Traceback:\n{traceback.format_exc()}"
            )
            raise

    return wrapper


def mcp_tool_logger(tool_name: str, logger: Optional[logging.Logger] = None) -> Callable:
    """
    Decorator for MCP tool functions to add comprehensive logging.
    
    Logs:
    - Tool execution start with arguments
    - Tool execution completion with result
    - Execution time
    - Errors with stack traces
    
    Args:
        tool_name: Name of the MCP tool
        logger: Optional logger instance (will create one if not provided)
    
    Usage:
        @mcp_tool_logger("create_draft")
        def tool_create_draft(width: int, height: int, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)

            start_time = time.time()

            try:
                # Log tool execution start
                logger.info(f"[MCP] Tool Start: {tool_name}")

                # Log key arguments
                if kwargs:
                    sanitized_kwargs = {
                        k: v for k, v in kwargs.items()
                        if k not in ["password", "token", "secret"] and not k.startswith("_")
                    }
                    # Only log non-URL parameters to avoid noise
                    log_params = {
                        k: v for k, v in sanitized_kwargs.items()
                        if not (isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")))
                    }
                    if log_params:
                        logger.debug(f"[MCP] Tool Arguments: {log_params}")

                # Execute tool
                result = func(*args, **kwargs)

                # Calculate duration
                duration = time.time() - start_time

                # Log tool completion
                logger.info(f"[MCP] Tool Complete: {tool_name} in {duration:.3f}s")

                # Log result structure
                if isinstance(result, dict):
                    logger.debug(f"[MCP] Result keys: {list(result.keys())}")

                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.error(
                    f"[MCP] Tool Error: {tool_name}\n"
                    f"Error: {e!s}\n"
                    f"Duration: {duration:.3f}s\n"
                    f"Traceback:\n{traceback.format_exc()}"
                )
                raise

        return wrapper

    return decorator


def log_execution(logger: logging.Logger, operation: str, **context: Any) -> None:
    """
    Log a generic operation with context.
    
    Args:
        logger: Logger instance
        operation: Operation description
        **context: Additional context to log
    """
    context_str = ", ".join([f"{k}={v}" for k, v in context.items()])
    logger.info(f"{operation} - {context_str}")

