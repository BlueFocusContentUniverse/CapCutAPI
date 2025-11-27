#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWS Cognito 配置管理模块
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class CognitoConfig:
    """AWS Cognito配置类"""
    
    # AWS区域
    REGION: str = os.getenv("COGNITO_REGION", "us-west-2")
    # Cognito用户池ID
    USER_POOL_ID: str = os.getenv("COGNITO_USER_POOL_ID", "")
    # 应用程序客户端ID（用于验证audience）
    CLIENT_ID: str = os.getenv("COGNITO_CLIENT_ID", "")
    
    # Redis Token缓存配置
    ENABLE_REDIS_CACHE: bool = os.getenv("ENABLE_REDIS_CACHE", "true").lower() in ("true", "1", "yes")
    
    @classmethod
    def validate(cls) -> bool:
        """验证配置是否完整"""
        required_fields = {
            "REGION": cls.REGION,
            "USER_POOL_ID": cls.USER_POOL_ID,
            "CLIENT_ID": cls.CLIENT_ID,
        }
        
        missing = [key for key, value in required_fields.items() if not value]
        
        if missing:
            return False
        
        return True

