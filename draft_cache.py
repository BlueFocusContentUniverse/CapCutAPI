import asyncio
import logging
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple, Union

import pyJianYingDraft as draft
from repositories.draft_repository import get_postgres_storage

logger = logging.getLogger(__name__)

# 尝试导入Redis缓存
try:
    from repositories.redis_draft_cache import get_redis_draft_cache

    REDIS_CACHE_AVAILABLE = True
except Exception as e:
    REDIS_CACHE_AVAILABLE = False
    logger.debug(f"Redis草稿缓存层不可用: {e}")

<<<<<<< HEAD
REDIS_CACHE_AVAILABLE = False
logger.debug("Redis草稿缓存层不可用")
=======
# REDIS_CACHE_AVAILABLE = False
# logger.debug("Redis草稿缓存层不可用")
>>>>>>> 08df27e

# Keep in-memory cache for active drafts (faster access)
# Note: In-memory cache should be invalidated when using version-based locking
DRAFT_CACHE: Dict[str, Tuple["draft.ScriptFile", int]] = (
    OrderedDict()
)  # Store (script, version)
MAX_CACHE_SIZE = 100  # Reduced size since PostgreSQL is primary storage

# Retry configuration for concurrent updates
MAX_RETRIES = 3
RETRY_DELAY_MS = 50  # Initial retry delay in milliseconds


def _normalize_cache_key(raw_key: Any) -> Optional[str]:
    """Convert various incoming key representations into a cache-friendly string."""
    if isinstance(raw_key, str):
        stripped = raw_key.strip()
        return stripped or None

    if isinstance(raw_key, Mapping):
        for candidate in ("draft_id", "id", "key", "value"):
            value = raw_key.get(candidate)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    return stripped
        if len(raw_key) == 1:
            only_value = next(iter(raw_key.values()))
            if isinstance(only_value, str):
                stripped = only_value.strip()
                if stripped:
                    return stripped
        logger.error("Invalid mapping provided for draft cache key: %s", raw_key)
        return None

    if raw_key is None:
        return None

    draft_id_attr = getattr(raw_key, "draft_id", None)
    if isinstance(draft_id_attr, str):
        stripped = draft_id_attr.strip()
        if stripped:
            return stripped

    if isinstance(raw_key, (bytes, bytearray)):
        try:
            decoded = raw_key.decode().strip()
            return decoded or None
        except UnicodeDecodeError:
            logger.error("Failed to decode bytes provided as draft cache key")
            return None

    normalized = str(raw_key).strip()
    return normalized or None


def normalize_draft_id(raw_key: Any) -> Optional[str]:
    """Public helper to normalize external draft identifiers."""
    return _normalize_cache_key(raw_key)


