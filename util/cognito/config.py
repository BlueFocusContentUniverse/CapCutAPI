#!/usr/bin/env python3
"""
AWS Cognito 配置管理模块
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class _LazyEnvVar:
    """延迟加载环境变量的描述符"""

    def __init__(self, env_key: str, default: str = ""):
        self.env_key = env_key
        self.default = default
        self._value: Optional[str] = None

    def __get__(self, obj, objtype=None):
        if self._value is None:
            self._value = os.getenv(self.env_key, self.default)
        return self._value


class _LazyBoolEnvVar:
    """延迟加载布尔环境变量的描述符"""

    def __init__(self, env_key: str, default: bool = True):
        self.env_key = env_key
        self.default = default
        self._value: Optional[bool] = None

    def __get__(self, obj, objtype=None):
        if self._value is None:
            value = os.getenv(self.env_key, "true" if self.default else "false")
            self._value = value.lower() in ("true", "1", "yes")
        return self._value


class CognitoConfig:
    """AWS Cognito配置类（延迟加载环境变量）"""

    # 使用描述符实现延迟加载
    REGION: str = _LazyEnvVar("COGNITO_REGION", "us-west-2")
    USER_POOL_ID: str = _LazyEnvVar("COGNITO_USER_POOL_ID", "")
    CLIENT_ID: str = _LazyEnvVar("COGNITO_CLIENT_ID", "")
    ENABLE_REDIS_CACHE: bool = _LazyBoolEnvVar("ENABLE_REDIS_CACHE", True)

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

