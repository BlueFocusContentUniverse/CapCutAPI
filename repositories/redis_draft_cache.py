#!/usr/bin/env python3
"""
Redis草稿缓存层（读取侧基于dogpile.cache，写入侧使用Redis客户端保证事务完整性）
- add: dogpile.cache 的本地内存缓存：关闭，避免持有 ScriptFile 对象的引用导致内存泄漏
- L1缓存：Redis（10分钟TTL）
- L2持久化：PostgreSQL
- 写入策略：Write-Through + Write-Behind
"""

import json
import logging
import pickle
import threading
import time
import os
import pyJianYingDraft as draft
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from dogpile.cache import make_region
from repositories.draft_repository import PostgresDraftStorage, get_postgres_storage

logger = logging.getLogger(__name__)
# 确保日志级别为 INFO
if logger.level == logging.NOTSET:
    logger.setLevel(logging.INFO)

# Redis配置
DRAFT_CACHE_TTL = 600  # 10分钟
DRAFT_CACHE_KEY_PREFIX = "draft:cache:"
DRAFT_DIRTY_KEY_PREFIX = "draft:dirty:"
SYNC_INTERVAL = 60  # 同步间隔（秒）
MAX_SYNC_BATCH_SIZE = 1000  # 单次同步的最大脏数据数量（避免单次同步时间过长）
MAX_SYNC_WORKERS = (
    5  # 并发同步的线程数（默认5，不超过数据库连接池的50%，避免影响主业务）
)


