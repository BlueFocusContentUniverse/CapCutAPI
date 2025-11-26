#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cognito认证依赖（替换现有认证）
支持JWT验证、Redis缓存和Rate Limit
"""

import logging
from typing import Dict, Any, Optional
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from util.cognito.auth_middleware import verify_cognito_token, get_auth_middleware
from util.cognito.rate_limit import get_rate_limiter

logger = logging.getLogger(__name__)

# HTTP Bearer安全方案
security = HTTPBearer(auto_error=False)


async def verify_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI依赖：验证Cognito JWT token（替换原有的verify_api_token）
    
    使用方法：
        router = APIRouter(
            prefix="/api/videos",
            dependencies=[Depends(verify_auth)]
        )
    
    Args:
        request: FastAPI请求对象
        credentials: HTTP Bearer凭证（可选）
    
    Returns:
        token claims字典
    
    Raises:
        HTTPException: 验证失败
    """
    return await verify_cognito_token(request, credentials)


async def verify_auth_with_rate_limit(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    requests_per_minute: Optional[int] = None
) -> Dict[str, Any]:
    """
    FastAPI依赖：验证Cognito JWT token + Rate Limit
    
    使用方法：
        @router.get("/api/limited")
        async def limited_endpoint(
            claims: dict = Depends(verify_auth_with_rate_limit)
        ):
            return {"message": "成功"}
        
        或者自定义速率限制：
        @router.get("/api/limited")
        async def limited_endpoint(
            claims: dict = Depends(lambda: verify_auth_with_rate_limit(requests_per_minute=100))
        ):
            return {"message": "成功"}
    
    Args:
        request: FastAPI请求对象
        credentials: HTTP Bearer凭证（可选）
        requests_per_minute: 每分钟允许的请求数（如果为None，从配置读取）
    
    Returns:
        token claims字典
    
    Raises:
        HTTPException: 验证失败或超过速率限制
    """
    # 先验证token
    claims = await verify_cognito_token(request, credentials)
    
    # 然后检查rate limit
    limiter = get_rate_limiter(requests_per_minute=requests_per_minute)
    limiter.check_rate_limit(claims=claims)
    
    return claims


# 为了向后兼容，保留原有函数名（但使用Cognito验证）
verify_api_token = verify_auth

