#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI认证中间件和依赖
用于验证Cognito JWT token
"""

import time
import logging
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from util.cognito.jwt_verifier import CognitoJWTVerifier
from util.cognito.config import CognitoConfig
from util.cognito.redis_cache import TokenCache, get_token_cache

logger = logging.getLogger(__name__)


# HTTP Bearer安全方案
security = HTTPBearer(auto_error=False)


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
            token_cache: TokenCache实例（可选，需要Redis）
            enable_cache: 是否启用Redis缓存
        """
        self.verifier = CognitoJWTVerifier(config)
        self.token_cache = token_cache
        # 只有在提供了token_cache时才启用缓存
        self.enable_cache = enable_cache and token_cache is not None
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """
        从请求中提取token
        
        Args:
            request: FastAPI请求对象
        
        Returns:
            token字符串，如果未找到则返回None
        """
        # 从Authorization header获取
        authorization = request.headers.get("Authorization")
        if authorization:
            if authorization.startswith("Bearer "):
                return authorization[7:].strip()
            return authorization.strip()
        
        # 从X-Auth-Token header获取（备用）
        token = request.headers.get("X-Auth-Token")
        if token:
            return token.strip()
        
        return None
    
    def _verify_token_with_cache(self, token: str) -> Dict[str, Any]:
        """
        验证token（带缓存）
        
        Args:
            token: JWT token字符串
        
        Returns:
            token claims
        
        Raises:
            HTTPException: 验证失败
        """
        # 1. 先检查缓存
        if self.enable_cache:
            cached_claims = self.token_cache.get(token)
            if cached_claims:
                return cached_claims
        
        # 2. 验证token
        try:
            claims = self.verifier.verify_token(token)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "invalid_token",
                    "message": f"Token验证失败: {str(e)}"
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 3. 存入缓存
        if self.enable_cache:
            # 计算TTL（使用token的exp）
            exp = claims.get('exp')
            if exp:
                ttl = max(0, int(exp - time.time()))
                if ttl > 0:
                    try:
                        success = self.token_cache.set(token, claims, ttl=ttl)
                        if success:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.debug(f"Token已缓存，TTL: {ttl}秒")
                        else:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"Token缓存失败，TTL: {ttl}秒")
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Token缓存异常: {str(e)}")
        else:
            import logging
            logger = logging.getLogger(__name__)
            logger.debug("Token缓存未启用")
        
        return claims
    
    async def verify_token(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = None
    ) -> Dict[str, Any]:
        """
        验证token（内部方法，不直接作为FastAPI依赖）
        
        Args:
            request: FastAPI请求对象
            credentials: HTTP Bearer凭证（可选）
        
        Returns:
            token claims
        
        Raises:
            HTTPException: 验证失败
        """
        # 提取token
        token = None
        
        if credentials:
            token = credentials.credentials
        else:
            token = self._extract_token(request)
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "missing_token",
                    "message": "需要提供认证token。请在Authorization header中使用Bearer token"
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 验证token
        return self._verify_token_with_cache(token)


# 全局认证中间件实例（延迟初始化）
_auth_middleware: Optional[CognitoAuthMiddleware] = None


def get_auth_middleware() -> CognitoAuthMiddleware:
    """
    获取认证中间件实例（单例模式）
    
    Returns:
        CognitoAuthMiddleware实例
    """
    global _auth_middleware
    
    if _auth_middleware is None:
        # 根据配置决定是否启用缓存
        token_cache = None
        if CognitoConfig.ENABLE_REDIS_CACHE:
            try:
                token_cache = get_token_cache()
            except Exception as e:
                logger.warning(f"Redis缓存不可用: {str(e)}，认证功能仍然可用，只是不使用缓存")
        
        _auth_middleware = CognitoAuthMiddleware(
            config=CognitoConfig,
            token_cache=token_cache,
            enable_cache=token_cache is not None
        )
    
    return _auth_middleware


# FastAPI依赖：验证token
async def verify_cognito_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI依赖：验证Cognito JWT token
    
    使用方法：
        @app.get("/protected")
        async def protected_route(claims: dict = Depends(verify_cognito_token)):
            return {"user_id": claims.get("sub")}
    
    Args:
        request: FastAPI请求对象
        credentials: HTTP Bearer凭证
    
    Returns:
        token claims字典
    
    Raises:
        HTTPException: 验证失败
    """
    middleware = get_auth_middleware()
    return await middleware.verify_token(request, credentials)


# 可选：创建一个可选的token验证（不强制要求token）
async def verify_cognito_token_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[Dict[str, Any]]:
    """
    FastAPI依赖：可选验证Cognito JWT token（如果提供了token则验证，否则返回None）
    
    使用方法：
        @app.get("/optional")
        async def optional_route(claims: Optional[dict] = Depends(verify_cognito_token_optional)):
            if claims:
                return {"authenticated": True, "user_id": claims.get("sub")}
            return {"authenticated": False}
    
    Args:
        request: FastAPI请求对象
        credentials: HTTP Bearer凭证
    
    Returns:
        token claims字典（如果提供了有效token），否则返回None
    """
    try:
        middleware = get_auth_middleware()
        token = None
        
        if credentials:
            token = credentials.credentials
        else:
            token = middleware._extract_token(request)
        
        if not token:
            return None
        
        return middleware._verify_token_with_cache(token)
    except HTTPException:
        return None

