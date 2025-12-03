#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Redis草稿缓存层（读取侧基于dogpile.cache，写入侧使用Redis客户端保证事务完整性）
- L1缓存：Redis（10分钟TTL）
- L2持久化：PostgreSQL
- 写入策略：Write-Through + Write-Behind
"""

import logging
import pickle
import time
import threading
import json
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
    
    def _serialize_for_dogpile(self, data: bytes) -> bytes:
        """
        模拟 dogpile.cache 的序列化格式
        
        dogpile.cache 的格式：{"ct": timestamp, "v": version}|<实际数据>
        - ct: 创建时间戳
        - v: 版本号（通常是2）
        - |: 分隔符
        - 后面是实际的数据（pickle序列化的数据）
        """
        metadata = {
            "ct": time.time(),
            "v": 2  # dogpile.cache 的版本号
        }
        metadata_json = json.dumps(metadata).encode('utf-8')
        return metadata_json + b"|" + data
    
    def _deserialize_cached_data(self, cached_data: Any, draft_id: str) -> Optional[draft.ScriptFile]:
        """
        反序列化缓存数据
        
        Args:
            cached_data: 从 dogpile.cache 获取的数据（通常是 bytes，也可能是 ScriptFile 对象）
            draft_id: 草稿ID（用于日志）
        
        Returns:
            ScriptFile 对象，如果反序列化失败则返回 None
        """
        if isinstance(cached_data, bytes):
            try:
                return pickle.loads(cached_data)
            except Exception as e:
                logger.warning(f"反序列化失败 {draft_id}: {e}")
                return None
        elif isinstance(cached_data, draft.ScriptFile):
            # 如果已经是 ScriptFile 对象（可能是旧数据），直接返回
            return cached_data
        else:
            logger.warning(f"不支持的缓存数据类型: {type(cached_data)}, draft_id: {draft_id}")
            return None
    
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
                script_obj = self._deserialize_cached_data(cached_data, draft_id)
                if script_obj:
                    logger.debug(f"从Redis缓存获取草稿: {draft_id}")
                    return script_obj
                # 反序列化失败，降级到PostgreSQL
                return self.pg_storage.get_draft(draft_id)
            
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
        
        1. 使用Redis事务原子性地写入缓存和脏数据标记
        2. 如果提供了expected_version，立即同步到PG（保证一致性）
        3. 否则后台任务定期同步到PostgreSQL
        
        注意：写入时绕过dogpile.cache，直接使用Redis客户端以保证事务原子性
        """
        try:
            cache_key = self._get_cache_key(draft_id)  # 返回 draft_id（不带前缀）
            # dogpile.cache 会自动添加前缀，所以需添加前缀以保持一致
            # 使用bytes格式，因为redis_client使用decode_responses=False
            cache_key_with_prefix = f"{DRAFT_CACHE_KEY_PREFIX}{cache_key}".encode()
            
            # 序列化数据：先pickle，然后模拟dogpile.cache的格式
            # 这样读取时可以使用dogpile.cache的get()，衔接dogpile.cache的防缓存击穿功能
            pickled_data = pickle.dumps(script_obj)
            serialized_data = self._serialize_for_dogpile(pickled_data)
            
            # 1. 使用Redis事务原子性地写入缓存和脏数据标记（绕过dogpile.cache的set()方法，直接使用Redis客户端以保证事务原子性）
            # 但使用dogpile.cache的序列化格式，确保读取时可以使用dogpile.cache的get()
            # pipeline(transaction=True) 会自动使用 MULTI/EXEC 保证原子性
            pipe = self.redis_client.pipeline(transaction=True)
            
            # 操作1：写入缓存（直接使用Redis，但使用dogpile.cache的序列化格式）
            # 使用带前缀的key，与dogpile.cache保持一致
            pipe.setex(cache_key_with_prefix, DRAFT_CACHE_TTL, serialized_data)
            
            # 操作2：标记为脏数据（如果需要）
            dirty_key = None
            if mark_dirty:
                dirty_key = self._get_dirty_key(draft_id)
                pipe.setex(dirty_key, DRAFT_CACHE_TTL * 2, b"1")
            
            # 执行事务（保证原子性：所有命令一起执行）
            try:
                results = pipe.execute()
                # 检查结果（Redis事务不保证回滚，需要检查返回值）
                # results 是一个列表，每个元素对应一个命令的执行结果
                if not results or not all(results):
                    logger.warning(f"Redis事务执行部分失败: {draft_id}, results: {results}")
                    return False
            except Exception as e:
                logger.error(f"Redis事务执行失败: {draft_id}: {e}")
                return False
            
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
                    if mark_dirty and dirty_key:
                        try:
                            self.redis_client.delete(dirty_key)
                        except Exception as e:
                            logger.warning(f"清除脏数据标记失败: {draft_id}: {e}")
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
            skipped_count = 0  # 跳过的数量（缓存不存在、已过期、格式错误等）
            for dirty_key in dirty_keys:
                draft_id = None
                try:
                    # 检查脏数据标记是否仍然存在（可能已被立即同步清除）
                    if not self.redis_client.exists(dirty_key):
                        skipped_count += 1
                        continue  # 跳过，已被其他操作清除
                    # 提取draft_id
                    draft_id = dirty_key.decode().replace(DRAFT_DIRTY_KEY_PREFIX, "")
                    cache_key = self._get_cache_key(draft_id)
                    
                    # 写入时使用了dogpile.cache的序列化格式，所以可以正常读取
                    try:
                        cached_data = self.cache_region.get(cache_key)
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
                        # 数据格式错误
                        logger.error(f"缓存数据格式错误 {draft_id}: {e}，清除脏标记并跳过")
                        self.redis_client.delete(dirty_key)
                        skipped_count += 1
                        continue
                    
                    if not cached_data:
                        # 缓存已过期，清除脏数据标记
                        self.redis_client.delete(dirty_key)
                        skipped_count += 1
                        continue
                    
                    # 反序列化缓存数据
                    script_obj = self._deserialize_cached_data(cached_data, draft_id)
                    if not script_obj:
                        # 反序列化失败，清除脏标记并跳过
                        self.redis_client.delete(dirty_key)
                        skipped_count += 1
                        continue
                    
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
            
            if synced_count > 0 or failed_count > 0 or skipped_count > 0:
                logger.info(f"同步完成: {synced_count} 成功, {failed_count} 失败, {skipped_count} 跳过, 共 {len(dirty_keys)} 个脏数据标记")
            
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
