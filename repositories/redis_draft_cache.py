#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis草稿缓存层（基于dogpile.cache）
- L1缓存：Redis（10分钟TTL）
- L2持久化：PostgreSQL
- 写入策略：Write-Through + Write-Behind
"""

import logging
import pickle
import time
import threading
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse

try:
    from dogpile.cache import make_region
    from dogpile.cache.backends.redis import RedisBackend
    DOGPILE_AVAILABLE = True
except ImportError:
    DOGPILE_AVAILABLE = False
    make_region = None
    RedisBackend = None

import pyJianYingDraft as draft
from repositories.draft_repository import PostgresDraftStorage, get_postgres_storage

logger = logging.getLogger(__name__)

# Redis配置
DRAFT_CACHE_TTL = 600  # 10分钟
DRAFT_CACHE_KEY_PREFIX = "draft:cache:"
DRAFT_DIRTY_KEY_PREFIX = "draft:dirty:"
SYNC_INTERVAL = 60  # 同步间隔（秒）


class RedisDraftCache:
    """Redis草稿缓存层"""
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        pg_storage: Optional[PostgresDraftStorage] = None,
        enable_sync: bool = True
    ):
        """
        初始化Redis缓存层
        
        Args:
            redis_url: Redis连接URL，格式: redis://[:password]@host:port/db
            pg_storage: PostgreSQL存储实例
            enable_sync: 是否启用后台同步任务
        """
        if not DOGPILE_AVAILABLE:
            raise ImportError("dogpile.cache包未安装，请运行: pip install 'dogpile.cache[redis]'")
        
        self.pg_storage = pg_storage or get_postgres_storage()
        self.enable_sync = enable_sync
        self._sync_thread = None
        self._stop_sync = False
        
        # 解析Redis URL
        if redis_url:
            redis_config = self._parse_redis_url(redis_url)
        else:
            # 从环境变量读取
            import os
            redis_url = os.getenv("DRAFT_CACHE_REDIS_URL", "redis://localhost:6379/3")
            redis_config = self._parse_redis_url(redis_url)
        
        # 创建dogpile.cache region
        # key_mangler 应该返回字符串，dogpile.cache 会处理编码
        self.cache_region = make_region(
            key_mangler=lambda key: f"{DRAFT_CACHE_KEY_PREFIX}{key}"
        ).configure(
            'dogpile.cache.redis',
            arguments={
                'host': redis_config['host'],
                'port': redis_config['port'],
                'db': redis_config['db'],
                'password': redis_config.get('password'),
                'socket_timeout': 5,
                'socket_connect_timeout': 5,
                'decode_responses': False,  # 使用bytes模式（pickle需要）
            },
            expiration_time=DRAFT_CACHE_TTL,
        )
        
        # 创建Redis客户端用于脏数据标记和统计
        try:
            import redis
            self.redis_client = redis.Redis(
                host=redis_config['host'],
                port=redis_config['port'],
                db=redis_config['db'],
                password=redis_config.get('password'),
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self.redis_client.ping()
            logger.info(f"Redis缓存连接成功: {redis_url}")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise
        
        # 启动后台同步任务
        if enable_sync:
            self._start_sync_task()
    
    def _parse_redis_url(self, redis_url: str) -> Dict[str, Any]:
        """解析Redis URL"""
        parsed = urlparse(redis_url)
        config = {
            'host': parsed.hostname or "localhost",
            'port': parsed.port or 6379,
            'db': int(parsed.path.lstrip('/')) if parsed.path else 0,
        }
        if parsed.password:
            config['password'] = parsed.password
        return config
    
    def _get_cache_key(self, draft_id: str) -> str:
        """生成缓存key（用于dogpile.cache）"""
        return draft_id
    
    def _get_dirty_key(self, draft_id: str) -> bytes:
        """生成脏数据标记key"""
        return f"{DRAFT_DIRTY_KEY_PREFIX}{draft_id}".encode()
    
    def get_draft(self, draft_id: str) -> Optional[draft.ScriptFile]:
        """
        获取草稿（Read-Through策略）
        
        1. 先查Redis（dogpile.cache自动处理缓存击穿）
        2. 未命中则查PostgreSQL并写入Redis
        3. 命中后自动刷新TTL
        """
        cache_key = self._get_cache_key(draft_id)
        
        try:
            # 使用dogpile.cache的get_or_create，自动处理缓存击穿
            def _get_from_pg() -> Optional[bytes]:
                """从PostgreSQL获取并序列化"""
                script_obj = self.pg_storage.get_draft(draft_id)
                if script_obj:
                    return pickle.dumps(script_obj)
                return None
            
            # 使用get_or_create，自动处理缓存击穿和并发
            cached_data = self.cache_region.get_or_create(
                cache_key,
                _get_from_pg,
                expiration_time=DRAFT_CACHE_TTL
            )
            
            if cached_data:
                script_obj = pickle.loads(cached_data)
                logger.debug(f"从Redis缓存获取草稿: {draft_id}")
                return script_obj
            
        except Exception as e:
            logger.warning(f"Redis读取失败: {e}，降级到PostgreSQL")
            # 降级到PostgreSQL
            try:
                return self.pg_storage.get_draft(draft_id)
            except Exception as pg_error:
                logger.error(f"PostgreSQL读取失败: {pg_error}")
        
        return None
    
    def get_draft_with_version(self, draft_id: str) -> Optional[Tuple[draft.ScriptFile, int]]:
        """获取草稿及版本号"""
        script_obj = self.get_draft(draft_id)
        if script_obj is None:
            return None
        
        # 从PostgreSQL获取版本号（版本号只在PG中维护）
        try:
            result = self.pg_storage.get_draft_with_version(draft_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"获取版本号失败: {e}")
        
        # 降级：返回默认版本
        return (script_obj, 1)
    
    def save_draft(
        self,
        draft_id: str,
        script_obj: draft.ScriptFile,
        expected_version: Optional[int] = None,
        mark_dirty: bool = True
    ) -> bool:
        """
        保存草稿（Write-Through + Write-Behind策略）
        
        1. 先写Redis（立即返回）
        2. 如果mark_dirty=True，标记为脏数据
        3. 如果提供了expected_version，立即同步到PG（保证一致性）
        4. 否则后台任务定期同步到PostgreSQL
        """
        try:
            cache_key = self._get_cache_key(draft_id)
            serialized_data = pickle.dumps(script_obj)
            
            # 1. 先写Redis（立即返回）
            self.cache_region.set(cache_key, serialized_data)
            
            # 标记为脏数据（如果需要）
            if mark_dirty:
                dirty_key = self._get_dirty_key(draft_id)
                self.redis_client.setex(dirty_key, DRAFT_CACHE_TTL * 2, b"1")
            
            # 2. 如果提供了expected_version，立即同步到PG（保证一致性）
            # 这种情况下需要创建版本记录，因为涉及版本控制
            if expected_version is not None:
                success = self.pg_storage.save_draft(
                    draft_id,
                    script_obj,
                    expected_version=expected_version,
                    create_version=True  # 版本控制需要创建版本记录
                )
                if success:
                    # 清除脏数据标记（如果存在）
                    if mark_dirty:
                        self.redis_client.delete(dirty_key)
                    logger.debug(f"立即同步草稿到PostgreSQL: {draft_id}（已创建版本记录）")
                else:
                    # 同步失败，如果标记了脏数据则保留标记以便后台任务重试
                    if mark_dirty:
                        logger.warning(f"立即同步失败，保留脏数据标记: {draft_id}")
                return success
            
            # 3. 否则标记为脏数据，等待后台同步
            logger.debug(f"草稿已写入Redis缓存: {draft_id}，等待后台同步")
            return True
            
        except Exception as e:
            logger.error(f"保存草稿失败: {draft_id}: {e}")
            return False
    
    def _sync_to_postgres(self):
        """后台同步任务：将脏数据同步到PostgreSQL"""
        try:
            # 使用SCAN代替KEYS，避免阻塞Redis
            pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            dirty_keys = []
            cursor = 0
            scan_count = 0
            max_scan_iterations = 1000  # 防止无限循环
            
            while scan_count < max_scan_iterations:
                try:
                    cursor, keys = self.redis_client.scan(
                        cursor,
                        match=pattern.encode(),
                        count=100
                    )
                    dirty_keys.extend(keys)
                    scan_count += 1
                    if cursor == 0:
                        break
                except Exception as e:
                    logger.error(f"SCAN操作失败: {e}")
                    break
            
            if not dirty_keys:
                return
            
            logger.info(f"开始同步 {len(dirty_keys)} 个脏数据到PostgreSQL")
            
            synced_count = 0
            failed_count = 0
            for dirty_key in dirty_keys:
                draft_id = None
                try:
                    # 检查脏数据标记是否仍然存在（可能已被立即同步清除）
                    if not self.redis_client.exists(dirty_key):
                        continue  # 跳过，已被其他操作清除
                    # 提取draft_id
                    draft_id = dirty_key.decode().replace(DRAFT_DIRTY_KEY_PREFIX, "")
                    cache_key = self._get_cache_key(draft_id)
                    
                    # 从dogpile.cache获取缓存数据
                    cached_data = self.cache_region.get(cache_key)
                    if not cached_data:
                        # 缓存已过期，清除脏数据标记
                        self.redis_client.delete(dirty_key)
                        continue
                    
                    # 反序列化
                    script_obj = pickle.loads(cached_data)
                    
                    # 获取当前版本号（用于乐观锁，从PostgreSQL获取）
                    current_version = None
                    try:
                        result = self.pg_storage.get_draft_with_version(draft_id)
                        if result:
                            _, current_version = result
                    except Exception as e:
                        logger.warning(f"获取版本号失败 {draft_id}: {e}")
                    
                    # 同步到PostgreSQL（持久化操作，创建版本记录）
                    # 使用版本控制避免覆盖并发更新
                    success = self.pg_storage.save_draft(
                        draft_id,
                        script_obj,
                        expected_version=current_version,
                        create_version=True  # 持久化时创建版本记录
                    )
                    if success:
                        # 清除脏数据标记
                        self.redis_client.delete(dirty_key)
                        synced_count += 1
                        logger.debug(f"同步草稿到PostgreSQL: {draft_id}（已创建版本记录）")
                    else:
                        # 同步失败（可能是版本冲突），保留脏数据标记以便下次重试
                        failed_count += 1
                        logger.warning(f"同步草稿失败（可能是版本冲突）: {draft_id}")
                        # 延长脏数据标记的TTL，确保不会丢失
                        self.redis_client.expire(dirty_key, DRAFT_CACHE_TTL * 2)
                    
                except Exception as e:
                    failed_count += 1
                    draft_id_str = draft_id or "unknown"
                    logger.error(f"同步草稿失败 {draft_id_str}: {e}", exc_info=True)
            
            if synced_count > 0 or failed_count > 0:
                logger.info(f"同步完成: {synced_count} 成功, {failed_count} 失败, 共 {len(dirty_keys)} 个草稿")
            
        except Exception as e:
            logger.error(f"后台同步任务失败: {e}", exc_info=True)
    
    def _start_sync_task(self):
        """启动后台同步任务"""
        def sync_loop():
            while not self._stop_sync:
                try:
                    time.sleep(SYNC_INTERVAL)
                    if not self._stop_sync:
                        self._sync_to_postgres()
                except Exception as e:
                    logger.error(f"同步任务异常: {e}")
        
        self._stop_sync = False
        self._sync_thread = threading.Thread(target=sync_loop, daemon=True)
        self._sync_thread.start()
        logger.info("后台同步任务已启动")
    
    def stop_sync_task(self):
        """停止后台同步任务"""
        self._stop_sync = True
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        logger.info("后台同步任务已停止")
    
    def exists(self, draft_id: str) -> bool:
        """检查草稿是否存在"""
        cache_key = self._get_cache_key(draft_id)
        
        # 先查Redis
        try:
            cached_data = self.cache_region.get(cache_key)
            if cached_data is not None:
                return True
        except Exception as e:
            logger.warning(f"Redis检查失败: {e}")
        
        # 再查PostgreSQL
        try:
            return self.pg_storage.exists(draft_id)
        except Exception as e:
            logger.error(f"PostgreSQL检查失败: {e}")
            return False
    
    def delete_draft(self, draft_id: str) -> bool:
        """删除草稿"""
        cache_key = self._get_cache_key(draft_id)
        dirty_key = self._get_dirty_key(draft_id)
        
        try:
            # 删除Redis缓存和脏数据标记
            self.cache_region.delete(cache_key)
            self.redis_client.delete(dirty_key)
        except Exception as e:
            logger.warning(f"Redis删除失败: {e}")
        
        # 删除PostgreSQL
        try:
            return self.pg_storage.delete_draft(draft_id)
        except Exception as e:
            logger.error(f"PostgreSQL删除失败: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        stats = {
            "redis_available": True,
            "cache_ttl_seconds": DRAFT_CACHE_TTL,
            "sync_interval_seconds": SYNC_INTERVAL,
            "backend": "dogpile.cache",
        }
        
        try:
            # 统计Redis中的缓存数量（使用SCAN）
            pattern = f"{DRAFT_CACHE_KEY_PREFIX}*"
            cache_keys = []
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor, match=pattern.encode(), count=100)
                cache_keys.extend(keys)
                if cursor == 0:
                    break
            stats["redis_cache_count"] = len(cache_keys)
            
            # 统计脏数据数量（使用SCAN）
            dirty_pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            dirty_keys = []
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(cursor, match=dirty_pattern.encode(), count=100)
                dirty_keys.extend(keys)
                if cursor == 0:
                    break
            stats["dirty_count"] = len(dirty_keys)
        except Exception as e:
            logger.warning(f"获取Redis统计失败: {e}")
            stats["redis_available"] = False
        
        # PostgreSQL统计
        try:
            pg_stats = self.pg_storage.get_stats()
            stats["postgres_stats"] = pg_stats
        except Exception as e:
            logger.warning(f"获取PostgreSQL统计失败: {e}")
            stats["postgres_stats"] = {}
        
        return stats


# 全局实例
_redis_cache: Optional[RedisDraftCache] = None


def get_redis_draft_cache() -> Optional[RedisDraftCache]:
    """
    获取Redis缓存实例（单例）
    
    如果Redis不可用，返回None（降级到PostgreSQL）
    """
    global _redis_cache
    
    if _redis_cache is not None:
        return _redis_cache
    
    if not DOGPILE_AVAILABLE:
        logger.warning("dogpile.cache包未安装，Redis缓存不可用")
        return None
    
    try:
        _redis_cache = RedisDraftCache()
        return _redis_cache
    except Exception as e:
        logger.warning(f"Redis缓存初始化失败: {e}，将降级到PostgreSQL")
        return None