class RedisDraftCache:
    """Redis草稿缓存层"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        pg_storage: Optional[PostgresDraftStorage] = None,
        enable_sync: bool = True,
        max_sync_batch_size: int = MAX_SYNC_BATCH_SIZE,
        max_sync_workers: int = MAX_SYNC_WORKERS,
    ):
        """
        初始化Redis缓存层

        Args:
            redis_url: Redis连接URL，格式: redis://[:password]@host:port/db
            pg_storage: PostgreSQL存储实例
            enable_sync: 是否启用后台同步任务
            max_sync_batch_size: 单次同步的最大脏数据数量（默认1000）
            max_sync_workers: 并发同步的线程数（默认5，建议不超过数据库连接池的50%）
        """
        self.pg_storage = pg_storage or get_postgres_storage()
        self.enable_sync = enable_sync
        self._sync_thread = None
        self._stop_sync = False
        self.max_sync_batch_size = max_sync_batch_size
        self.max_sync_workers = max_sync_workers

        # 从环境变量读取 Redis URL
        redis_url = redis_url or os.getenv("DRAFT_CACHE_REDIS_URL")
        if not redis_url:
            raise ValueError("Redis URL 未配置，请设置环境变量 DRAFT_CACHE_REDIS_URL")
        redis_config = self._parse_redis_url(redis_url)

        # 创建dogpile.cache region
        # key_mangler 直接返回原 key（不添加前缀）
        # 配置说明：
        # 1. 使用 dogpile.cache.redis 后端，数据只存储在Redis中
        # 2. 禁用本地内存缓存（local_cache=None），避免 dogpile 持有 ScriptFile 对象的引用
        #    这样所有请求都直接从 Redis 读取 bytes，反序列化后对象可以被 GC 回收
        # 3. 配置 distributed_lock=True 启用分布式锁，防止缓存击穿（不受本地缓存影响）
        # 4. 配置 redis_expiration_time 确保Redis中的键有过期时间
        self.cache_region = make_region(
            key_mangler=lambda key: key,
            function_key_generator=None,  # 使用默认的 key 生成器
        ).configure(
            "dogpile.cache.redis",
            arguments={
                "host": redis_config["host"],
                "port": redis_config["port"],
                "db": redis_config["db"],
                "password": redis_config.get("password"),
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "decode_responses": False,  # 使用bytes模式（pickle需要）
                "redis_expiration_time": DRAFT_CACHE_TTL,  # Redis中的键过期时间
                "distributed_lock": True,  # 启用分布式锁，防止缓存击穿
                "thread_local_lock": False,  # 当 distributed_lock=True 时，必须设置为 False
            },
            expiration_time=DRAFT_CACHE_TTL,  # dogpile.cache的过期时间，用于锁机制
        )
        # 禁用本地内存缓存，避免持有 ScriptFile 对象的引用导致内存泄漏
        # 这样所有请求都直接从 Redis 读取 bytes，反序列化后对象可以被 GC 回收
        self.cache_region.backend.local_cache = None

        # 创建Redis客户端用于脏数据标记和统计
        try:
            import redis

            self.redis_client = redis.Redis(
                host=redis_config["host"],
                port=redis_config["port"],
                db=redis_config["db"],
                password=redis_config.get("password"),
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5,
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
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 6379,
            "db": int(parsed.path.lstrip("/")) if parsed.path else 0,
        }
        if parsed.password:
            config["password"] = parsed.password
        return config

    def _get_cache_key(self, draft_id: str) -> str:
        """
        生成完整缓存key（直接带前缀，无需后续拼接）
        """
        return f"{DRAFT_CACHE_KEY_PREFIX}{draft_id}"

    def _get_dirty_key(self, draft_id: str) -> str:
        """
        生成脏数据标记key（字符串格式，Redis客户端自动编码）

        统一使用字符串格式，Redis客户端在 decode_responses=False 时会自动编码为 bytes
        """
        return f"{DRAFT_DIRTY_KEY_PREFIX}{draft_id}"

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
            "v": 2,  # dogpile.cache 的版本号
        }
        metadata_json = json.dumps(metadata).encode("utf-8")
        return metadata_json + b"|" + data

    def _deserialize_cached_data(
        self, cached_data: Any, draft_id: str
    ) -> Optional[draft.ScriptFile]:
        """
        反序列化缓存数据（健壮性优化）

        Args:
            cached_data: 从 dogpile.cache 获取的数据
                - 通常是 ScriptFile 对象（dogpile.cache.redis 后端自动反序列化）
                - 也可能是 bytes（异常情况，兼容处理）
            draft_id: 草稿ID（用于日志）

        Returns:
            ScriptFile 对象，如果反序列化失败则返回 None

        注意：由于已禁用 dogpile.cache 的本地内存缓存（local_cache=None），
        每次调用都直接从 Redis 读取 bytes 并反序列化，返回的是新对象，可以被 GC 回收。
        因此，如果是 ScriptFile 对象，可以直接返回，无需重新序列化/反序列化。
        """
        # 如果已经是 ScriptFile 对象，直接返回
        # 由于已禁用本地缓存，每次都是从 Redis 读取并反序列化的新对象，不会有内存泄漏问题
        if isinstance(cached_data, draft.ScriptFile):
            return cached_data

        # 如果是 bytes，需要反序列化
        if isinstance(cached_data, bytes):
            try:
                # 检查是否包含 dogpile.cache 格式的元数据分隔符
                if b"|" in cached_data:
                    # 按第一个 "|" 分割（避免数据中含 "|" 导致分割错误）
                    metadata_json, pickled_data = cached_data.split(b"|", 1)
                    # 验证元数据格式（可选，无效则抛出异常）
                    try:
                        json.loads(metadata_json.decode("utf-8"))
                    except json.JSONDecodeError as e:
                        logger.warning(f"缓存元数据格式错误 {draft_id}: {e}")
                        return None
                    # 反序列化实际的 pickle 数据
                    return pickle.loads(pickled_data)
                else:
                    # 兼容旧数据（无元数据，直接是 pickle 数据）
                    return pickle.loads(cached_data)
            except pickle.UnpicklingError as e:
                logger.warning(f"pickle 反序列化失败 {draft_id}: {e}")
                return None
            except Exception as e:
                logger.warning(f"反序列化失败 {draft_id}: {e}")
                return None

        # 其他类型不支持
        logger.warning(
            f"不支持的缓存数据类型: {type(cached_data)}, draft_id: {draft_id}"
        )
        return None

    def get_draft(self, draft_id: str) -> Optional[draft.ScriptFile]:
        """
        获取草稿（Read-Through策略）

        1. 先查Redis（dogpile.cache自动处理缓存击穿）
        2. 未命中则查PostgreSQL并写入Redis
        3. 命中后自动刷新TTL

        注意：反序列化后的 ScriptFile 对象很大，会在Python内存中存在直到被垃圾回收
        为了减少内存占用，我们确保只返回必要的对象，不保留额外的引用
        """
        cache_key = self._get_cache_key(draft_id)

        try:
            # 使用dogpile.cache的get_or_create，自动处理缓存击穿
            # 注意：dogpile.cache.redis 后端会自动序列化/反序列化
            # 所以 _get_from_pg 应该返回 ScriptFile 对象，而不是 bytes
            def _get_from_pg() -> Optional[draft.ScriptFile]:
                """从PostgreSQL获取草稿对象"""
                script_obj = self.pg_storage.get_draft(draft_id)
                # dogpile.cache 会自动序列化这个对象并存储到 Redis
                # 读取时会自动反序列化，返回 ScriptFile 对象
                return script_obj

            # 使用get_or_create，自动处理缓存击穿和并发
            # dogpile.cache.redis 后端会自动序列化/反序列化
            # 所以 cached_data 可能是 ScriptFile 对象（如果来自缓存）或 None
            cached_data = self.cache_region.get_or_create(
                cache_key, _get_from_pg, expiration_time=DRAFT_CACHE_TTL
            )

            if cached_data:
                # dogpile.cache.redis 后端会自动反序列化，返回 ScriptFile 对象
                # 但为了避免内存泄漏，我们需要确保每次都是新对象
                script_obj = self._deserialize_cached_data(cached_data, draft_id)
                # 清除 cached_data 引用，帮助垃圾回收
                del cached_data
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

    def get_draft_with_version(
        self, draft_id: str
    ) -> Optional[Tuple[draft.ScriptFile, int]]:
        """获取草稿及版本号（草稿从 Redis，版本号从 PG）"""
        script_obj = self.get_draft(draft_id)
        if script_obj is None:
            return None

        # 从PostgreSQL获取版本号（版本号只在PG中维护）
        try:
            result = self.pg_storage.get_draft_with_version(draft_id)
            if result:
                _, version = result  # 只取版本号
                return (script_obj, version)  # 返回 Redis 草稿 + PG 版本号
        except Exception as e:
            logger.warning(f"获取版本号失败: {e}")

        # 降级：检查PostgreSQL中是否存在草稿
        # 如果不存在，返回版本0（表示新草稿，尚未创建）
        # 如果存在但获取版本号失败，返回版本1（保守估计）
        try:
            if not self.pg_storage.exists(draft_id):
                logger.debug(
                    f"草稿 {draft_id} 在PostgreSQL中不存在，返回版本0（新草稿）"
                )
                return (script_obj, 0)
        except Exception as e:
            logger.warning(f"检查草稿是否存在失败: {e}")

        # 如果无法确定，返回版本1（保守估计，避免版本冲突）
        return (script_obj, 1)

    def _is_retryable_error(self, error: Exception) -> bool:
        """
        判断错误是否为临时性错误（可重试）

        Args:
            error: 异常对象

        Returns:
            True 如果是临时性错误（可重试），False 如果是永久性错误（不应重试）
        """
        error_type = type(error).__name__
        error_str = str(error).lower()

        # 临时性错误（可重试）
        retryable_errors = (
            "ConnectionError",
            "TimeoutError",
            "OperationalError",
            "InterfaceError",
            "DisconnectionError",
            "OSError",
        )

        # 检查异常类型
        if any(retryable in error_type for retryable in retryable_errors):
            return True

        # 检查 Redis 相关异常
        try:
            import redis

            if isinstance(
                error,
                (redis.ConnectionError, redis.TimeoutError, redis.BusyLoadingError),
            ):
                return True
        except ImportError:
            pass

        # 检查 SQLAlchemy 相关异常
        try:
            from sqlalchemy.exc import (
                DisconnectionError,
                InterfaceError,
                OperationalError,
            )

            if isinstance(
                error, (OperationalError, InterfaceError, DisconnectionError)
            ):
                return True
        except ImportError:
            pass

        # 检查错误消息中的关键词
        retryable_keywords = (
            "connection",
            "timeout",
            "network",
            "temporary",
            "retry",
            "lock wait",
            "deadlock",
        )
        if any(keyword in error_str for keyword in retryable_keywords):
            return True

        # 其他错误视为永久性错误（不重试）
        return False

    def save_draft(
        self,
        draft_id: str,
        script_obj: draft.ScriptFile,
        expected_version: Optional[int] = None,
        mark_dirty: bool = True,
    ) -> bool:
        """
        保存草稿（Write-Through + Write-Behind策略）

        1. 使用Redis事务原子性地写入缓存和脏数据标记
        2. 如果提供了expected_version，立即同步到PG（保证一致性）
        3. 否则后台任务定期同步到PostgreSQL

        注意：写入时绕过dogpile.cache，直接使用Redis客户端以保证事务原子性
        """
        try:
            logger.info(f"save_draft 被调用: draft_id={draft_id}, mark_dirty={mark_dirty}, expected_version={expected_version}")
            # 获取完整缓存key（字符串格式，Redis客户端会自动编码为bytes）
            cache_key = self._get_cache_key(draft_id)

            # 序列化数据：先pickle，然后模拟dogpile.cache的格式
            # 这样读取时可以使用dogpile.cache的get()，衔接dogpile.cache的防缓存击穿功能
            pickled_data = pickle.dumps(script_obj)
            serialized_data = self._serialize_for_dogpile(pickled_data)

            # 1. 使用Redis事务原子性地写入缓存和脏数据标记（绕过dogpile.cache的set()方法，直接使用Redis客户端以保证事务原子性）
            # 但使用dogpile.cache的序列化格式，确保读取时可以使用dogpile.cache的get()
            # pipeline(transaction=True) 会自动使用 MULTI/EXEC 保证原子性
            pipe = self.redis_client.pipeline(transaction=True)

            # 操作1：写入缓存（直接使用Redis，但使用dogpile.cache的序列化格式）
            # Redis客户端会自动将字符串key编码为bytes（因为decode_responses=False）
            pipe.setex(cache_key, DRAFT_CACHE_TTL, serialized_data)
            logger.debug(f"Pipeline 添加缓存写入: cache_key={cache_key}")

            # 操作2：标记为脏数据（如果需要）
            dirty_key = None
            if mark_dirty:
                dirty_key = self._get_dirty_key(draft_id)
                # 确保 key 格式正确（字符串会被 Redis 客户端自动编码为 bytes）
                pipe.setex(dirty_key, DRAFT_CACHE_TTL * 2, b"1")
                logger.info(f"Pipeline 添加脏数据标记: dirty_key={dirty_key}, TTL={DRAFT_CACHE_TTL * 2}")
            else:
                logger.warning(f"警告: 保存草稿 {draft_id} 时 mark_dirty=False，不会标记为脏数据")

            # 执行事务（保证原子性：所有命令一起执行）
            try:
                logger.debug(f"执行 Redis 事务: draft_id={draft_id}, 命令数量={len(pipe.command_stack) if hasattr(pipe, 'command_stack') else 'unknown'}")
                results = pipe.execute()
                logger.info(f"Redis 事务执行完成: draft_id={draft_id}, results={results}, mark_dirty={mark_dirty}")
                # 检查结果（Redis事务不保证回滚，需要检查返回值）
                # results 是一个列表，每个元素对应一个命令的执行结果
                if not results or not all(results):
                    logger.error(
                        f"Redis事务执行部分失败: {draft_id}, results: {results}, mark_dirty={mark_dirty}, dirty_key={dirty_key}"
                    )
                    return False
                # 验证脏数据标记是否成功设置
                if mark_dirty and dirty_key:
                    # 检查脏数据标记是否真的存在
                    # Redis 客户端在 decode_responses=False 时需要 bytes，但字符串会自动编码
                    # 为了确保兼容性，统一转换为 bytes
                    dirty_key_bytes = dirty_key.encode('utf-8') if isinstance(dirty_key, str) else dirty_key
                    # 等待一小段时间，确保 Redis 事务完全提交
                    import time
                    time.sleep(0.01)  # 10ms 延迟
                    exists = self.redis_client.exists(dirty_key_bytes)
                    ttl = self.redis_client.ttl(dirty_key_bytes)
                    if not exists:
                        logger.error(f"❌ 脏数据标记设置失败: {draft_id}, dirty_key={dirty_key}, dirty_key_bytes={dirty_key_bytes}, results={results}")
                        # 尝试手动设置一次
                        try:
                            self.redis_client.setex(dirty_key_bytes, DRAFT_CACHE_TTL * 2, b"1")
                            logger.info(f"手动设置脏数据标记成功: {draft_id}, dirty_key={dirty_key}")
                        except Exception as e2:
                            logger.error(f"手动设置脏数据标记也失败: {draft_id}, error={e2}")
                    else:
                        logger.info(f"✅ 脏数据标记设置成功: {draft_id}, dirty_key={dirty_key}, TTL={ttl}")
            except Exception as e:
                logger.error(f"Redis事务执行失败: {draft_id}: {e}", exc_info=True)
                return False

            # 2. 所有写入都使用 Write-Behind 策略，先写入 Redis，标记为脏数据
            #    后台任务定期同步到 PostgreSQL，这样可以减轻 PG 压力
            #    版本检查在后台同步时进行（_sync_single_draft 中会获取当前版本号并检查）
            logger.info(
                f"草稿已写入Redis缓存: {draft_id}，"
                f"标记为脏数据，等待后台同步到PostgreSQL"
            )
            return True

        except Exception as e:
            logger.error(f"保存草稿失败: {draft_id}: {e}")
            return False

    def _sync_single_draft(self, dirty_key: bytes) -> Tuple[str, str]:
        """
        同步单个草稿到PostgreSQL（带重试机制）

        Args:
            dirty_key: 脏数据标记key（bytes格式）

        Returns:
            (draft_id, result) 元组，result为 'synced' | 'failed' | 'skipped'
        """
        draft_id = None
        max_retries = 2  # 最多重试2次（共3次尝试）
        retry_count = 0

        while retry_count <= max_retries:
            try:
                # 检查脏数据标记是否仍然存在（可能已被立即同步清除）
                if not self.redis_client.exists(dirty_key):
                    draft_id_str = dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "") if draft_id is None else draft_id
                    logger.debug(f"跳过同步 {draft_id_str}: 脏数据标记已不存在（可能已被其他线程清除）")
                    return (draft_id_str, "skipped")

                # 提取draft_id（dirty_key 从 SCAN 返回的是 bytes，需要解码）
                draft_id = dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "")
                cache_key = self._get_cache_key(draft_id)

                # 获取缓存数据
                try:
                    cached_data = self.cache_region.get(cache_key)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
                    # 数据格式错误（永久性错误，不重试）
                    # 漏洞 3 修复：清理 Redis 缓存和 dogpile 缓存
                    logger.error(f"缓存数据格式错误 {draft_id}: {e}，清除缓存和脏标记并跳过")
                    try:
                        self.cache_region.delete(cache_key)
                        self.redis_client.delete(dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped")

                if not cached_data:
                    # 缓存已过期，清除脏数据标记（永久性错误，不重试）
                    # 漏洞 3 修复：清理 Redis 缓存和 dogpile 缓存
                    logger.warning(f"跳过同步 {draft_id}: 缓存已过期（TTL到期）")
                    try:
                        self.cache_region.delete(cache_key)
                        self.redis_client.delete(dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped")

                # 反序列化缓存数据
                script_obj = self._deserialize_cached_data(cached_data, draft_id)
                if not script_obj:
                    # 反序列化失败（永久性错误，不重试）
                    # 漏洞 3 修复：清理 Redis 缓存和 dogpile 缓存
                    logger.warning(f"跳过同步 {draft_id}: 反序列化失败")
                    try:
                        self.cache_region.delete(cache_key)
                        self.redis_client.delete(dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped")

                # 获取当前版本号（用于乐观锁，从PostgreSQL获取）
                current_version = None
                try:
                    result = self.pg_storage.get_draft_with_version(draft_id)
                    if result:
                        _, current_version = result
                except Exception as e:
                    logger.warning(f"获取版本号失败 {draft_id}: {e}")
                    # 获取版本号失败可能是临时性错误，继续尝试同步

                # 同步到PostgreSQL（持久化操作，创建版本记录）
                success = self.pg_storage.save_draft(
                    draft_id,
                    script_obj,
                    expected_version=current_version,
                    create_version=True,  # 持久化时创建版本记录
                )

                if success:
                    # 清除脏数据标记
                    self.redis_client.delete(dirty_key)
                    logger.debug(f"同步草稿到PostgreSQL: {draft_id}（已创建版本记录）")
                    return (draft_id, "synced")
                else:
                    # 同步失败（版本冲突等永久性错误，不重试）
                    # 漏洞 2 修复：PG 写失败时，回滚 Redis 缓存，避免脏数据
                    logger.warning(
                        f"同步草稿失败（可能是版本冲突）: {draft_id}, "
                        f"current_version={current_version}，回滚 Redis 缓存"
                    )
                    try:
                        # 删除 Redis 缓存（回滚）
                        self.cache_region.delete(cache_key)
                        # 删除脏数据标记
                        self.redis_client.delete(dirty_key)
                        logger.info(f"已回滚 Redis 缓存: {draft_id}")
                    except Exception as e:
                        logger.error(f"回滚 Redis 缓存失败: {draft_id}, error={e}")
                    return (draft_id, "failed")

            except Exception as e:
                # 判断是否为临时性错误（可重试）
                is_retryable = self._is_retryable_error(e)

                if is_retryable and retry_count < max_retries:
                    retry_count += 1
                    draft_id_str = draft_id or "unknown"
                    logger.warning(
                        f"同步重试 {retry_count}/{max_retries} {draft_id_str}: {e}"
                    )
                    time.sleep(0.5)  # 重试间隔0.5秒，避免频繁重试
                else:
                    # 永久性错误或重试次数用尽
                    draft_id_str = draft_id or "unknown"
                    if retry_count >= max_retries:
                        logger.error(
                            f"同步草稿失败（重试用尽，已重试 {max_retries} 次） {draft_id_str}: {e}",
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            f"同步草稿失败（永久性错误，不重试） {draft_id_str}: {e}",
                            exc_info=True,
                        )
                    # 漏洞 2 修复：PG 写失败时，回滚 Redis 缓存，避免脏数据
                    # 漏洞 3 修复：清理 Redis 缓存和 dogpile 缓存（虽然已禁用本地缓存，但为了完整性）
                    try:
                        if draft_id:
                            cache_key = self._get_cache_key(draft_id)
                            # 删除 Redis 缓存（回滚）
                            self.cache_region.delete(cache_key)
                            # 删除脏数据标记
                            if dirty_key:
                                self.redis_client.delete(dirty_key)
                            logger.info(f"已回滚 Redis 缓存（永久性错误）: {draft_id_str}")
                    except Exception as rollback_error:
                        logger.error(f"回滚 Redis 缓存失败: {draft_id_str}, error={rollback_error}")
                    return (draft_id_str, "failed")

        # 理论上不会到达这里
        return (draft_id or "unknown", "failed")

    def _sync_to_postgres(self):
        """后台同步任务：将脏数据同步到PostgreSQL（支持批量限制和并发处理）"""
        try:
            logger.info("开始执行后台同步任务：扫描脏数据标记...")
            # 使用SCAN代替KEYS，避免阻塞Redis
            pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            pattern_bytes = pattern.encode('utf-8')
            logger.debug(f"扫描模式: {pattern}, pattern_bytes: {pattern_bytes}")
            dirty_keys = []
            cursor = 0
            scan_count = 0
            max_scan_iterations = 1000  # 防止无限循环

            while scan_count < max_scan_iterations:
                try:
                    cursor, keys = self.redis_client.scan(
                        cursor, match=pattern_bytes, count=100
                    )
                    logger.debug(f"SCAN 迭代 {scan_count}: cursor={cursor}, 找到 {len(keys)} 个key")
                    dirty_keys.extend(keys)
                    scan_count += 1
                    if cursor == 0:
                        break
                except Exception as e:
                    logger.error(f"SCAN操作失败: {e}", exc_info=True)
                    break

            logger.info(f"扫描完成: 找到 {len(dirty_keys)} 个脏数据标记")
            if dirty_keys:
                logger.info(f"脏数据标记列表: {[k.decode('utf-8') if isinstance(k, bytes) else k for k in dirty_keys[:5]]}")

            if not dirty_keys:
                # 即使没有脏数据，也输出一条 INFO 日志，表示同步任务正常运行
                logger.info("后台同步任务执行：当前没有脏数据需要同步")
                return

            # 方案A: 限制单次同步数量（避免单次同步时间过长）
            total_count = len(dirty_keys)
            if total_count > self.max_sync_batch_size:
                dirty_keys = dirty_keys[: self.max_sync_batch_size]
                logger.info(
                    f"脏数据数量 ({total_count}) 超过单次同步限制 ({self.max_sync_batch_size})，本次只同步前 {self.max_sync_batch_size} 条"
                )

            logger.info(
                f"开始同步 {len(dirty_keys)} 个脏数据到PostgreSQL（并发数: {self.max_sync_workers}）"
            )

            # 方案B: 使用线程池并发处理
            synced_count = 0
            failed_count = 0
            skipped_count = 0
            # 统计失败和跳过的原因
            skip_reasons = {
                "dirty_key_not_exists": 0,  # 脏数据标记已不存在
                "cache_expired": 0,  # 缓存已过期
                "deserialize_failed": 0,  # 反序列化失败
                "data_format_error": 0,  # 数据格式错误
            }
            fail_reasons = {
                "version_conflict": 0,  # 版本冲突
                "retry_exhausted": 0,  # 重试用尽
                "permanent_error": 0,  # 永久性错误
                "exception": 0,  # 异常
            }

            with ThreadPoolExecutor(max_workers=self.max_sync_workers) as executor:
                # 提交所有任务
                future_to_key = {
                    executor.submit(self._sync_single_draft, dirty_key): dirty_key
                    for dirty_key in dirty_keys
                }

                # 收集结果
                for future in as_completed(future_to_key):
                    try:
                        draft_id, result = future.result()
                        if result == "synced":
                            synced_count += 1
                        elif result == "failed":
                            failed_count += 1
                            # 失败原因已在 _sync_single_draft 中记录到日志
                        elif result == "skipped":
                            skipped_count += 1
                            # 跳过原因已在 _sync_single_draft 中记录到日志
                    except Exception as e:
                        failed_count += 1
                        fail_reasons["exception"] += 1
                        dirty_key = future_to_key[future]
                        draft_id = (
                            dirty_key.decode("utf-8").replace(
                                DRAFT_DIRTY_KEY_PREFIX, ""
                            )
                            if isinstance(dirty_key, bytes)
                            else str(dirty_key)
                        )
                        logger.error(f"同步任务异常 {draft_id}: {e}", exc_info=True)

            # 无论是否有同步结果，都输出日志
            logger.info(
                f"同步完成: {synced_count} 成功, {failed_count} 失败, {skipped_count} 跳过, 共 {len(dirty_keys)} 个脏数据标记"
            )
            # 输出失败和跳过的详细信息（如果有）
            if failed_count > 0:
                logger.warning(
                    f"失败详情: 异常={fail_reasons.get('exception', 0)} "
                    f"(注意：版本冲突、重试用尽等详细原因请查看上面的 WARNING/ERROR 日志)"
                )
            if skipped_count > 0:
                logger.info(
                    f"跳过详情: 脏数据标记已不存在或缓存已过期 "
                    f"(这是正常的，可能因为并发同步或缓存TTL到期)"
                )
            if total_count > self.max_sync_batch_size:
                remaining = total_count - self.max_sync_batch_size
                logger.info(f"剩余 {remaining} 个脏数据将在下次同步时处理")

        except Exception as e:
            logger.error(f"后台同步任务失败: {e}", exc_info=True)

    def _start_sync_task(self):
        """启动后台同步任务"""

        def sync_loop():
            # 启动时立即执行一次同步检查
            logger.info(f"后台同步任务已启动，同步间隔: {SYNC_INTERVAL} 秒")
            if not self._stop_sync:
                self._sync_to_postgres()
            
            # 然后按间隔定期执行
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
            "max_sync_batch_size": self.max_sync_batch_size,
            "max_sync_workers": self.max_sync_workers,
            "backend": "dogpile.cache",
        }

        try:
            # 统计Redis中的缓存数量（使用SCAN）
            pattern = f"{DRAFT_CACHE_KEY_PREFIX}*"
            cache_keys = []
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(
                    cursor, match=pattern.encode(), count=100
                )
                cache_keys.extend(keys)
                if cursor == 0:
                    break
            stats["redis_cache_count"] = len(cache_keys)

            # 统计脏数据数量（使用SCAN）
            dirty_pattern = f"{DRAFT_DIRTY_KEY_PREFIX}*"
            dirty_keys = []
            cursor = 0
            while True:
                cursor, keys = self.redis_client.scan(
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

    try:
        _redis_cache = RedisDraftCache()
        return _redis_cache
    except ImportError as e:
        logger.warning(f"dogpile.cache包未安装，Redis缓存不可用: {e}")
        return None
    except Exception as e:
        logger.warning(f"Redis缓存初始化失败: {e}，将降级到PostgreSQL")
        return None


def init_redis_draft_cache() -> Optional[RedisDraftCache]:
    """
    初始化Redis缓存实例（用于FastAPI生命周期管理）

    如果Redis不可用，返回None（降级到PostgreSQL）
    如果已经初始化，返回现有实例
    """
    return get_redis_draft_cache()


def shutdown_redis_draft_cache() -> None:
    """
    关闭Redis缓存实例（用于FastAPI生命周期管理）

    停止后台同步任务，清理资源
    """
    global _redis_cache

    if _redis_cache is not None:
        try:
            _redis_cache.stop_sync_task()
            logger.info("Redis缓存后台同步任务已停止")
        except Exception as e:
            logger.error(f"停止Redis缓存后台同步任务失败: {e}")
        finally:
            # 注意：不重置 _redis_cache 为 None，因为可能还有请求在使用
            # 只是停止后台任务，实例本身保留以便后续使用
            pass
