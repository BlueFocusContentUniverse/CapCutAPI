#!/usr/bin/env python3
"""
Redis草稿缓存层（异步版本）
- L1缓存：Redis（10分钟TTL）
- L2持久化：PostgreSQL（异步）
- 写入策略：Write-Through + Write-Behind
- 后台同步：使用 asyncio 任务
"""

import asyncio
import logging
import os
import pickle
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as aioredis
from sqlalchemy import exc as sa_exc

import pyJianYingDraft as draft
from repositories.draft_repository import PostgresDraftStorage, get_postgres_storage

logger = logging.getLogger(__name__)

# 配置常量
DRAFT_CACHE_TTL = 600  # 10分钟
DRAFT_CACHE_KEY_PREFIX = "draft:cache:"
DRAFT_DIRTY_KEY_PREFIX = "draft:dirty:"  # 使用 Redis Set 记录待同步的 Key
DRAFT_DIRTY_FAIL_COUNT_PREFIX = "draft:dirty:fail:"  # 记录脏数据同步失败次数的 Key 前缀
SYNC_LOCK_PREFIX = "lock:sync:"  # 同步锁前缀，用于防止并发同步时的版本冲突
SYNC_LOCK_TTL = 30  # 同步锁过期时间（秒），应该足够覆盖一次同步操作的时间
MAX_DIRTY_FAIL_COUNT = (
    5  # 脏数据同步失败的最大次数，超过此次数后彻底删除（防止错误循环）
)
SYNC_INTERVAL = 60
MAX_SYNC_BATCH_SIZE = 1000  # 单次同步的最大脏数据数量（避免单次同步时间过长）
MAX_SYNC_WORKERS = 5  # 并发同步的协程数（默认5）
RETRYABLE_ERR_TYPES = (
    OSError,
    TimeoutError,
    ConnectionError,
    sa_exc.OperationalError,
    sa_exc.InterfaceError,
    sa_exc.DisconnectionError,
)
RETRYABLE_KEYWORDS = (
    "connection",
    "timeout",
    "network",
    "temporary",
    "retry",
    "lock wait",
    "deadlock",
)


