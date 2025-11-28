#!/usr/bin/env python3
"""
API Rate Limit 中间件
通用的速率限制工具,使用Redis实现基于标识符的速率限制
"""

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


def _get_redis_client():
    """获取Redis客户端实例(从环境变量读取配置)"""
    if not REDIS_AVAILABLE:
        return None

    redis_url = os.getenv("RATE_LIMIT_REDIS_URL")
    if not redis_url:
        return None

    try:
        parsed = urlparse(redis_url)
        client = redis.Redis(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/")) if parsed.path else 0,
            password=parsed.password,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"无法从RATE_LIMIT_REDIS_URL初始化Redis连接: {e}")
        return None


class RateLimiter:
    """速率限制器"""
    
    def __init__(
        self,
        redis_client: Optional[Any] = None,
        requests_per_minute: int = 60,
        key_prefix: str = "rate_limit:"
    ):
        """
        初始化速率限制器

        Args:
            redis_client: Redis客户端实例(如果为None,会从环境变量自动获取)
            requests_per_minute: 每分钟允许的请求数
            key_prefix: Redis key前缀
        """
        self.redis_client = redis_client or _get_redis_client()
        self.requests_per_minute = requests_per_minute
        self.key_prefix = key_prefix
        self.enabled = self.redis_client is not None
    
    def _get_rate_limit_key(self, identifier: str) -> str:
        """生成速率限制key"""
        current_minute = int(time.time() // 60)
        return f"{self.key_prefix}{identifier}:{current_minute}"

    def _normalize_identifier(self, identifier: str) -> str:
        """标准化标识符(如果太长则hash)"""
        if len(identifier) > 64:
            return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]
        return identifier

    def _get_reset_time(self) -> int:
        """计算重置时间(下一分钟)"""
        return (int(time.time() // 60) + 1) * 60
    
    def check_rate_limit(self, identifier: str) -> Dict[str, Any]:
        """检查速率限制，如果超过限制会抛出HTTPException"""
        if not self.enabled:
            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute,
                "reset_time": int(time.time()) + 60
            }

        normalized_id = self._normalize_identifier(identifier)
        key = self._get_rate_limit_key(normalized_id)

        try:
            current_count = int(self.redis_client.get(key) or 0)

            if current_count >= self.requests_per_minute:
                reset_time = self._get_reset_time()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "rate_limit_exceeded",
                        "message": f"请求过于频繁，每分钟最多{self.requests_per_minute}次请求",
                        "limit": self.requests_per_minute,
                        "current": current_count,
                        "reset_time": reset_time,
                        "retry_after": reset_time - int(time.time())
                    },
                    headers={
                        "X-RateLimit-Limit": str(self.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_time),
                        "Retry-After": str(reset_time - int(time.time()))
                    }
                )

            new_count = current_count + 1
            self.redis_client.setex(key, 120, new_count)  # 2分钟过期,确保跨分钟边界

            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute - new_count,
                "current": new_count,
                "reset_time": self._get_reset_time()
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"速率限制检查出错: {e}", exc_info=True)
            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute,
                "error": str(e)
            }
    
    def get_rate_limit_info(self, identifier: str) -> Dict[str, Any]:
        """获取速率限制信息(不增加计数)"""
        if not self.enabled:
            return {
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute
            }

        normalized_id = self._normalize_identifier(identifier)
        key = self._get_rate_limit_key(normalized_id)

        try:
            current_count = int(self.redis_client.get(key) or 0)
            return {
                "limit": self.requests_per_minute,
                "remaining": max(0, self.requests_per_minute - current_count),
                "current": current_count
            }
        except Exception:
            return {
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute
            }


# 全局速率限制器实例(使用默认配置)
_default_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(requests_per_minute: Optional[int] = None, key_prefix: Optional[str] = None) -> RateLimiter:
    """获取速率限制器实例(使用默认配置时返回单例)"""
    global _default_rate_limiter

    default_rpm = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "600"))
    default_prefix = os.getenv("RATE_LIMIT_KEY_PREFIX", "rate_limit:")

    if requests_per_minute is None and key_prefix is None:
        if _default_rate_limiter is None:
            _default_rate_limiter = RateLimiter(
                requests_per_minute=default_rpm,
                key_prefix=default_prefix
            )
        return _default_rate_limiter

    return RateLimiter(
        requests_per_minute=requests_per_minute or default_rpm,
        key_prefix=key_prefix or default_prefix
    )


def get_identifier_from_request(request: Request, claims: Optional[Dict[str, Any]] = None) -> str:
    """从请求中提取标识符(优先级:claims > token hash > IP)"""
    if claims:
        identifier = claims.get("client_id") or claims.get("sub") or claims.get("user_id")
        if identifier:
            return str(identifier)

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]

    client_ip = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(',')[0].strip()

    return client_ip

