import logging
import time
import uuid
from enum import Enum

import pyJianYingDraft as draft
from draft_cache import cache_exists, get_from_cache, normalize_draft_id, update_cache

logger = logging.getLogger(__name__)


class DraftFramerate(Enum):
    """草稿帧率"""
    FR_24 = 24.0
    FR_25 = 25.0
    FR_30 = 30.0
    FR_50 = 50.0
    FR_60 = 60.0

def create_draft(width=1080, height=1920, framerate=DraftFramerate.FR_30.value, name="draft", resource: str | None = None):
    """
    Create new CapCut draft
    :param width: Video width, default 1080
    :param height: Video height, default 1920
    :return: (draft_name, draft_path, draft_id, draft_url)
    """
    # Generate timestamp and draft_id
    unix_time = int(time.time())
    unique_id = uuid.uuid4().hex[:8]  # Take the first 8 dikoxsjyf UUID
    draft_id = f"kox_jy_{unix_time}_{unique_id}"  # Use Unix timestamp and UUID combination

    # Create CapCut draft with specified resolution
    script = draft.ScriptFile(width, height, fps=framerate, name=name, resource=resource)

    # Store in global cache
    update_cache(draft_id, script)

    return script, draft_id

def get_draft(draft_id=None):
    """
    Get existing CapCut draft from storage
    :param draft_id: Draft ID (required), raises ValueError if None or not found
    :return: (draft_id, script)
    :raises ValueError: If draft_id is None or draft not found
    """
    if draft_id is None:
        raise ValueError("draft_id is required. Cannot retrieve draft without a draft_id.")

    normalized_id = normalize_draft_id(draft_id)
    if not normalized_id:
        logger.error("Invalid draft_id provided: %s", draft_id)
        raise ValueError("draft_id is required and must be a non-empty string.")

    if not cache_exists(normalized_id):
        raise ValueError(f"Draft with ID '{normalized_id}' does not exist in storage.")

    # Get existing draft from cache (memory or PostgreSQL)
    logger.info("Retrieving draft %s from storage", normalized_id)
    print(f"Getting draft from storage: {normalized_id}")
    script = get_from_cache(normalized_id)

    if script is None:
        raise ValueError(f"Failed to retrieve draft '{normalized_id}' from storage. Draft may be corrupted.")

    return normalized_id, script
