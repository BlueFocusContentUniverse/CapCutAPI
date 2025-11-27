#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cognito认证依赖
支持JWT验证和Redis缓存
"""

import logging
from typing import Dict, Any, Optional
from fastapi import Request, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from util.cognito.auth_middleware import verify_cognito_token

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


async def verify_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI依赖：验证Cognito JWT token
    
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


verify_api_token = verify_auth

