#!/usr/bin/env python3
"""
FastAPI认证中间件
用于验证Cognito JWT token
"""

import logging
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from util.cognito.config import CognitoConfig
from util.cognito.jwt_verifier import CognitoJWTVerifier
from util.cognito.redis_cache import get_token_cache

logger = logging.getLogger(__name__)

# OAuth2 Bearer token方案
# auto_error=False: 如果没有token,返回None而不是抛出异常(适合中间件使用)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


class CognitoAuthMiddleware:
    """Cognito认证中间件"""

    def __init__(
        self,
        config: Optional[CognitoConfig] = None,
        token_cache: Optional[Any] = None,
        enable_cache: bool = True
    ):
        """
        初始化认证中间件

        Args:
            config: CognitoConfig实例
            token_cache: TokenCache实例(可选,需要Redis)
            enable_cache: 是否启用Redis缓存
        """
        self.verifier = CognitoJWTVerifier(config)
        self.token_cache = token_cache
        # 只有在提供了token_cache时才启用缓存
        self.enable_cache = enable_cache and token_cache is not None

    async def _extract_token(self, request: Request) -> Optional[str]:
        """从请求中提取token(使用FastAPI标准OAuth2PasswordBearer)"""
        # 优先使用OAuth2PasswordBearer提取token(符合FastAPI标准)
        token = await oauth2_scheme(request)
        if token:
            logger.debug(f"[AUTH] 从OAuth2PasswordBearer提取到token: {token[:20]}...")
            return token

        # 备用方案:从X-Auth-Token header获取
        token = request.headers.get("X-Auth-Token")
        if token:
            logger.debug(f"[AUTH] 从X-Auth-Token header提取到token: {token[:20]}...")
            return token.strip()

        logger.debug("[AUTH] 未找到token")
        return None

    def _verify_token_with_cache(self, token: str) -> Dict[str, Any]:
        """验证token(带缓存)"""
        # 先检查缓存
        if self.enable_cache:
            cached_claims = self.token_cache.get(token)
            if cached_claims:
                return cached_claims

        # 验证token
        try:
            claims = self.verifier.verify_token(token)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "invalid_token",
                    "message": f"Token验证失败: {e!s}"
                },
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        # 存入缓存
        if self.enable_cache:
            exp = claims.get("exp")
            if exp:
                ttl = max(0, int(exp - time.time()))
                if ttl > 0:
                    try:
                        success = self.token_cache.set(token, claims, ttl=ttl)
                        if success:
                            logger.debug(f"Token已缓存,TTL: {ttl}秒")
                        else:
                            logger.warning(f"Token缓存失败,TTL: {ttl}秒")
                    except Exception as e:
                        logger.warning(f"Token缓存异常: {e}")

        return claims

    async def verify_token(self, request: Request) -> Dict[str, Any]:
        """
        验证请求中的token

        Args:
            request: FastAPI Request对象

        Returns:
            token的claims字典

        Raises:
            HTTPException: 如果token缺失或验证失败
        """
        token = await self._extract_token(request)

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "missing_token",
                    "message": "需要提供认证token。请在Authorization header中使用Bearer token"
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        return self._verify_token_with_cache(token)


# 全局认证中间件实例(延迟初始化)
_auth_middleware: Optional[CognitoAuthMiddleware] = None


def get_auth_middleware() -> CognitoAuthMiddleware:
    """
    获取认证中间件实例(单例模式)

    Returns:
        CognitoAuthMiddleware实例
    """
    global _auth_middleware

    if _auth_middleware is None:
        token_cache = None
        if CognitoConfig.ENABLE_REDIS_CACHE:
            try:
                token_cache = get_token_cache()
            except Exception as e:
                logger.warning(f"Redis缓存不可用: {e},认证功能仍然可用,只是不使用缓存")

        _auth_middleware = CognitoAuthMiddleware(
            config=CognitoConfig,
            token_cache=token_cache,
            enable_cache=token_cache is not None
        )

    return _auth_middleware

