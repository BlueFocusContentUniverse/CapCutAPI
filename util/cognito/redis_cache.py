#!/usr/bin/env python3
"""
Redis缓存管理
用于缓存已验证的JWT token
"""

import json
import time
from typing import Any, Dict, Optional

import redis


class TokenCache:
    """Token缓存管理器"""

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        key_prefix: str = "cognito:token:",
    ):
        """
        初始化Redis缓存

        Args:
            redis_host: Redis主机地址
            redis_port: Redis端口
            redis_db: Redis数据库编号
            redis_password: Redis密码
            key_prefix: 缓存key前缀
        """
        self.key_prefix = key_prefix

        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,  # 自动解码为字符串
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # 测试连接
            self.redis_client.ping()
        except Exception as e:
            raise ConnectionError(f"无法连接到Redis: {e!s}")

    def _get_cache_key(self, token: str) -> str:
        """
        生成缓存key

        Args:
            token: JWT token字符串

        Returns:
            缓存key
        """
        # 使用token的hash作为key的一部分（避免key过长）
        import hashlib

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{self.key_prefix}{token_hash}"

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        """
        从缓存获取token信息

        Args:
            token: JWT token字符串

        Returns:
            token信息字典，如果不存在或已过期则返回None
        """
        try:
            cache_key = self._get_cache_key(token)
            cached_data = self.redis_client.get(cache_key)

            if cached_data is None:
                return None

            # 解析JSON数据
            data = json.loads(cached_data)

            # 检查是否过期（双重检查）
            if "exp" in data and time.time() >= data["exp"]:
                # 已过期，删除缓存
                self.delete(token)
                return None

            return data

        except Exception as e:
            # 如果Redis出错，返回None（让验证逻辑继续）
            print(f"⚠️  Redis缓存读取错误: {e!s}")
            return None

    def set(
        self, token: str, claims: Dict[str, Any], ttl: Optional[int] = None
    ) -> bool:
        """
        将token信息存入缓存

        Args:
            token: JWT token字符串
            claims: token的claims（包含验证结果）
            ttl: 过期时间（秒），如果为None则使用token的exp

        Returns:
            是否成功
        """
        try:
            cache_key = self._get_cache_key(token)

            # 计算TTL
            if ttl is None:
                # 使用token的exp计算TTL
                exp = claims.get("exp")
                if exp:
                    ttl = max(0, int(exp - time.time()))
                else:
                    # 如果没有exp，使用默认值（1小时）
                    ttl = 3600

            # 确保TTL为正数
            if ttl <= 0:
                return False

            # 存储数据（包含claims和缓存时间）
            data = {**claims, "cached_at": time.time()}

            # 存入Redis
            self.redis_client.setex(cache_key, ttl, json.dumps(data))

            return True

        except Exception as e:
            # 如果Redis出错，记录但不影响验证流程
            print(f"⚠️  Redis缓存写入错误: {e!s}")
            return False

    def delete(self, token: str) -> bool:
        """
        从缓存删除token

        Args:
            token: JWT token字符串

        Returns:
            是否成功
        """
        try:
            cache_key = self._get_cache_key(token)
            self.redis_client.delete(cache_key)
            return True
        except Exception as e:
            print(f"⚠️  Redis缓存删除错误: {e!s}")
            return False

    def clear_all(self) -> int:
        """
        清空所有token缓存

        Returns:
            删除的key数量
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            print(f"⚠️  Redis缓存清空错误: {e!s}")
            return 0

    def ping(self) -> bool:
        """
        测试Redis连接

        Returns:
            连接是否正常
        """
        try:
            return self.redis_client.ping()
        except Exception:
            return False


# 实际使用函数
def get_token_cache(redis_url: Optional[str] = None) -> Optional[TokenCache]:
    """
    获取Token缓存实例（从环境变量读取配置）

    只支持从 TOKEN_REDIS_URL 环境变量读取配置，与 CELERY_BROKER_URL 完全独立。

    配置格式：redis://[:password@]host[:port][/db]
    示例：
    - TOKEN_REDIS_URL=redis://localhost:6379/1
    - TOKEN_REDIS_URL=redis://:password@localhost:6379/1

    注意：
    - TOKEN_REDIS_URL 和 CELERY_BROKER_URL 完全独立，互不干扰
    - 建议使用独立的数据库编号（如DB 1），与Celery（DB 0）完全隔离
    - 如果未配置 TOKEN_REDIS_URL，将返回 None，不使用 Redis 缓存

    Args:
        redis_url: Redis URL（可选，优先使用，否则从环境变量 TOKEN_REDIS_URL 读取）

    Returns:
        TokenCache实例，如果未配置或连接失败则返回None
    """
    import os

    # 只使用 TOKEN_REDIS_URL（从参数或环境变量）
    redis_url = redis_url or os.getenv("TOKEN_REDIS_URL")
    if not redis_url:
        # 未配置 TOKEN_REDIS_URL，返回 None（不使用 Redis 缓存）
        return None

    try:
        from urllib.parse import urlparse

        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        db = int(parsed.path.lstrip("/")) if parsed.path else 0
        password = parsed.password
        return TokenCache(
            redis_host=host, redis_port=port, redis_db=db, redis_password=password
        )
    except Exception as e:
        print(f"⚠️  无法从TOKEN_REDIS_URL初始化Redis缓存: {e!s}")
        return None
