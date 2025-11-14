import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple, Union

import pyJianYingDraft as draft
from repositories.draft_repository import get_postgres_storage

logger = logging.getLogger(__name__)

# Keep in-memory cache for active drafts (faster access)
# Note: In-memory cache should be invalidated when using version-based locking
DRAFT_CACHE: Dict[str, Tuple["draft.ScriptFile", int]] = OrderedDict()  # Store (script, version)
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

def update_cache(key: str, value: draft.ScriptFile, expected_version: Optional[int] = None) -> bool:
    """
    Update cache in both memory and PostgreSQL with optimistic locking support.

    Args:
        key: Draft ID
        value: Script object to save
        expected_version: Expected version for optimistic locking. If None, no version check is performed.

    Returns:
        True if update succeeded, False if version mismatch occurred
    """
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot update cache with invalid draft key: %s", key)
        return False

    try:
        # Update PostgreSQL storage (persistent) with version check
        pg_storage = get_postgres_storage()
        success = pg_storage.save_draft(cache_key, value, expected_version=expected_version)

        if not success:
            logger.warning(f"Failed to update draft {cache_key} due to version mismatch or other error")
            return False

        # Clear in-memory cache to force reload from DB (ensures consistency)
        # This is important because another process might have updated the draft
        if cache_key in DRAFT_CACHE:
            DRAFT_CACHE.pop(cache_key)
            logger.debug(f"Cleared in-memory cache for draft {cache_key} after successful update")

        logger.info(f"Successfully updated draft {cache_key} in PostgreSQL")
        return True

    except Exception as e:
        logger.error(f"Failed to update cache for {cache_key}: {e}")
        return False

def get_from_cache(key: str) -> Optional[draft.ScriptFile]:
    """
    Get draft from cache (PostgreSQL first for consistency).

    Note: We prioritize PostgreSQL over memory cache to ensure we always
    get the latest version when concurrent updates are happening.
    """
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot retrieve draft with invalid key: %s", key)
        return None

    try:
        # Always fetch from PostgreSQL to ensure latest version
        pg_storage = get_postgres_storage()
        draft_obj = pg_storage.get_draft(cache_key)

        if draft_obj is not None:
            logger.debug(f"Retrieved draft {cache_key} from PostgreSQL")
            return draft_obj

        logger.warning(f"Draft {cache_key} not found in PostgreSQL")
        return None

    except Exception as e:
        logger.error(f"Failed to get draft {cache_key} from PostgreSQL: {e}")
        # Fallback to memory cache only
        cached = DRAFT_CACHE.get(cache_key)
        if cached:
            logger.warning(f"Falling back to memory cache for draft {cache_key}")
            return cached[0] if isinstance(cached, tuple) else cached
        return None

def get_from_cache_with_version(key: str) -> Optional[Tuple[draft.ScriptFile, int]]:
    """
    Get draft from cache along with its version number.

    Returns:
        Tuple of (script_obj, version) or None if not found
    """
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot retrieve draft with version using invalid key: %s", key)
        return None

    try:
        # Fetch from PostgreSQL with version information
        pg_storage = get_postgres_storage()
        result = pg_storage.get_draft_with_version(cache_key)

        if result is not None:
            script_obj, version = result
            logger.debug(f"Retrieved draft {cache_key} from PostgreSQL with version {version}")
            return (script_obj, version)

        logger.warning(f"Draft {cache_key} not found in PostgreSQL")
        return None

    except Exception as e:
        logger.error(f"Failed to get draft {cache_key} with version from PostgreSQL: {e}")
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

def remove_from_cache(key: str) -> bool:
    """Remove draft from both memory and PostgreSQL cache"""
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot remove draft with invalid key: %s", key)
        return False

    try:
        pg_storage = get_postgres_storage()
        pg_removed = pg_storage.delete_draft(cache_key)

        memory_removed = cache_key in DRAFT_CACHE
        if memory_removed:
            DRAFT_CACHE.pop(cache_key)

        logger.info(f"Removed draft {cache_key} from cache (PostgreSQL: {pg_removed}, Memory: {memory_removed})")
        return pg_removed or memory_removed

    except Exception as e:
        logger.error(f"Failed to remove draft {cache_key} from cache: {e}")
        # Fallback to memory cache only
        if cache_key in DRAFT_CACHE:
            DRAFT_CACHE.pop(cache_key)
            return True
        return False

def cache_exists(key: str) -> bool:
    """Check if draft exists in cache"""
    cache_key = _normalize_cache_key(key)
    if not cache_key:
        logger.error("Cannot check existence for invalid draft key: %s", key)
        return False

    try:
        if cache_key in DRAFT_CACHE:
            return True

        pg_storage = get_postgres_storage()
        return pg_storage.exists(cache_key)

    except Exception as e:
        logger.error(f"Failed to check if draft {cache_key} exists: {e}")
        return cache_key in DRAFT_CACHE

def get_cache_stats() -> Dict:
    """Get cache statistics"""
    try:
        pg_storage = get_postgres_storage()
        pg_stats = pg_storage.get_stats()

        return {
            "memory_cache_size": len(DRAFT_CACHE),
            "memory_cache_max": MAX_CACHE_SIZE,
            "postgres_stats": pg_stats
        }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {
            "memory_cache_size": len(DRAFT_CACHE),
            "memory_cache_max": MAX_CACHE_SIZE,
            "postgres_stats": {}
        }

def update_draft_with_retry(
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
            result = get_from_cache_with_version(normalized_id)
            if result is None:
                err = RuntimeError(f"Draft {normalized_id} not found in cache or storage")
                last_exception = err
                logger.error("%s", err)
                if return_error:
                    return False, err
                return False

            script, current_version = result
            logger.debug(f"Attempt {attempt + 1}/{max_retries}: Fetched draft {normalized_id} version {current_version}")

            # Apply modifications
            modifier_func(script)

            # Try to save with version check
            success = update_cache(normalized_id, script, expected_version=current_version)

            if success:
                logger.info(f"Successfully updated draft {normalized_id} on attempt {attempt + 1}")
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
                    time.sleep(retry_delay)
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
