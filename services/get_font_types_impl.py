"""Service implementation for getting font types."""

import logging
from typing import Any, Dict

from pyJianYingDraft.metadata.font_meta import FontType

logger = logging.getLogger(__name__)


def get_font_types_impl() -> Dict[str, Any]:
    """Core logic for getting font types (without Flask dependency).
    
    Returns:
        Dictionary with success status and font types or error message
    """
    result = {"success": True, "output": "", "error": ""}
    try:
        logger.info("Fetching font types")
        font_types = []
        for name, member in FontType.__members__.items():
            font_types.append({"name": name})
        result["output"] = font_types
        logger.info(f"Successfully fetched {len(font_types)} font types")
        return result
    except Exception as e:
        result["success"] = False
        result["error"] = f"Error occurred while getting font types: {e!s}"
        logger.error(f"Failed to get font types: {e!s}", exc_info=True)
        return result