async def update_cache(
    key: str, value: draft.ScriptFile, expected_version: Optional[int] = None
) -> bool:
    """
    Update cache with Redis (L1) and PostgreSQL (L2) with optimistic locking support.

    Args:
        key: Draft ID
        value: Script object to save
        expected_version: Expected version for optimistic locking. If None, no version check is performed.

    Returns:
        True if update succeeded, False if version mismatch occurred
    """
    logger.info(f"update_cache 被调用: key={key}, expected_version={expected_version}, REDIS_CACHE_AVAILABLE={REDIS_CACHE_AVAILABLE}")
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot update cache with invalid draft key: %s", key)
        return False

    try:
        # 优先使用Redis缓存
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_draft_cache()
                if redis_cache:
                    logger.info(f"准备调用 redis_cache.save_draft: cache_key={cache_key}, mark_dirty=True")
                    # 确保标记为脏数据，以便后台任务同步到 PostgreSQL
                    success = redis_cache.save_draft(
                        cache_key, value, expected_version=expected_version, mark_dirty=True
                    )
                    logger.info(f"redis_cache.save_draft 返回: success={success}")
                    if success:
                        # 清除内存缓存（重要：其他进程可能已更新）
                        if cache_key in DRAFT_CACHE:
                            DRAFT_CACHE.pop(cache_key)
                        logger.info(
                            f"Successfully updated draft {cache_key} via Redis cache"
                        )
                        return True
                    else:
                        logger.warning(
                            "Redis cache update failed, falling back to PostgreSQL"
                        )
            except Exception as e:
                logger.warning(
                    f"Redis cache unavailable: {e}, falling back to PostgreSQL"
                )

        # 降级到PostgreSQL
        # 漏洞 1 修复：确保 PG 写成功后，如果 Redis 可用，也写入 Redis（保证一致性）
        pg_storage = get_postgres_storage()
        success = await pg_storage.save_draft(
            cache_key, value, expected_version=expected_version
        )

        if not success:
            logger.warning(
                f"Failed to update draft {cache_key} due to version mismatch or other error"
            )
            # 漏洞 1 修复：PG 写失败时，如果 Redis 中有数据，应该清理 Redis 缓存
            if REDIS_CACHE_AVAILABLE:
                try:
                    redis_cache = get_redis_draft_cache()
                    if redis_cache:
                        # 清理 Redis 缓存，避免不一致
                        redis_cache.cache_region.delete(redis_cache._get_cache_key(cache_key))
                        dirty_key = redis_cache._get_dirty_key(cache_key)
                        redis_cache.redis_client.delete(dirty_key.encode('utf-8') if isinstance(dirty_key, str) else dirty_key)
                        logger.info(f"已清理 Redis 缓存（PG 写失败）: {cache_key}")
                except Exception as e:
                    logger.warning(f"清理 Redis 缓存失败: {e}")
            return False

        # 漏洞 1 修复：PG 写成功后，如果 Redis 可用，也写入 Redis（保证一致性）
        # 使用 mark_dirty=False，因为数据已经在 PG 中，不需要标记为脏数据
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_draft_cache()
                if redis_cache:
                    redis_cache.save_draft(cache_key, value, mark_dirty=False)
                    logger.debug(f"已同步到 Redis 缓存（PG 写成功）: {cache_key}")
            except Exception as e:
                logger.warning(f"同步到 Redis 缓存失败: {e}，但不影响主流程")

        # Clear in-memory cache to force reload from DB (ensures consistency)
        # This is important because another process might have updated the draft
        if cache_key in DRAFT_CACHE:
            DRAFT_CACHE.pop(cache_key)
            logger.debug(
                f"Cleared in-memory cache for draft {cache_key} after successful update"
            )

        logger.info(f"Successfully updated draft {cache_key} in PostgreSQL")
        return True

    except Exception as e:
        logger.error(f"Failed to update cache for {cache_key}: {e}")
        return False


async def get_from_cache(key: str) -> Optional[draft.ScriptFile]:
    """
    Get draft from cache (Redis -> PostgreSQL).

    Read-Through策略：优先从Redis获取，未命中则从PostgreSQL获取并缓存到Redis。
    """
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot retrieve draft with invalid key: %s", key)
        return None

    # 优先使用Redis缓存
    if REDIS_CACHE_AVAILABLE:
        try:
            redis_cache = get_redis_draft_cache()
            if redis_cache:
                draft_obj = redis_cache.get_draft(cache_key)
                if draft_obj is not None:
                    logger.debug(f"Retrieved draft {cache_key} from Redis cache")
                    return draft_obj
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}, falling back to PostgreSQL")

    # 降级到PostgreSQL
    try:
        pg_storage = get_postgres_storage()
        draft_obj = await pg_storage.get_draft(cache_key)

        if draft_obj is not None:
            logger.debug(f"Retrieved draft {cache_key} from PostgreSQL")
            # 如果Redis可用，尝试写入Redis缓存
            if REDIS_CACHE_AVAILABLE:
                try:
                    redis_cache = get_redis_draft_cache()
                    if redis_cache:
                        redis_cache.save_draft(cache_key, draft_obj, mark_dirty=False)
                except Exception:
                    pass  # 忽略Redis写入失败
            return draft_obj

        logger.warning(f"Draft {cache_key} not found in PostgreSQL")
        return None

    except Exception as e:
        logger.error(f"Failed to get draft {cache_key} from PostgreSQL: {e}")
        return None