class RedisDraftCache:
    def __init__(
        self,
        redis_url: Optional[str] = None,
        pg_storage: Optional[PostgresDraftStorage] = None,
        enable_sync: bool = True,
        max_sync_batch_size: int = MAX_SYNC_BATCH_SIZE,
        max_sync_workers: int = MAX_SYNC_WORKERS,
    ):
        self.pg_storage = pg_storage or get_postgres_storage()
        self.enable_sync = enable_sync
        self.max_sync_batch_size = max_sync_batch_size
        self.max_sync_workers = max_sync_workers
        self._sync_task: Optional[asyncio.Task] = None
        self._stop_sync = False

        redis_url = redis_url or os.getenv("DRAFT_CACHE_REDIS_URL")
        if not redis_url:
            raise ValueError(
                "Redis草稿缓存层未配置，请检查 DRAFT_CACHE_REDIS_URL 环境变量"
            )

        self._redis_url = redis_url
        # 异步 Redis 客户端（延迟初始化）
        self.redis_client: Optional[aioredis.Redis] = None

    async def _ensure_redis_client(self) -> aioredis.Redis:
        """确保 Redis 客户端已初始化"""
        if self.redis_client is None:
            self.redis_client = aioredis.from_url(
                self._redis_url,
                decode_responses=False,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            # 验证连接
            await self.redis_client.ping()
            logger.info(f"Redis缓存连接成功: {self._redis_url}")
        return self.redis_client

    def _get_cache_key(self, draft_id: str) -> str:
        """生成完整缓存key"""
        return f"{DRAFT_CACHE_KEY_PREFIX}{draft_id}"

    def _get_dirty_key(self, draft_id: str) -> str:
        """生成脏数据标记key"""
        return f"{DRAFT_DIRTY_KEY_PREFIX}{draft_id}"

    def _get_version_key(self, draft_id: str) -> str:
        """生成版本号key"""
        return f"draft:version:{draft_id}"

    def _get_dirty_fail_count_key(self, draft_id: str) -> str:
        """生成脏数据同步失败计数key"""
        return f"{DRAFT_DIRTY_FAIL_COUNT_PREFIX}{draft_id}"

    def _get_sync_lock_key(self, draft_id: str) -> str:
        """生成同步锁key"""
        return f"{SYNC_LOCK_PREFIX}{draft_id}"

    async def get_draft(self, draft_id: str) -> Optional[draft.ScriptFile]:
        """
        获取草稿（Read-Through策略）

        1. 优先从Redis获取
        2. 未命中则查PostgreSQL并写入Redis
        """
        redis = await self._ensure_redis_client()
        cache_key = self._get_cache_key(draft_id)

        # 尝试从 Redis 获取
        try:
            cached_bytes = await redis.get(cache_key)
            if cached_bytes:
                try:
                    script_obj = pickle.loads(cached_bytes)
                    if isinstance(script_obj, draft.ScriptFile):
                        logger.debug(f"从Redis缓存获取草稿: {draft_id}")
                        return script_obj
                except Exception as e:
                    logger.warning(f"反序列化失败 {draft_id}: {e}")
        except Exception as e:
            logger.warning(f"Redis读取失败: {e}，降级到PostgreSQL")

        # 从 PostgreSQL 获取
        try:
            result = await self.pg_storage.get_draft_with_version(draft_id)
            if result:
                script_obj, version = result
                # 写入 Redis 缓存
                try:
                    pickled_data = pickle.dumps(script_obj)
                    version_key = self._get_version_key(draft_id)
                    pipe = redis.pipeline(transaction=True)
                    pipe.setex(cache_key, DRAFT_CACHE_TTL, pickled_data)
                    pipe.setex(
                        version_key, DRAFT_CACHE_TTL, str(version).encode("utf-8")
                    )
                    await pipe.execute()
                    logger.debug(
                        f"从PostgreSQL加载并写入Redis缓存: {draft_id}, version={version}"
                    )
                except Exception as e:
                    logger.warning(f"写入Redis缓存失败: {e}")
                return script_obj
            return None
        except Exception as e:
            logger.error(f"PostgreSQL读取失败: {e}")
            return None

    async def get_draft_with_version(
        self, draft_id: str
    ) -> Optional[Tuple[draft.ScriptFile, int]]:
        """
        获取草稿及版本号（优先从 Redis 读取）
        """
        redis = await self._ensure_redis_client()
        cache_key = self._get_cache_key(draft_id)
        version_key = self._get_version_key(draft_id)

        try:
            res = await redis.mget([cache_key, version_key])
            cached_bytes, version_bytes = res[0], res[1]
        except Exception as e:
            logger.warning(f"Redis MGET 失败: {e}")
            cached_bytes, version_bytes = None, None

        # 如果两样都有，直接返回
        if cached_bytes and version_bytes:
            try:
                script_obj = pickle.loads(cached_bytes)
                version = int(version_bytes.decode("utf-8"))
                return (script_obj, version)
            except Exception as e:
                logger.debug(f"缓存解析失败，降级到PG: {e}")

        # 从 PostgreSQL 获取
        script_obj = await self.get_draft(draft_id)
        if script_obj is None:
            return None

        # 尝试获取版本号
        try:
            v_data = await redis.get(version_key)
            if v_data:
                version = int(v_data.decode("utf-8"))
                return (script_obj, version)
        except Exception as e:
            logger.warning(f"获取版本号失败: {e}")

        # 从 PG 获取版本号
        result = await self.pg_storage.get_draft_with_version(draft_id)
        if result:
            _, version = result
            return (script_obj, version)

        # 新草稿返回版本 0
        return (script_obj, 0)

    async def save_draft(
        self,
        draft_id: str,
        script_obj: draft.ScriptFile,
        expected_version: Optional[int] = None,
        mark_dirty: bool = True,
    ) -> bool:
        """
        保存草稿（Write-Through + Write-Behind策略）
        """
        try:
            logger.info(
                f"save_draft 被调用: draft_id={draft_id}, mark_dirty={mark_dirty}, expected_version={expected_version}"
            )
            redis = await self._ensure_redis_client()

            cache_key = self._get_cache_key(draft_id)
            version_key = self._get_version_key(draft_id)
            pickled_data = pickle.dumps(script_obj)

            # 版本号逻辑
            if not mark_dirty and expected_version is not None:
                version = expected_version
            else:
                version = 1 if expected_version is None else (expected_version + 1)

            # Redis 事务
            pipe = redis.pipeline(transaction=True)
            pipe.setex(cache_key, DRAFT_CACHE_TTL, pickled_data)
            pipe.setex(version_key, DRAFT_CACHE_TTL, str(version).encode("utf-8"))

            if mark_dirty:
                dirty_key = self._get_dirty_key(draft_id)
                pipe.setex(dirty_key, DRAFT_CACHE_TTL * 2, b"1")
            else:
                logger.warning(
                    f"警告: 保存草稿 {draft_id} 时 mark_dirty=False，不会标记为脏数据"
                )

            results = await pipe.execute()

            if not results:
                logger.error(f"Redis 事务返回空结果: {draft_id}")
                return False

            for i, result in enumerate(results):
                if result is False or result is None or isinstance(result, Exception):
                    logger.error(
                        f"Redis 事务命令 {i} 执行失败: {draft_id}, result={result}"
                    )
                    return False

            logger.debug(
                f"成功存入 Redis 缓存: {draft_id}, v={version}, dirty={mark_dirty}"
            )
            return True

        except Exception as e:
            logger.error(f"save_draft 执行崩溃: {draft_id}, 错误: {e}", exc_info=True)
            return False

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否为临时性错误（可重试）"""
        if isinstance(error, RETRYABLE_ERR_TYPES):
            return True

        error_type_name = type(error).__name__
        if any(x in error_type_name for x in ("Connection", "Timeout", "Operational")):
            return True

        error_msg = str(error).lower()
        if any(kw in error_msg for kw in RETRYABLE_KEYWORDS):
            return True

        return False

    async def sync_if_dirty(self, draft_id: str) -> bool:
        """
            检查并同步脏数据。
            
            逻辑路径：
            1. 检查 Redis 脏数据标记是否存在。
            2. 若存在且未在同步中：触发带锁同步，成功后数据回填 Redis。
            3. 若正在同步中：避让等待，期望同步协程写回缓存。
            4. 异常或无脏数据：告知调用方 fallback 至持久层。
            Returns:
                bool: True 表示最新数据应已存在于 Redis；False 表示应直接读取 PostgreSQL。
            """
        try:
            redis = await self._ensure_redis_client()
            dirty_key_str = self._get_dirty_key(draft_id)
            dirty_key_bytes = dirty_key_str.encode("utf-8")
            
            # 检查是否有脏数据标记
            if not await redis.exists(dirty_key_bytes):
                logger.debug(f"sync_if_dirty: {draft_id} 无脏数据标记，无需同步")
                return False  # 无脏数据，数据不在Redis中，建议直接读PG
            
            logger.info(f"sync_if_dirty: 检测到脏数据标记，触发同步: {draft_id}")
            # 触发同步（带锁，避免重复）
            result = await self._sync_single_draft(dirty_key_bytes)
            draft_id_synced, status, reason = result
            logger.info(f"sync_if_dirty: 同步结果 {draft_id_synced}, status={status}, reason={reason}")
            
            # 如果同步成功，数据应该在Redis中
            if status == "synced":
                return True
            
            # 如果正在同步（其他协程），等待一小段时间后再返回True，避免立即读取时数据还没准备好
            if status == "skipped" and reason == "already_syncing":
                logger.debug(f"sync_if_dirty: {draft_id} 正在被其他协程同步，等待一小段时间")
                await asyncio.sleep(0.1)
                return True
            
            # 其他情况（跳过、失败等），返回False，建议直接读PG
            logger.debug(f"sync_if_dirty: {draft_id} 同步状态={status}, 建议直接读PostgreSQL")
            return False
            
        except Exception as e:
            logger.warning(f"sync_if_dirty: 检查脏数据标记或同步失败 {draft_id}: {e}")
            return False  # 异常情况，建议直接读PG

    async def _sync_single_draft(self, dirty_key: bytes) -> Tuple[str, str, str]:
        """
        同步单个草稿到PostgreSQL（带重试机制和分布式锁）
        """
        draft_id = None
        max_retries = 2
        retry_count = 0
        lock_acquired = False
        lock_key = None
        redis = await self._ensure_redis_client()

        while retry_count <= max_retries:
            try:
                # 检查脏数据标记是否仍然存在
                if not await redis.exists(dirty_key):
                    draft_id_str = (
                        dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "")
                        if draft_id is None
                        else draft_id
                    )
                    logger.debug(f"跳过同步 {draft_id_str}: 脏数据标记已不存在")
                    return (draft_id_str, "skipped", "dirty_key_not_exists")

                draft_id = dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "")

                # 获取同步锁
                lock_key = self._get_sync_lock_key(draft_id)
                lock_key_bytes = (
                    lock_key.encode("utf-8") if isinstance(lock_key, str) else lock_key
                )

                lock_acquired = await redis.set(
                    lock_key_bytes, b"1", nx=True, ex=SYNC_LOCK_TTL
                )

                if not lock_acquired:
                    logger.debug(f"跳过同步 {draft_id}: 同步锁已被其他协程获取")
                    return (draft_id, "skipped", "already_syncing")

                cache_key = self._get_cache_key(draft_id)

                # 从 Redis 读取数据
                try:
                    cached_bytes = await redis.get(cache_key)
                except Exception as e:
                    logger.error(f"缓存读取错误 {draft_id}: {e}")
                    version_key = self._get_version_key(draft_id)
                    await redis.delete(cache_key, version_key, dirty_key)
                    return (draft_id, "skipped", "cache_read_error")

                if not cached_bytes:
                    logger.warning(f"跳过同步 {draft_id}: 缓存已过期")
                    version_key = self._get_version_key(draft_id)
                    await redis.delete(cache_key, version_key, dirty_key)
                    return (draft_id, "skipped", "cache_expired")

                # 反序列化
                try:
                    script_obj = pickle.loads(cached_bytes)
                    if not isinstance(script_obj, draft.ScriptFile):
                        logger.warning(f"跳过同步 {draft_id}: 数据格式错误")
                        version_key = self._get_version_key(draft_id)
                        await redis.delete(cache_key, version_key, dirty_key)
                        return (draft_id, "skipped", "data_format_error")
                except Exception as e:
                    logger.warning(f"跳过同步 {draft_id}: 反序列化失败: {e}")
                    version_key = self._get_version_key(draft_id)
                    await redis.delete(cache_key, version_key, dirty_key)
                    return (draft_id, "skipped", "deserialize_failed")

                # 获取当前版本号
                current_version = None
                try:
                    result = await self.pg_storage.get_draft_with_version(draft_id)
                    if result:
                        _, current_version = result
                except Exception as e:
                    logger.warning(f"获取版本号失败 {draft_id}: {e}")

                # 同步到 PostgreSQL
                success = await self.pg_storage.save_draft(
                    draft_id,
                    script_obj,
                    expected_version=current_version,
                    create_version=True,
                )

                if success:
                    version_key = self._get_version_key(draft_id)
                    fail_count_key = self._get_dirty_fail_count_key(draft_id)
                    await redis.delete(version_key, dirty_key, fail_count_key)
                    logger.debug(f"同步草稿到PostgreSQL成功: {draft_id}")
                    return (draft_id, "synced", "success")
                else:
                    logger.warning(f"同步草稿失败（版本冲突）: {draft_id}")
                    version_key = self._get_version_key(draft_id)
                    await redis.delete(cache_key, version_key, dirty_key)
                    return (draft_id, "failed", "version_conflict")

            except Exception as e:
                is_retryable = self._is_retryable_error(e)

                if is_retryable and retry_count < max_retries:
                    retry_count += 1
                    draft_id_str = draft_id or "unknown"
                    logger.warning(
                        f"同步重试 {retry_count}/{max_retries} {draft_id_str}: {e}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    draft_id_str = draft_id or "unknown"
                    reason = (
                        "retry_exhausted"
                        if retry_count >= max_retries
                        else "permanent_error"
                    )
                    logger.error(f"同步草稿失败 {draft_id_str}: {e}", exc_info=True)

                    # 处理失败计数
                    if draft_id:
                        try:
                            cache_key = self._get_cache_key(draft_id)
                            version_key = self._get_version_key(draft_id)
                            fail_count_key = self._get_dirty_fail_count_key(draft_id)

                            fail_count = await redis.incr(fail_count_key)
                            if fail_count == 1:
                                await redis.expire(fail_count_key, DRAFT_CACHE_TTL * 2)

                            if fail_count >= MAX_DIRTY_FAIL_COUNT:
                                logger.error(
                                    f"脏数据同步失败次数超过阈值，彻底删除: {draft_id_str}"
                                )
                                await redis.delete(
                                    cache_key, version_key, dirty_key, fail_count_key
                                )
                            else:
                                await redis.delete(cache_key, version_key)
                                logger.warning(
                                    f"已回滚 Redis 缓存（失败次数: {fail_count}/{MAX_DIRTY_FAIL_COUNT}）: {draft_id_str}"
                                )
                        except Exception as rollback_error:
                            logger.error(
                                f"回滚 Redis 缓存失败: {draft_id_str}, error={rollback_error}"
                            )

                    return (draft_id_str, "failed", reason)

            finally:
                # 释放同步锁
                if draft_id and lock_acquired and lock_key:
                    try:
                        lock_key_bytes = (
                            lock_key.encode("utf-8")
                            if isinstance(lock_key, str)
                            else lock_key
                        )
                        await redis.delete(lock_key_bytes)
                    except Exception as e:
                        logger.warning(f"释放同步锁失败: {e}")

        return (draft_id or "unknown", "failed", "unknown_error")

    async def _sync_to_postgres(self):
        """后台同步任务：将脏数据同步到PostgreSQL"""
        try:
            redis = await self._ensure_redis_client()
            pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            pattern_bytes = pattern.encode("utf-8")
            dirty_keys = []
            cursor = 0
            scan_count = 0
            max_scan_iterations = 1000

            while scan_count < max_scan_iterations:
                try:
                    cursor, keys = await redis.scan(
                        cursor, match=pattern_bytes, count=100
                    )
                    dirty_keys.extend(keys)
                    scan_count += 1
                    if cursor == 0:
                        break
                except Exception as e:
                    logger.error(f"SCAN操作失败: {e}", exc_info=True)
                    break

            if not dirty_keys:
                logger.debug("后台同步任务执行：当前没有脏数据需要同步")
                return

            logger.info(f"开始执行后台同步任务：扫描到 {len(dirty_keys)} 个脏数据标记")

            total_count = len(dirty_keys)
            if total_count > self.max_sync_batch_size:
                dirty_keys = dirty_keys[: self.max_sync_batch_size]
                logger.info(
                    f"脏数据数量超过限制，本次只同步前 {self.max_sync_batch_size} 条"
                )

            # 使用 asyncio 并发处理
            synced_count = 0
            failed_count = 0
            skipped_count = 0

            # 创建信号量限制并发数
            semaphore = asyncio.Semaphore(self.max_sync_workers)

            async def sync_with_semaphore(dirty_key):
                async with semaphore:
                    return await self._sync_single_draft(dirty_key)

            tasks = [sync_with_semaphore(dk) for dk in dirty_keys]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    failed_count += 1
                    logger.error(f"同步任务异常: {result}")
                else:
                    _, status, _ = result
                    if status == "synced":
                        synced_count += 1
                    elif status == "failed":
                        failed_count += 1
                    else:
                        skipped_count += 1

            logger.info(
                f"同步完成: {synced_count} 成功, {failed_count} 失败, {skipped_count} 跳过"
            )

        except Exception as e:
            logger.error(f"后台同步任务失败: {e}", exc_info=True)

    async def start_sync_task(self):
        """启动后台同步任务"""
        if not self.enable_sync:
            return

        if self._sync_task is not None and not self._sync_task.done():
            logger.info("后台同步任务已在运行，跳过重复启动")
            return

        async def sync_loop():
            logger.info(f"后台同步任务已启动，同步间隔: {SYNC_INTERVAL} 秒")
            # 启动时立即执行一次
            if not self._stop_sync:
                await self._sync_to_postgres()

            while not self._stop_sync:
                try:
                    await asyncio.sleep(SYNC_INTERVAL)
                    if not self._stop_sync:
                        await self._sync_to_postgres()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"同步任务异常: {e}")

        self._stop_sync = False
        self._sync_task = asyncio.create_task(sync_loop())

    async def stop_sync_task(self):
        """停止后台同步任务"""
        self._stop_sync = True
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            finally:
                self._sync_task = None
        logger.info("后台同步任务已停止")

    async def exists(self, draft_id: str) -> bool:
        """检查草稿是否存在"""
        redis = await self._ensure_redis_client()
        cache_key = self._get_cache_key(draft_id)

        try:
            if await redis.exists(cache_key):
                return True
        except Exception as e:
            logger.warning(f"Redis检查失败: {e}")

        try:
            return await self.pg_storage.exists(draft_id)
        except Exception as e:
            logger.error(f"PostgreSQL检查失败: {e}")
            return False

    async def delete_draft(self, draft_id: str) -> bool:
        """删除草稿"""
        redis = await self._ensure_redis_client()
        cache_key = self._get_cache_key(draft_id)
        dirty_key = self._get_dirty_key(draft_id)
        version_key = self._get_version_key(draft_id)
        fail_count_key = self._get_dirty_fail_count_key(draft_id)

        try:
            await redis.delete(cache_key, version_key, dirty_key, fail_count_key)
        except Exception as e:
            logger.warning(f"Redis删除失败: {e}")

        try:
            return await self.pg_storage.delete_draft(draft_id)
        except Exception as e:
            logger.error(f"PostgreSQL删除失败: {e}")
            return False

    async def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        stats = {
            "redis_available": True,
            "cache_ttl_seconds": DRAFT_CACHE_TTL,
            "sync_interval_seconds": SYNC_INTERVAL,
            "max_sync_batch_size": self.max_sync_batch_size,
            "max_sync_workers": self.max_sync_workers,
            "backend": "redis.asyncio",
        }

        try:
            redis = await self._ensure_redis_client()

            # 统计缓存数量
            pattern = f"{DRAFT_CACHE_KEY_PREFIX}*"
            cache_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=pattern.encode(), count=100
                )
                cache_keys.extend(keys)
                if cursor == 0:
                    break
            stats["redis_cache_count"] = len(cache_keys)

            # 统计脏数据数量
            dirty_pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            dirty_keys = []
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=dirty_pattern.encode(), count=100
                )
                dirty_keys.extend(keys)
                if cursor == 0:
                    break
            stats["dirty_count"] = len(dirty_keys)
        except Exception as e:
            logger.warning(f"获取Redis统计失败: {e}")
            stats["redis_available"] = False

        # PostgreSQL统计
        try:
            pg_stats = await self.pg_storage.get_stats()
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

    try:
        _redis_cache = RedisDraftCache()
        return _redis_cache
    except ImportError as e:
        logger.warning(f"redis.asyncio包未安装，Redis缓存不可用: {e}")
        return None
    except Exception as e:
        logger.warning(f"Redis缓存初始化失败: {e}，将降级到PostgreSQL")
        return None


async def init_redis_draft_cache() -> Optional[RedisDraftCache]:
    """
    初始化Redis缓存实例（用于FastAPI生命周期管理）
    """
    cache = get_redis_draft_cache()
    if cache:
        await cache._ensure_redis_client()
        await cache.start_sync_task()
    return cache


async def shutdown_redis_draft_cache() -> None:
    """
    关闭Redis缓存实例（用于FastAPI生命周期管理）
    """
    global _redis_cache

    if _redis_cache is not None:
        try:
            await _redis_cache.stop_sync_task()
            if _redis_cache.redis_client:
                await _redis_cache.redis_client.close()
            logger.info("Redis缓存已关闭")
        except Exception as e:
            logger.error(f"关闭Redis缓存失败: {e}")
