#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Rate Limit 中间件
使用Redis实现基于token的速率限制
"""

import time
import os
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status, Depends
from util.cognito.redis_cache import TokenCache, get_token_cache
from util.cognito.auth_middleware import verify_cognito_token
from util.cognito.config import CognitoConfig


class RateLimiter:
    """速率限制器"""
    
    def __init__(
        self,
        redis_cache: Optional[TokenCache] = None,
        requests_per_minute: int = 60,
        key_prefix: str = "rate_limit:"
    ):
        """
        初始化速率限制器
        
        Args:
            redis_cache: TokenCache实例（用于Redis连接）
            requests_per_minute: 每分钟允许的请求数
            key_prefix: Redis key前缀
        """
        self.redis_cache = redis_cache or get_token_cache()
        self.requests_per_minute = requests_per_minute
        self.key_prefix = key_prefix
        self.enabled = self.redis_cache is not None
    
    def _get_rate_limit_key(self, identifier: str) -> str:
        """
        生成速率限制key
        
        Args:
            identifier: 标识符（如token或client_id）
        
        Returns:
            Redis key
        """
        # 使用分钟作为时间窗口
        current_minute = int(time.time() // 60)
        return f"{self.key_prefix}{identifier}:{current_minute}"
    
    def _get_identifier_from_token(self, token: str) -> str:
        """
        从token中提取标识符（用于限流）
        
        Args:
            token: JWT token字符串
        
        Returns:
            标识符（使用token的hash）
        """
        import hashlib
        # 使用token的hash作为标识符
        return hashlib.sha256(token.encode('utf-8')).hexdigest()[:16]
    
    def _get_identifier_from_claims(self, claims: Dict[str, Any]) -> str:
        """
        从claims中提取标识符（用于限流）
        
        Args:
            claims: JWT token claims
        
        Returns:
            标识符（优先使用client_id，否则使用sub）
        """
        return claims.get("client_id") or claims.get("sub") or "unknown"
    
    def check_rate_limit(
        self,
        identifier: Optional[str] = None,
        token: Optional[str] = None,
        claims: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        检查速率限制
        
        Args:
            identifier: 直接指定标识符
            token: JWT token（如果提供，会从中提取标识符）
            claims: JWT claims（如果提供，会从中提取标识符）
        
        Returns:
            包含限流信息的字典
        
        Raises:
            HTTPException: 如果超过速率限制
        """
        # 如果未启用Redis，直接允许
        if not self.enabled:
            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute,
                "reset_time": int(time.time()) + 60
            }
        
        # 确定标识符
        if identifier:
            rate_limit_id = identifier
        elif claims:
            rate_limit_id = self._get_identifier_from_claims(claims)
        elif token:
            rate_limit_id = self._get_identifier_from_token(token)
        else:
            # 如果没有标识符，使用默认值（不推荐）
            rate_limit_id = "default"
        
        # 获取当前时间窗口的key
        key = self._get_rate_limit_key(rate_limit_id)
        
        try:
            # 获取当前计数
            current_count = self.redis_cache.redis_client.get(key)
            current_count = int(current_count) if current_count else 0
            
            # 检查是否超过限制
            if current_count >= self.requests_per_minute:
                # 计算重置时间（下一分钟）
                reset_time = (int(time.time() // 60) + 1) * 60
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
            
            # 增加计数
            new_count = current_count + 1
            # 设置过期时间为2分钟（确保跨分钟边界）
            self.redis_cache.redis_client.setex(key, 120, new_count)
            
            # 计算重置时间
            reset_time = (int(time.time() // 60) + 1) * 60
            
            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute - new_count,
                "current": new_count,
                "reset_time": reset_time
            }
            
        except HTTPException:
            raise
        except Exception as e:
            # 如果Redis出错，记录但不阻止请求
            print(f"⚠️  速率限制检查出错: {str(e)}")
            return {
                "allowed": True,
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute,
                "error": str(e)
            }
    
    def get_rate_limit_info(self, identifier: str) -> Dict[str, Any]:
        """
        获取速率限制信息（不增加计数）
        
        Args:
            identifier: 标识符
        
        Returns:
            速率限制信息
        """
        if not self.enabled:
            return {
                "limit": self.requests_per_minute,
                "remaining": self.requests_per_minute
            }
        
        key = self._get_rate_limit_key(identifier)
        
        try:
            current_count = self.redis_cache.redis_client.get(key)
            current_count = int(current_count) if current_count else 0
            
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


# 全局速率限制器实例（使用默认配置）
_default_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(requests_per_minute: Optional[int] = None, key_prefix: Optional[str] = None) -> RateLimiter:
    """
    获取速率限制器实例
    
    如果使用默认配置（参数为None），返回单例实例
    如果指定了自定义参数，返回新的实例
    
    Args:
        requests_per_minute: 每分钟允许的请求数（如果为None，从配置读取）
        key_prefix: Redis key前缀（如果为None，从配置读取）
    
    Returns:
        RateLimiter实例
    """
    global _default_rate_limiter
    
    # 如果使用默认配置，返回单例
    if requests_per_minute is None and key_prefix is None:
        if _default_rate_limiter is None:
            _default_rate_limiter = RateLimiter(
                requests_per_minute=CognitoConfig.RATE_LIMIT_REQUESTS_PER_MINUTE,
                key_prefix=CognitoConfig.RATE_LIMIT_KEY_PREFIX
            )
        return _default_rate_limiter
    
    # 如果指定了自定义参数，创建新实例
    rpm = requests_per_minute if requests_per_minute is not None else CognitoConfig.RATE_LIMIT_REQUESTS_PER_MINUTE
    prefix = key_prefix if key_prefix is not None else CognitoConfig.RATE_LIMIT_KEY_PREFIX
    return RateLimiter(requests_per_minute=rpm, key_prefix=prefix)


# FastAPI依赖：速率限制检查
async def check_rate_limit(
    request: Request,
    claims: Optional[Dict[str, Any]] = None,
    requests_per_minute: Optional[int] = None
) -> Dict[str, Any]:
    """
    FastAPI依赖：检查速率限制
    
    使用方法：
        @app.get("/api/limited")
        async def limited_endpoint(
            claims: dict = Depends(verify_cognito_token),
            rate_limit: dict = Depends(check_rate_limit)
        ):
            return {"message": "请求成功"}
        
        或者自定义速率限制：
        @app.get("/api/limited")
        async def limited_endpoint(
            claims: dict = Depends(verify_cognito_token),
            rate_limit: dict = Depends(lambda: check_rate_limit(requests_per_minute=100))
        ):
            return {"message": "请求成功"}
    
    Args:
        request: FastAPI请求对象
        claims: JWT token claims（如果已验证）
        requests_per_minute: 每分钟允许的请求数（如果为None，从配置读取）
    
    Returns:
        速率限制信息
    
    Raises:
        HTTPException: 如果超过速率限制
    """
    limiter = get_rate_limiter(requests_per_minute=requests_per_minute)
    
    # 从请求中提取token（如果claims未提供）
    token = None
    if not claims:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    
    return limiter.check_rate_limit(claims=claims, token=token)

