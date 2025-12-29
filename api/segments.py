"""
API endpoints for segment management in tracks
"""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from services.segment_management import (
    delete_segment,
    get_segment_details,
    modify_segment,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["segments"], prefix="/segments")


class GetSegmentDetailsRequest(BaseModel):
    draft_id: str
    track_name: str
    segment_id: str


@router.post("/get_segment_details")
async def get_segment_details_api(request: GetSegmentDetailsRequest):
    """
    Get detailed information about a specific segment
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    if not request.track_name:
        result["error"] = (
            "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        )
        return result

    if not request.segment_id:
        result["error"] = (
            "Hi, the required parameter 'segment_id' is missing. Please add it and try again."
        )
        return result

    try:
        segment_details = await get_segment_details(
            request.draft_id, request.track_name, request.segment_id
        )

        result["success"] = True
        result["output"] = segment_details
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        logger.error(f"Error getting segment details: {e}", exc_info=True)
        result["error"] = f"Error occurred while getting segment details: {e!s}"
        return result


class DeleteSegmentRequest(BaseModel):
    draft_id: str
    track_name: str
    segment_index: Optional[int] = None
    segment_id: Optional[str] = None


@router.post("/delete_segment")
async def delete_segment_api(request: DeleteSegmentRequest):
    """
    Delete a segment from a track by index or ID
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    if not request.track_name:
        result["error"] = (
            "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        )
        return result

    if request.segment_index is None and request.segment_id is None:
        result["error"] = (
            "Hi, you must provide either 'segment_index' or 'segment_id'. Please add one and try again."
        )
        return result

    if request.segment_index is not None and request.segment_id is not None:
        result["error"] = (
            "Hi, you can only provide one of 'segment_index' or 'segment_id', not both. Please remove one and try again."
        )
        return result

    try:
        delete_result = await delete_segment(
            request.draft_id,
            request.track_name,
            segment_index=request.segment_index,
            segment_id=request.segment_id,
        )

        result["success"] = True
        result["output"] = delete_result
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        logger.error(f"Error deleting segment: {e}", exc_info=True)
        result["error"] = f"Error occurred while deleting segment: {e!s}"
        return result


class ClipSettingsRequest(BaseModel):
    """Clip settings for visual segments"""

    alpha: Optional[float] = None  # Opacity 0-1
    flip_horizontal: Optional[bool] = None
    flip_vertical: Optional[bool] = None
    rotation: Optional[float] = None  # Rotation angle in degrees
    scale_x: Optional[float] = None  # Horizontal scale
    scale_y: Optional[float] = None  # Vertical scale
    transform_x: Optional[float] = None  # Horizontal position
    transform_y: Optional[float] = None  # Vertical position


class ModifySegmentRequest(BaseModel):
    draft_id: str
    track_name: str
    segment_id: str
    clip_settings: Optional[ClipSettingsRequest] = None
    volume: Optional[float] = None  # Volume 0-2
    speed: Optional[float] = None  # Playback speed


@router.post("/modify_segment")
async def modify_segment_api(request: ModifySegmentRequest):
    """
    Modify a segment's properties (clip settings, volume, speed)

    - **clip_settings**: Visual adjustments like alpha, rotation, scale, transform, flip
    - **volume**: Audio volume level (0-2)
    - **speed**: Playback speed multiplier
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    if not request.track_name:
        result["error"] = (
            "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        )
        return result

    if not request.segment_id:
        result["error"] = (
            "Hi, the required parameter 'segment_id' is missing. Please add it and try again."
        )
        return result

    if (
        request.clip_settings is None
        and request.volume is None
        and request.speed is None
    ):
        result["error"] = (
            "Hi, you must provide at least one of 'clip_settings', 'volume', or 'speed'. Please add one and try again."
        )
        return result

    try:
        # Convert clip_settings to dict if provided
        clip_settings_dict = None
        if request.clip_settings:
            clip_settings_dict = request.clip_settings.model_dump(exclude_none=True)

        modify_result = await modify_segment(
            request.draft_id,
            request.track_name,
            request.segment_id,
            clip_settings=clip_settings_dict,
            volume=request.volume,
            speed=request.speed,
        )

        result["success"] = True
        result["output"] = modify_result
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except TypeError as e:
        result["error"] = f"Unsupported operation: {e!s}"
        return result
    except Exception as e:
        logger.error(f"Error modifying segment: {e}", exc_info=True)
        result["error"] = f"Error occurred while modifying segment: {e!s}"
        return result
