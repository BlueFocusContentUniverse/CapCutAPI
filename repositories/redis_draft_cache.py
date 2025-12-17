#!/usr/bin/env python3
"""
Redis草稿缓存层（读取侧基于dogpile.cache，写入侧使用Redis客户端保证事务完整性）
- add: dogpile.cache 的本地内存缓存：关闭，避免持有 ScriptFile 对象的引用导致内存泄漏
- L1缓存：Redis（10分钟TTL）
- L2持久化：PostgreSQL
- 写入策略：Write-Through + Write-Behind
"""
import logging
import pickle
import threading
import time
import redis
import os
import sqlalchemy.exc
from sqlalchemy import exc as sa_exc
import pyJianYingDraft as draft

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional, Tuple
from dogpile.cache import make_region
from repositories.draft_repository import PostgresDraftStorage, get_postgres_storage

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 配置常量
DRAFT_CACHE_TTL = 600 # 10分钟
DRAFT_CACHE_KEY_PREFIX = "draft:cache:"
DRAFT_DIRTY_KEY_PREFIX = "draft:dirty:"  # 使用 Redis Set 记录待同步的 Key
DRAFT_DIRTY_FAIL_COUNT_PREFIX = "draft:dirty:fail:"  # 记录脏数据同步失败次数的 Key 前缀
SYNC_LOCK_PREFIX = "lock:sync:"  # 同步锁前缀，用于防止并发同步时的版本冲突
SYNC_LOCK_TTL = 30  # 同步锁过期时间（秒），应该足够覆盖一次同步操作的时间
MAX_DIRTY_FAIL_COUNT = 5  # 脏数据同步失败的最大次数，超过此次数后彻底删除（防止错误循环）
SYNC_INTERVAL = 60 
MAX_SYNC_BATCH_SIZE = 1000 # 单次同步的最大脏数据数量（避免单次同步时间过长）
MAX_SYNC_WORKERS = 5 # 并发同步的线程数（默认5，不超过数据库连接池的50%，避免影响主业务）
RETRYABLE_ERR_TYPES = (
    OSError, TimeoutError, ConnectionError,
    redis.ConnectionError, redis.TimeoutError, redis.BusyLoadingError,
    sa_exc.OperationalError, sa_exc.InterfaceError, sa_exc.DisconnectionError
)
RETRYABLE_KEYWORDS = (
    "connection", "timeout", "network", "temporary", 
    "retry", "lock wait", "deadlock"
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
        self._sync_thread = None
        self._stop_sync = False

        redis_url = redis_url or os.getenv("DRAFT_CACHE_REDIS_URL")
        if not redis_url:
            raise ValueError("Redis草稿缓存层未配置，请检查 DRAFT_CACHE_REDIS_URL 环境变量")

        # 1. 创建独立的 Redis 客户端（用于事务和脏数据标记）
        self.redis_client = redis.from_url(
            redis_url,
            decode_responses=False,
            socket_timeout=5,
            socket_connect_timeout=5,
        )

        # 2. 配置 dogpile.cache region (直接传入 URL)
        self.cache_region = make_region(
            key_mangler=lambda key: key,
            function_key_generator=None, # 使用默认的 key 生成器
        ).configure(
            "dogpile.cache.redis",
            arguments={
                "url": redis_url,  # 内部会自动调用解析器
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
                "decode_responses": False,
                "redis_expiration_time": DRAFT_CACHE_TTL,
                "distributed_lock": True,
                "thread_local_lock": False,
            },
            expiration_time=DRAFT_CACHE_TTL,
        )

        # 3. 强制禁用本地缓存（保持你原有的内存优化逻辑）
        self.cache_region.backend.local_cache = None

        # 4. 验证连接
        try:
            self.redis_client.ping()
            logger.info(f"Redis缓存连接成功: {redis_url}")
        except Exception as e:
            logger.error(f"Redis 连接验证失败: {e}")
            raise

        if enable_sync:
            self._start_sync_task()

    def _get_cache_key(self, draft_id: str) -> str:
        """
        生成完整缓存key（直接带前缀，无需后续拼接）
        """
        return f"{DRAFT_CACHE_KEY_PREFIX}{draft_id}"

    def _get_lock_key(self, draft_id: str) -> str:
        """
        生成分布式锁key（用于 dogpile.cache 的并发控制）
        """
        return f"draft:lock:{draft_id}"

    def _get_dirty_key(self, draft_id: str) -> str:
        """
        生成脏数据标记key（字符串格式，Redis客户端自动编码）

        统一使用字符串格式，Redis客户端在 decode_responses=False 时会自动编码为 bytes
        """
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

    def get_draft(self, draft_id: str) -> Optional[draft.ScriptFile]:
        """
        获取草稿（Read-Through策略）

        1. 使用 dogpile.cache 的分布式锁机制防止缓存击穿
        2. 数据直接从 redis_client 读取 pickle 字节流
        3. 未命中则查PostgreSQL并写入Redis
        """
        cache_key = self._get_cache_key(draft_id)
        lock_key = self._get_lock_key(draft_id)

        # 优化：缓存命中时避免获取分布式锁，减少网络往返和锁竞争
        cached_bytes = self.redis_client.get(cache_key)
        if cached_bytes:
            try:
                script_obj = pickle.loads(cached_bytes)
                if isinstance(script_obj, draft.ScriptFile):
                    logger.debug(f"从Redis缓存快速获取草稿: {draft_id}")
                    return script_obj
            except Exception as e:
                logger.debug(f"尝试走分布式锁流程获取草稿: {draft_id}, {e}")

        # 缓存未命中，进入分布式锁流程
        try:
            # 使用 dogpile.cache 的 get_or_create 作为分布式锁机制
            # 锁 key 只存一个简单的信号量（True），不存实际数据
            def _load_data_with_lock() -> bool:
                """
                在分布式锁保护下加载数据，返回 True 表示锁已获取
                这个函数在 get_or_create 的回调中被调用，确保只有一个进程能执行数据加载
                """
                try:
                    # 在锁保护下，检查 Redis 和 PG 
                    cached_bytes = self.redis_client.get(cache_key)
                    if cached_bytes:
                        logger.debug(f"从Redis缓存获取草稿（锁保护下）: {draft_id}")
                        return True
                    # 缓存未命中，从PostgreSQL加载
                    result = self.pg_storage.get_draft_with_version(draft_id)
                    if result:
                        script_obj, version = result
                        pickled_data = pickle.dumps(script_obj)
                        version_key = self._get_version_key(draft_id)
                        # 在锁保护下，同时写入数据和版本号
                        self.redis_client.setex(cache_key, DRAFT_CACHE_TTL, pickled_data)
                        self.redis_client.setex(version_key, DRAFT_CACHE_TTL, str(version).encode('utf-8'))
                        logger.debug(f"从PostgreSQL加载并写入Redis缓存（锁保护下）: {draft_id}, version={version}")
                    return True
                except Exception as e:
                    logger.error(f"加载数据过程中发生异常: {e}")
                    raise  # 务必 raise，让 dogpile 知道任务失败了
            
            # 使用 get_or_create 获取分布式锁（只存信号量 True）
            # 如果锁已存在，等待其他进程完成；如果不存在，调用 _load_data_with_lock 加载数据
            self.cache_region.get_or_create(
                lock_key, _load_data_with_lock, expiration_time=DRAFT_CACHE_TTL
            )
            # 锁释放后，从 redis_client 读取数据（此时数据应该已经加载完成）
            cached_bytes = self.redis_client.get(cache_key)
            if cached_bytes:
                try:
                    script_obj = pickle.loads(cached_bytes)
                    if isinstance(script_obj, draft.ScriptFile):
                        logger.debug(f"从Redis缓存获取草稿: {draft_id}")
                        return script_obj
                    else:
                        logger.warning(f"缓存数据格式错误: {draft_id}")
                except Exception as e:
                    logger.warning(f"反序列化失败 {draft_id}: {e}")

            # 如果 Redis 仍然没有数据（异常情况），降级到PostgreSQL
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
        """
        获取草稿及版本号（优先从 Redis 读取版本号，只有 Redis 没有时才去 PostgreSQL）
        """
        cache_key = self._get_cache_key(draft_id)
        version_key = self._get_version_key(draft_id)

        try:
            res = self.redis_client.mget([cache_key, version_key])
            cached_bytes, version_bytes = res[0], res[1]
        except Exception as e:
            logger.warning(f"Redis MGET 失败: {e}")
            cached_bytes, version_bytes = None, None

        # 如果两样都有，直接返回（最快路径）
        if cached_bytes and version_bytes:
            try:
                script_obj = pickle.loads(cached_bytes)
                version = int(version_bytes.decode('utf-8'))
                return (script_obj, version)
            except Exception as e:
                logger.debug(f"缓存解析失败，降级到锁流程: {e}")

        # 如果 Redis 没对齐，统一走 get_draft 的逻辑：分布式锁、回源 PG、回写 Redis（包含版本号）
        script_obj = self.get_draft(draft_id)
        if script_obj is None:
            return None
        v_data = self.redis_client.get(version_key)
        if v_data:
            try:
                version = int(v_data.decode('utf-8'))
                return (script_obj, version)
            except (ValueError, UnicodeDecodeError) as e:
                logger.warning(f"版本号格式错误 {draft_id}: {e}")

        # 极少数情况（如 Redis 写入失败），才从 PG 做最后的版本确认
        result = self.pg_storage.get_draft_with_version(draft_id)
        if result:
            _, version = result
            return (script_obj, version)

        # 最终兜底：新草稿返回版本 0
        return (script_obj, 0)

    def save_draft(
        self,
        draft_id: str,
        script_obj: draft.ScriptFile,
        expected_version: Optional[int] = None,
        mark_dirty: bool = True,
    ) -> bool:
        """
        保存草稿（Write-Through + Write-Behind策略）
        优化点：精简事务校验逻辑，移除阻塞式等待，增强异常处理
        
        重要说明（超高并发场景）：
        1. expected_version 来源：请确保 expected_version 是刚刚从 get_draft_with_version 中取出的最新值。
           如果传入的版本号过旧，save_draft 依然会写入 Redis（因为它信任传入的 expected_version）。
           真正的乐观锁校验发生在 _sync_single_draft 中，那里会查询 PostgreSQL 的当前版本进行最终校验。
        2. 设计理念：Redis 层负责快速写入，PostgreSQL 层负责最终一致性校验。
           这样可以提高写入性能，同时保证数据一致性。
        """
        try:
            logger.info(f"save_draft 被调用: draft_id={draft_id}, mark_dirty={mark_dirty}, expected_version={expected_version}")
            # 1. 预计算与序列化（放在事务外，减少事务占用时间）
            cache_key = self._get_cache_key(draft_id)
            version_key = self._get_version_key(draft_id)
            pickled_data = pickle.dumps(script_obj)
            
            # 版本号逻辑：
            # - 如果 mark_dirty=False（Read-Through场景），直接使用 expected_version（与PostgreSQL保持一致）
            # - 如果 mark_dirty=True（Write-Behind场景），新草稿设为1，修改则自增
            if not mark_dirty and expected_version is not None:
                # Read-Through场景：直接使用PostgreSQL的版本号，保持一致性
                version = expected_version
            else:
                # Write-Behind场景：新草稿设为1，修改则自增
                version = 1 if expected_version is None else (expected_version + 1)

            # 2. 开启 Redis 事务
            pipe = self.redis_client.pipeline(transaction=True)

            # 操作1：写入核心数据
            pipe.setex(cache_key, DRAFT_CACHE_TTL, pickled_data)

            # 操作2：写入独立版本号
            pipe.setex(version_key, DRAFT_CACHE_TTL, str(version).encode('utf-8'))
            
            # 操作3：原子化设置脏标记
            dirty_key = None
            if mark_dirty:
                dirty_key = self._get_dirty_key(draft_id)
                # 脏标记 TTL 建议设为缓存的两倍，防止同步任务未及时跑完
                pipe.setex(dirty_key, DRAFT_CACHE_TTL * 2, b"1")
            else:
                logger.warning(f"警告: 保存草稿 {draft_id} 时 mark_dirty=False，不会标记为脏数据")

            # 3. 提交事务
            # pipe.execute() 如果返回成功，代表命令已全部进入 Redis 内存，无需额外 exists 检查
            results = pipe.execute()
            
            # 超高并发环境下的健壮性检查：
            # 1. 检查 results 是否为空
            # 2. 检查 results 中是否有 False 或 None（表示命令失败）
            # 3. 检查 results 中是否有异常对象（复杂分布式环境下可能出现）
            if not results:
                logger.error(f"Redis 事务返回空结果: {draft_id}, mark_dirty={mark_dirty}")
                return False

            # 检查每个结果：排除 False、None 和异常对象
            for i, result in enumerate(results):
                if result is False or result is None:
                    logger.error(
                        f"Redis 事务命令 {i} 执行失败: {draft_id}, "
                        f"result={result}, results={results}, mark_dirty={mark_dirty}"
                    )
                    return False
                # 检查是否为异常对象（复杂分布式环境下可能出现）
                if isinstance(result, Exception):
                    logger.error(
                        f"Redis 事务命令 {i} 返回异常: {draft_id}, "
                        f"exception={result}, results={results}, mark_dirty={mark_dirty}",
                        exc_info=result
                    )
                    return False
            
            # 所有检查通过，事务执行成功
            logger.debug(f"成功存入 Redis 缓存并标记脏数据: {draft_id}, v={version}, dirty={mark_dirty}")
            return True

        except Exception as e:
            logger.error(f"save_draft 执行崩溃: {draft_id}, 错误: {e}", exc_info=True)
            return False

    def _is_retryable_error(self, error: Exception) -> bool:
        """
        判断错误是否为临时性错误（可重试）
        优化点：预加载异常类型映射，提升高频调用性能
        """
        # 1. 直接通过类型继承链判断 (最快且最准确)
        if isinstance(error, RETRYABLE_ERR_TYPES):
            return True

        # 2. 检查特定名称前缀（处理某些动态包装的异常）
        error_type_name = type(error).__name__
        if any(x in error_type_name for x in ("Connection", "Timeout", "Operational")):
            return True

        # 3. 检查错误消息内容关键词
        error_msg = str(error).lower()
        if any(kw in error_msg for kw in RETRYABLE_KEYWORDS):
            return True

        return False

    def _sync_single_draft(self, dirty_key: bytes) -> Tuple[str, str, str]:
        """
        同步单个草稿到PostgreSQL（带重试机制和分布式锁）

        Args:
            dirty_key: 脏数据标记key（bytes格式）

        Returns:
            (draft_id, result, reason) 元组
            - result: 'synced' | 'failed' | 'skipped'
            - reason: 具体原因（如 'dirty_key_not_exists', 'cache_expired', 'version_conflict', 'already_syncing' 等）
        """
        draft_id = None
        max_retries = 2  # 最多重试2次（共3次尝试）
        retry_count = 0
        lock_acquired = False
        lock_key = None

        while retry_count <= max_retries:
            try:
                # 检查脏数据标记是否仍然存在（可能已被立即同步清除）
                if not self.redis_client.exists(dirty_key):
                    draft_id_str = dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "") if draft_id is None else draft_id
                    logger.debug(f"跳过同步 {draft_id_str}: 脏数据标记已不存在（可能已被其他线程清除）")
                    return (draft_id_str, "skipped", "dirty_key_not_exists")

                # 提取draft_id（dirty_key 从 SCAN 返回的是 bytes，需要解码）
                draft_id = dirty_key.decode("utf-8").replace(DRAFT_DIRTY_KEY_PREFIX, "")
                
                # 优化：使用 Redis 分布式锁防止并发同步时的版本冲突
                # 原理：SCAN 扫出了 Key，但没有"锁定"这个 Key 的同步权
                #       使用 SET NX 确保同一 draft_id 只被一个线程处理，冲突率降为 0
                lock_key = self._get_sync_lock_key(draft_id)
                lock_key_bytes = lock_key.encode('utf-8') if isinstance(lock_key, str) else lock_key
                
                # 尝试获取锁，有效期 SYNC_LOCK_TTL 秒（防止 worker 挂掉导致死锁）
                # set(key, value, nx=True, ex=ttl) 等同于 SET key value NX EX ttl
                lock_acquired = self.redis_client.set(
                    lock_key_bytes,
                    b"1",
                    nx=True,
                    ex=SYNC_LOCK_TTL
                )
                
                if not lock_acquired:
                    # 锁已被其他线程获取，跳过本次同步
                    logger.debug(f"跳过同步 {draft_id}: 同步锁已被其他线程获取（并发保护）")
                    return (draft_id, "skipped", "already_syncing")
                
                # 获取锁成功，继续执行同步逻辑
                cache_key = self._get_cache_key(draft_id)

                # 从 redis_client 直接读取 pickle 数据
                try:
                    cached_bytes = self.redis_client.get(cache_key)
                except Exception as e:
                    # 数据格式错误（永久性错误，不重试）
                    logger.error(f"缓存读取错误 {draft_id}: {e}，清除缓存、版本号和脏标记并跳过")
                    try:
                        version_key = self._get_version_key(draft_id)
                        self.redis_client.delete(cache_key, version_key, dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped", "cache_read_error")

                if not cached_bytes:
                    # 缓存已过期，清除缓存、版本号和脏数据标记（永久性错误，不重试）
                    logger.warning(f"跳过同步 {draft_id}: 缓存已过期（TTL到期）")
                    try:
                        version_key = self._get_version_key(draft_id)
                        self.redis_client.delete(cache_key, version_key, dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped", "cache_expired")

                # 反序列化缓存数据（直接 pickle）
                try:
                    script_obj = pickle.loads(cached_bytes)
                    if not isinstance(script_obj, draft.ScriptFile):
                        logger.warning(f"跳过同步 {draft_id}: 缓存数据格式错误（不是 ScriptFile 对象）")
                        try:
                            version_key = self._get_version_key(draft_id)
                            self.redis_client.delete(cache_key, version_key, dirty_key)
                        except Exception as cleanup_error:
                            logger.error(f"清理缓存失败: {cleanup_error}")
                        return (draft_id, "skipped", "data_format_error")
                except Exception as e:
                    # 反序列化失败（永久性错误，不重试）
                    logger.warning(f"跳过同步 {draft_id}: 反序列化失败: {e}")
                    try:
                        version_key = self._get_version_key(draft_id)
                        self.redis_client.delete(cache_key, version_key, dirty_key)
                    except Exception as cleanup_error:
                        logger.error(f"清理缓存失败: {cleanup_error}")
                    return (draft_id, "skipped", "deserialize_failed")

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
                    # 优化：同步成功后，不尝试盲写版本号，而是直接删除版本号和缓存
                    # 强制让读取端去 PG 拿最准确的数据，彻底规避并发导致的"版本倒退"
                    # 原因：如果同步任务A正在将V1同步到PG，成功后准备写version=2到Redis
                    #       但在A写入之前，用户又瞬间保存了一次，将Redis里的版本号更新到了V3
                    #       此时同步任务A执行了setex(version_key, V2)，会导致版本号从V3倒退回V2
                    try:
                        version_key = self._get_version_key(draft_id)
                        fail_count_key = self._get_dirty_fail_count_key(draft_id)
                        # 删除版本号、脏数据标记和失败计数器，强制读取端从PG获取最权威的版本号
                        self.redis_client.delete(version_key, dirty_key, fail_count_key)
                        logger.debug(f"同步草稿到PostgreSQL成功，已清理Redis标记（强制从PG读取）: {draft_id}")
                    except Exception as e:
                        logger.warning(f"清理Redis标记失败 {draft_id}: {e}")
                    finally:
                        # 释放同步锁
                        if lock_acquired and lock_key:
                            try:
                                lock_key_bytes = lock_key.encode('utf-8') if isinstance(lock_key, str) else lock_key
                                self.redis_client.delete(lock_key_bytes)
                            except Exception as e:
                                logger.warning(f"释放同步锁失败 {draft_id}: {e}")
                    return (draft_id, "synced", "success")
                else:
                    # 同步失败（版本冲突等永久性错误，不重试）
                    # 漏洞 2 修复：PG 写失败时，回滚 Redis 缓存，避免脏数据
                    # 版本冲突场景：放弃旧版本同步，删除缓存和版本号，同时删除 dirty_key
                    # 这样用户会读到 DB 最新版本，保证最终一致性（以 DB 最新版为准）
                    logger.warning(
                        f"同步草稿失败（可能是版本冲突）: {draft_id}, "
                        f"current_version={current_version}，放弃旧版本同步，回滚 Redis 缓存"
                    )
                    try:
                        # 删除 Redis 缓存、版本号和脏数据标记（放弃旧版本同步）
                        # 用户下次读取时会从 DB 获取最新版本，保证最终一致性
                        version_key = self._get_version_key(draft_id)
                        self.redis_client.delete(cache_key, version_key, dirty_key)
                        logger.info(f"已回滚 Redis 缓存和版本号（放弃旧版本同步）: {draft_id}")
                    except Exception as e:
                        logger.error(f"回滚 Redis 缓存失败: {draft_id}, error={e}")
                    finally:
                        # 释放同步锁
                        if lock_acquired and lock_key:
                            try:
                                lock_key_bytes = lock_key.encode('utf-8') if isinstance(lock_key, str) else lock_key
                                self.redis_client.delete(lock_key_bytes)
                            except Exception as e:
                                logger.warning(f"释放同步锁失败 {draft_id}: {e}")
                    return (draft_id, "failed", "version_conflict")

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
                    reason = "retry_exhausted" if retry_count >= max_retries else "permanent_error"
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
                    # 优化：防止错误循环（Dead Loop）
                    # - 如果是永久性错误或重试用尽，只删除缓存和版本号，保留 dirty_key
                    # - 但需要记录失败次数，超过阈值后彻底删除，防止因代码 Bug 导致的永久失败无限重试
                    try:
                        if draft_id:
                            cache_key = self._get_cache_key(draft_id)
                            version_key = self._get_version_key(draft_id)
                            fail_count_key = self._get_dirty_fail_count_key(draft_id)
                            
                            # 使用Redis原子操作INCR来增加失败次数，避免多worker并发时的"丢失更新"问题
                            # 原因：如果多个同步worker同时失败，使用get+setex会导致计数不准确
                            #       例如两个worker都读到1，加1后都写回2，实际应该失败了2次，Redis里却只记了2
                            try:
                                # INCR 操作：如果key不存在，会先初始化为0再+1，返回新值
                                fail_count = self.redis_client.incr(fail_count_key)
                                # 设置TTL（如果key是新创建的，需要设置TTL；如果已存在，TTL保持不变）
                                if fail_count == 1:
                                    # 第一次失败，设置TTL
                                    self.redis_client.expire(fail_count_key, DRAFT_CACHE_TTL * 2)
                            except Exception as e:
                                logger.warning(f"增加失败计数器失败 {draft_id_str}: {e}")
                                fail_count = MAX_DIRTY_FAIL_COUNT  # 如果INCR失败，假设已达到阈值，直接删除
                            
                            # 如果失败次数超过阈值，彻底删除（防止错误循环）
                            if fail_count >= MAX_DIRTY_FAIL_COUNT:
                                logger.error(
                                    f"脏数据同步失败次数超过阈值 ({MAX_DIRTY_FAIL_COUNT})，彻底删除: {draft_id_str}, "
                                    f"reason={reason}，错误: {e}"
                                )
                                # 彻底删除：缓存、版本号、脏数据标记、失败计数器
                                self.redis_client.delete(cache_key, version_key, dirty_key, fail_count_key)
                                logger.warning(
                                    f"已彻底删除脏数据标记（防止错误循环）: {draft_id_str}"
                                )
                            else:
                                # 只删除缓存和版本号，保留 dirty_key 和失败计数器
                                # 失败计数器 TTL 设为脏数据标记的 2 倍，确保同步期间计数器不会过期
                                self.redis_client.delete(cache_key, version_key)
                                self.redis_client.setex(
                                    fail_count_key, 
                                    DRAFT_CACHE_TTL * 2, 
                                    str(fail_count).encode('utf-8')
                                )
                                logger.warning(
                                    f"已回滚 Redis 缓存和版本号（保留 dirty_key，失败次数: {fail_count}/{MAX_DIRTY_FAIL_COUNT}）: {draft_id_str}, "
                                    f"reason={reason}"
                                )
                    except Exception as rollback_error:
                        logger.error(f"回滚 Redis 缓存失败: {draft_id_str}, error={rollback_error}")
                    finally:
                        # 释放同步锁（如果已获取）
                        if draft_id and lock_acquired and lock_key:
                            try:
                                lock_key_bytes = lock_key.encode('utf-8') if isinstance(lock_key, str) else lock_key
                                self.redis_client.delete(lock_key_bytes)
                            except Exception as e:
                                logger.warning(f"释放同步锁失败 {draft_id_str}: {e}")
                    return (draft_id_str, "failed", reason)
            finally:
                # 确保在异常情况下也释放锁
                if draft_id and lock_acquired and lock_key:
                    try:
                        lock_key_bytes = lock_key.encode('utf-8') if isinstance(lock_key, str) else lock_key
                        self.redis_client.delete(lock_key_bytes)
                    except Exception as e:
                        logger.warning(f"释放同步锁失败（异常处理）: {e}")

        # 理论上不会到达这里
        return (draft_id or "unknown", "failed", "unknown_error")

    def _sync_to_postgres(self):
        """后台同步任务：将脏数据同步到PostgreSQL（支持批量限制和并发处理）"""
        try:
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

            if not dirty_keys:
                # 没有脏数据时，只输出 debug 日志，避免冗余
                logger.debug("后台同步任务执行：当前没有脏数据需要同步")
                return

            # 有脏数据时才输出 info 日志
            logger.info(f"开始执行后台同步任务：扫描到 {len(dirty_keys)} 个脏数据标记")
            logger.info(f"脏数据标记列表: {[k.decode('utf-8') if isinstance(k, bytes) else k for k in dirty_keys[:5]]}")

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
                "cache_read_error": 0,  # 缓存读取错误
                "already_syncing": 0,  # 同步锁已被其他线程获取（并发保护）
            }
            fail_reasons = {
                "version_conflict": 0,  # 版本冲突
                "retry_exhausted": 0,  # 重试用尽
                "permanent_error": 0,  # 永久性错误
                "exception": 0,  # 异常
                "unknown_error": 0,  # 未知错误
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
                        draft_id, result, reason = future.result()
                        if result == "synced":
                            synced_count += 1
                        elif result == "failed":
                            failed_count += 1
                            # 统计失败原因
                            if reason in fail_reasons:
                                fail_reasons[reason] += 1
                            else:
                                fail_reasons["unknown_error"] += 1
                        elif result == "skipped":
                            skipped_count += 1
                            # 统计跳过原因
                            if reason in skip_reasons:
                                skip_reasons[reason] += 1
                            else:
                                skip_reasons["dirty_key_not_exists"] += 1  # 默认归类
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
                fail_details = ", ".join([f"{k}={v}" for k, v in fail_reasons.items() if v > 0])
                logger.warning(f"失败详情: {fail_details}")
            if skipped_count > 0:
                skip_details = ", ".join([f"{k}={v}" for k, v in skip_reasons.items() if v > 0])
                logger.info(f"跳过详情: {skip_details}")
            # 如果有剩余脏数据，输出提示
            if total_count > len(dirty_keys):
                remaining = total_count - len(dirty_keys)
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

        # 先查Redis（直接从 redis_client 读取）
        try:
            cached_bytes = self.redis_client.get(cache_key)
            if cached_bytes is not None:
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
            # 删除Redis缓存、版本号、脏数据标记和失败计数器
            version_key = self._get_version_key(draft_id)
            fail_count_key = self._get_dirty_fail_count_key(draft_id)
            self.redis_client.delete(cache_key, version_key, dirty_key, fail_count_key)
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