async def get_from_cache_with_version(
    key: str,
) -> Optional[Tuple[draft.ScriptFile, int]]:
    """
    Get draft from cache along with its version number.

    Returns:
        Tuple of (script_obj, version) or None if not found
    """
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot retrieve draft with version using invalid key: %s", key)
        return None

    # 优先使用Redis缓存
    if REDIS_CACHE_AVAILABLE:
        try:
            redis_cache = get_redis_draft_cache()
            if redis_cache:
                result = redis_cache.get_draft_with_version(cache_key)
                if result is not None:
                    script_obj, version = result
                    logger.debug(
                        f"Retrieved draft {cache_key} from Redis cache with version {version}"
                    )
                    return (script_obj, version)
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}, falling back to PostgreSQL")

    # 降级到PostgreSQL
    try:
        pg_storage = get_postgres_storage()
        result = await pg_storage.get_draft_with_version(cache_key)

        if result is not None:
            script_obj, version = result
            logger.debug(
                f"Retrieved draft {cache_key} from PostgreSQL with version {version}"
            )
            # 如果Redis可用，尝试写入Redis缓存
            if REDIS_CACHE_AVAILABLE:
                try:
                    redis_cache = get_redis_draft_cache()
                    if redis_cache:
                        redis_cache.save_draft(cache_key, script_obj, mark_dirty=False)
                except Exception:
                    pass  # 忽略Redis写入失败
            return (script_obj, version)

        logger.warning(f"Draft {cache_key} not found in PostgreSQL")
        return None

    except Exception as e:
        logger.error(
            f"Failed to get draft {cache_key} with version from PostgreSQL: {e}"
        )
        # Fallback to memory cache only
        cached = DRAFT_CACHE.get(cache_key)
        if cached:
            logger.warning(f"Falling back to memory cache for draft {cache_key}")
            if isinstance(cached, tuple):
                return cached
            else:
                # Old cache format without version
                return (cached, 1)
        return None


async def remove_from_cache(key: str) -> bool:
    """Remove draft from both memory and PostgreSQL cache"""
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot remove draft with invalid key: %s", key)
        return False

    try:
        pg_storage = get_postgres_storage()
        pg_removed = await pg_storage.delete_draft(cache_key)

        memory_removed = cache_key in DRAFT_CACHE
        if memory_removed:
            DRAFT_CACHE.pop(cache_key)

        logger.info(
            f"Removed draft {cache_key} from cache (PostgreSQL: {pg_removed}, Memory: {memory_removed})"
        )
        return pg_removed or memory_removed

    except Exception as e:
        logger.error(f"Failed to remove draft {cache_key} from cache: {e}")
        # Fallback to memory cache only
        if cache_key in DRAFT_CACHE:
            DRAFT_CACHE.pop(cache_key)
            return True
        return False


async def cache_exists(key: str) -> bool:
    """Check if draft exists in cache"""
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot check existence for invalid draft key: %s", key)
        return False

    try:
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_draft_cache()
                if redis_cache and redis_cache.exists(cache_key):
                    return True
            except Exception as e:
                logger.warning(f"Redis exists check failed for {cache_key}: {e}")

        # 2. 检查 PostgreSQL
        pg_storage = get_postgres_storage()
        return await pg_storage.exists(cache_key)

    except Exception as e:
        # 评估是否需要降级
        logger.error(f"Failed to check if draft {cache_key} exists: {e}")
        return False


async def get_cache_stats() -> Dict:
    """Get cache statistics"""
    stats = {
        "memory_cache_size": len(DRAFT_CACHE),
        "memory_cache_max": MAX_CACHE_SIZE,
        "redis_cache_available": REDIS_CACHE_AVAILABLE,
    }

    # Redis缓存统计
    if REDIS_CACHE_AVAILABLE:
        try:
            redis_cache = get_redis_draft_cache()
            if redis_cache:
                redis_stats = redis_cache.get_stats()
                stats["redis_stats"] = redis_stats
        except Exception as e:
            logger.warning(f"Failed to get Redis cache stats: {e}")
            stats["redis_stats"] = {"redis_available": False}

    # PostgreSQL统计
    try:
        pg_storage = get_postgres_storage()
        pg_stats = await pg_storage.get_stats()
        stats["postgres_stats"] = pg_stats
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        stats["postgres_stats"] = {}

    return stats


