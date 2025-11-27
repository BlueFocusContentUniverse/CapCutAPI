#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AWS Cognito 配置管理模块
"""

import os
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载.env文件
env_path = Path(__file__).parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"已加载环境配置文件: {env_path}")
else:
    logger.warning(
        f".env文件未找到: {env_path}\n"
        f"将使用系统环境变量。如果需要加载.env文件，请确保文件存在。"
    )

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

