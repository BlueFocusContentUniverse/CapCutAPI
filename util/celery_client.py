"""
通用的 Celery 客户端单例工具

提供线程安全的 Celery 客户端实例，在整个项目中复用。
支持不同的 Celery 应用名称（用于不同的项目/服务）。
"""
import logging
import os
import threading
from typing import Dict, Optional

from celery import Celery

logger = logging.getLogger(__name__)

# 全局 Celery 客户端实例字典（按应用名称存储）
_celery_clients: Dict[str, Celery] = {}
_celery_lock = threading.RLock()

# 默认应用名称（用于视频生成等主要功能）
DEFAULT_APP_NAME = None

# Celery 应用名称常量
CELERY_APP_NAME_GENERATE = "video_generation"  # 用于 generate_video
CELERY_APP_NAME_REGENERATE = "video_regeneration"  # 用于 regenerate_video
CELERY_APP_NAME_DRAFT_ARCHIVE = "draft_archive_notice"  # 用于 draft_archive


def get_celery_client(app_name: Optional[str] = None) -> Celery:
    """
    获取 Celery 客户端单例（线程安全）。

    使用双重检查锁定模式确保线程安全。
    支持不同的 Celery 应用名称，用于不同的项目/服务。

    Args:
        app_name: Celery 应用名称，如果为 None 则使用默认配置（不指定应用名称）

    Returns:
        Celery: Celery 客户端实例

    Raises:
        RuntimeError: 如果 CELERY_BROKER_URL 环境变量未设置
    """
    global _celery_clients

    # 使用应用名称作为键，如果为 None 则使用空字符串
    cache_key = app_name or DEFAULT_APP_NAME

    if cache_key not in _celery_clients:
        with _celery_lock:
            # 双重检查锁定
            if cache_key not in _celery_clients:
                broker_url = os.getenv("CELERY_BROKER_URL")
                if not broker_url:
                    raise RuntimeError(
                        "CELERY_BROKER_URL environment variable is required"
                    )

                if app_name:
                    _celery_clients[cache_key] = Celery(
                        app_name, broker=broker_url
                    )
                    logger.info(
                        f"Initialized Celery client '{app_name}' with broker: {broker_url}"
                    )
                else:
                    _celery_clients[cache_key] = Celery(broker=broker_url)
                    logger.info(
                        f"Initialized Celery client (default) with broker: {broker_url}"
                    )

    return _celery_clients[cache_key]


def reset_celery_client(app_name: Optional[str] = None) -> None:
    """
    重置 Celery 客户端实例（主要用于测试）。

    Args:
        app_name: Celery 应用名称，如果为 None 则重置默认客户端

    注意：此方法会清除指定的客户端实例，下次调用 get_celery_client() 时会重新创建。
    """
    global _celery_clients

    cache_key = app_name or DEFAULT_APP_NAME

    with _celery_lock:
        if cache_key in _celery_clients:
            del _celery_clients[cache_key]
            logger.info(f"Reset Celery client instance: {app_name or 'default'}")