async def update_draft_with_retry(
    draft_id: str,
    modifier_func,
    max_retries: int = MAX_RETRIES,
    *,
    return_error: bool = False,
) -> Union[bool, Tuple[bool, Optional[Exception]]]:
    """
    Update a draft with automatic retry on version conflicts.

    This function implements optimistic locking with retry logic:
    1. Fetch the latest draft with version
    2. Apply modifications using modifier_func
    3. Try to save with version check
    4. If version conflict, retry from step 1

    Args:
        draft_id: The draft ID to update
        modifier_func: A function that takes (script_obj) and modifies it in-place
        max_retries: Maximum number of retry attempts

    Returns:
        True if update succeeded, False if all retries exhausted

    Example:
        def add_video(script):
            script.add_video(...)

        success = update_draft_with_retry(draft_id, add_video)
    """
    normalized_id = _normalize_cache_key(draft_id)
    if not normalized_id:
        err = ValueError(f"Cannot update draft with invalid draft_id: {draft_id!r}")
        logger.error("%s", err)
        if return_error:
            return False, err
        return False

    retry_delay = RETRY_DELAY_MS / 1000.0  # Convert to seconds
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            # Get latest version from database
            result = await get_from_cache_with_version(normalized_id)
            if result is None:
                err = RuntimeError(
                    f"Draft {normalized_id} not found in cache or storage"
                )
                last_exception = err
                logger.error("%s", err)
                if return_error:
                    return False, err
                return False

            script, current_version = result
            logger.debug(
                f"Attempt {attempt + 1}/{max_retries}: Fetched draft {normalized_id} version {current_version}"
            )

            # Apply modifications
            modifier_func(script)

            # Try to save with version check
            # 如果 version=0，表示草稿在 PG 中不存在，使用 Write-Behind 策略（不立即同步）
            # 这样可以减轻 PG 压力，让后台任务统一同步
            # 只有当 version > 0 时，才使用乐观锁控制，立即同步以保证一致性
            if current_version == 0:
                # 新草稿，使用 Write-Behind 策略，不立即同步到 PG
                logger.debug(
                    f"草稿 {normalized_id} 在 PG 中不存在（version=0），使用 Write-Behind 策略，不立即同步"
                )
                success = await update_cache(
                    normalized_id, script, expected_version=None
                )
            else:
                # 已存在的草稿，使用乐观锁控制，立即同步以保证一致性
                success = await update_cache(
                    normalized_id, script, expected_version=current_version
                )

            if success:
                logger.info(
                    f"Successfully updated draft {normalized_id} on attempt {attempt + 1}"
                )
                if return_error:
                    return True, None
                return True
            else:
                last_exception = RuntimeError(
                    f"Version conflict for draft {normalized_id} on attempt {attempt + 1}/{max_retries}"
                )
                # Version conflict - retry
                if attempt < max_retries - 1:
                    logger.warning(
                        f"{last_exception}. Retrying in {retry_delay * 1000:.0f}ms..."
                    )
                    await asyncio.sleep(retry_delay)
                    # Exponential backoff
                    retry_delay *= 2
                else:
                    logger.error(
                        "Failed to update draft %s after %s attempts due to version conflicts",
                        normalized_id,
                        max_retries,
                    )
                    if return_error:
                        return False, last_exception
                    return False

        except Exception as e:
            last_exception = e
            logger.error(
                "Error during update attempt %s for draft %s: %s",
                attempt + 1,
                normalized_id,
                e,
                exc_info=True,
            )
            if return_error:
                return False, last_exception
            raise

    if return_error:
        return False, last_exception
    return False
