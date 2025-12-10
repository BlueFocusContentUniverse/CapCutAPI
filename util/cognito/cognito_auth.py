#!/usr/bin/env python3
"""
Cognito JWT Token验证器
用于验证Cognito JWT token
"""

import logging
import time
from typing import Annotated, Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from util.cognito.config import CognitoConfig
from util.cognito.jwt_verifier import CognitoJWTVerifier
from util.cognito.redis_cache import get_token_cache

logger = logging.getLogger(__name__)

# HTTP Bearer token方案（用于FastAPI依赖注入和OpenAPI文档）
http_bearer_scheme = HTTPBearer(
    description="使用 AWS Cognito JWT token 进行认证。请在 Authorization header 中提供 Bearer token。"
)


class CognitoTokenVerifier:
    """Cognito JWT Token验证器"""

    def __init__(
        self,
        config: Optional[CognitoConfig] = None,
        token_cache: Optional[Any] = None,
        enable_cache: bool = True,
    ):
        """
        初始化Token验证器

        Args:
            config: CognitoConfig实例
            token_cache: TokenCache实例(可选,需要Redis)
            enable_cache: 是否启用Redis缓存
        """
        self.verifier = CognitoJWTVerifier(config)
        self.token_cache = token_cache
        # 只有在提供了token_cache时才启用缓存
        self.enable_cache = enable_cache and token_cache is not None

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
                detail={"error": "invalid_token", "message": f"Token验证失败: {e!s}"},
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


# 全局Token验证器实例(延迟初始化)
_token_verifier: Optional[CognitoTokenVerifier] = None


def get_token_verifier() -> CognitoTokenVerifier:
    """
    获取Token验证器实例(单例模式)

    Returns:
        CognitoTokenVerifier实例
    """
    global _token_verifier

    if _token_verifier is None:
        token_cache = None
        if CognitoConfig.ENABLE_REDIS_CACHE:
            try:
                token_cache = get_token_cache()
            except Exception as e:
                logger.warning(f"Redis缓存不可用: {e},认证功能仍然可用,只是不使用缓存")

        _token_verifier = CognitoTokenVerifier(
            config=CognitoConfig,
            token_cache=token_cache,
            enable_cache=token_cache is not None,
        )

    return _token_verifier


# FastAPI 依赖函数 - 用于依赖注入和OpenAPI文档
async def get_current_user_claims(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer_scheme)],
) -> Dict[str, Any]:
    """
    验证 JWT token 并返回 claims

    Args:
        credentials: HTTPAuthorizationCredentials 对象，包含从 Authorization header 中提取的 Bearer token

    Returns:
        token 的 claims 字典

    Raises:
        HTTPException: 如果 token 验证失败
    """
    token = credentials.credentials.strip()  # 去除可能的空格和换行符
    # 获取Token验证器
    try:
        verifier = get_token_verifier()
    except Exception as e:
        logger.error(f"Token验证器初始化失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "auth_service_unavailable",
                "message": "认证服务暂时不可用，请稍后重试",
            },
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    # 验证 token
    try:
        claims = verifier._verify_token_with_cache(token)
        return claims
    except HTTPException:
        # 直接重新抛出 HTTPException
        raise
    except Exception as e:
        logger.error(f"Token验证异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": f"Token验证失败: {e!s}"},
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
