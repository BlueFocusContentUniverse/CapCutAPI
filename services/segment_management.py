"""
Service for managing segments in tracks
"""

import logging
from typing import Any, Dict, Optional

from draft_cache import get_from_cache, update_cache
from pyJianYingDraft.exceptions import SegmentNotFound
from pyJianYingDraft.llm_export import export_segment_for_llm

logger = logging.getLogger(__name__)


class ClipSettingsUpdate:
    """Helper class for partial clip settings updates"""

    def __init__(self, data: Dict[str, Any]):
        self.alpha = data.get("alpha")
        self.flip_horizontal = data.get("flip_horizontal")
        self.flip_vertical = data.get("flip_vertical")
        self.rotation = data.get("rotation")
        self.scale_x = data.get("scale_x")
        self.scale_y = data.get("scale_y")
        self.transform_x = data.get("transform_x")
        self.transform_y = data.get("transform_y")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values"""
        result = {}
        if self.alpha is not None:
            result["alpha"] = self.alpha
        if self.flip_horizontal is not None:
            result["flip_horizontal"] = self.flip_horizontal
        if self.flip_vertical is not None:
            result["flip_vertical"] = self.flip_vertical
        if self.rotation is not None:
            result["rotation"] = self.rotation
        if self.scale_x is not None:
            result["scale_x"] = self.scale_x
        if self.scale_y is not None:
            result["scale_y"] = self.scale_y
        if self.transform_x is not None:
            result["transform_x"] = self.transform_x
        if self.transform_y is not None:
            result["transform_y"] = self.transform_y
        return result


async def get_segment_details(
    draft_id: str, track_name: str, segment_id: str
) -> Dict[str, Any]:
    """
    Get detailed information about a specific segment in LLM-friendly format.

    Args:
        draft_id: The draft ID to query
        track_name: Name of the track containing the segment
        segment_id: ID of the segment to get details for

    Returns:
        Dictionary containing LLM-friendly segment information:
        {
            "id": str,
            "type": str,
            "start_time": float (seconds),
            "duration": float (seconds),
            "end_time": float (seconds),
            "volume": float,
            "speed": float,
            "clip": {...},  # For visual segments
            "text": str,    # For text segments
            "material": {...},  # For video/audio segments
        }

    Raises:
        ValueError: If draft_id, track_name, or segment_id is not found
    """
    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    if not segment_id:
        raise ValueError("segment_id is required")

    script = await get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    # Find the track
    track = None
    if track_name in script.tracks:
        track = script.tracks[track_name]
    else:
        for imported_track in script.imported_tracks:
            if imported_track.name == track_name:
                track = imported_track
                break

    if track is None:
        raise ValueError(f"Track '{track_name}' not found in draft {draft_id}")

    # Find the segment by ID
    segment = None
    for seg in track.segments:
        if seg.segment_id == segment_id:
            segment = seg
            break

    if segment is None:
        raise ValueError(f"Segment '{segment_id}' not found in track '{track_name}'")

    logger.info(f"Found segment {segment_id} in track {track_name} of draft {draft_id}")

    # Use LLM-friendly export
    result = export_segment_for_llm(segment)

    logger.info(f"Successfully retrieved details for segment {segment_id}")

    return result


async def delete_segment(
    draft_id: str,
    track_name: str,
    segment_index: Optional[int] = None,
    segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a segment from a track by index or ID

    Args:
        draft_id: The draft ID to modify
        track_name: Name of the track containing the segment
        segment_index: Index of the segment to delete (0-based). Mutually exclusive with segment_id.
        segment_id: ID of the segment to delete. Mutually exclusive with segment_index.

    Returns:
        Dictionary containing success status and updated draft information:
        {
            "success": True,
            "message": str,
            "draft_id": str,
            "track_name": str,
            "deleted_segment_index": int (if deleted by index),
            "deleted_segment_id": str (if deleted by id or if we found the index),
            "remaining_segments_count": int,
            "draft_duration": int
        }

    Raises:
        ValueError: If draft_id or track_name is not provided, or if both/neither
                   segment_index and segment_id are provided, or if segment not found
    """
    logger.info(
        f"Deleting segment from draft {draft_id}, track {track_name}, "
        f"index={segment_index}, id={segment_id}"
    )

    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    if (segment_index is None and segment_id is None) or (
        segment_index is not None and segment_id is not None
    ):
        raise ValueError("Must provide exactly one of segment_index or segment_id")

    # Get the script from cache
    script = await get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    # Perform the deletion using the Script_file method
    try:
        script.delete_segment(
            track_name, segment_index=segment_index, segment_id=segment_id
        )
    except SegmentNotFound as e:
        logger.error(f"Failed to delete segment: {e!s}")
        raise ValueError(str(e)) from e
    except Exception as e:
        logger.error(f"Error deleting segment: {e!s}")
        raise

    # Save the updated script back to cache
    await update_cache(draft_id, script)

    # Get the updated track for response info
    track = None
    if track_name in script.tracks:
        track = script.tracks[track_name]
    else:
        for imported_track in script.imported_tracks:
            if imported_track.name == track_name:
                track = imported_track
                break

    remaining_count = len(track.segments) if track else 0

    logger.info(
        f"Successfully deleted segment {segment_id} from track {track_name}. "
        f"Remaining segments: {remaining_count}, Draft duration: {script.duration}"
    )

    return {
        "success": True,
        "message": f"Segment deleted successfully from track '{track_name}'",
        "draft_id": draft_id,
        "track_name": track_name,
        "deleted_segment_id": segment_id,
        "deleted_segment_index": segment_index,
        "remaining_segments_count": remaining_count,
    }


async def modify_segment(
    draft_id: str,
    track_name: str,
    segment_id: str,
    clip_settings: Optional[Dict[str, Any]] = None,
    volume: Optional[float] = None,
    speed: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Modify a segment's properties (clip settings, volume, speed)

    Args:
        draft_id: The draft ID to modify
        track_name: Name of the track containing the segment
        segment_id: ID of the segment to modify
        clip_settings: Optional clip settings to update. Can include:
            - alpha (float): Opacity, 0-1
            - flip_horizontal (bool): Horizontal flip
            - flip_vertical (bool): Vertical flip
            - rotation (float): Rotation angle in degrees
            - scale_x (float): Horizontal scale
            - scale_y (float): Vertical scale
            - transform_x (float): Horizontal position
            - transform_y (float): Vertical position
        volume: Optional volume level (0-2)
        speed: Optional playback speed

    Returns:
        Dictionary containing success status and updated segment info:
        {
            "success": True,
            "message": str,
            "draft_id": str,
            "track_name": str,
            "segment_id": str,
            "updated_fields": List[str]
        }

    Raises:
        ValueError: If required parameters are missing or segment not found
        TypeError: If trying to modify unsupported properties for segment type
    """
    logger.info(
        f"Modifying segment in draft {draft_id}, track {track_name}, segment_id={segment_id}"
    )

    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    if not segment_id:
        raise ValueError("segment_id is required")

    if clip_settings is None and volume is None and speed is None:
        raise ValueError(
            "At least one of clip_settings, volume, or speed must be provided"
        )

    # Get the script from cache
    script = await get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    # Process clip_settings if provided
    clip_settings_dict = None
    if clip_settings is not None:
        clip_update = ClipSettingsUpdate(clip_settings)
        clip_settings_dict = clip_update.to_dict()

    # Track which fields were updated
    updated_fields = []
    if clip_settings_dict:
        updated_fields.extend(list(clip_settings_dict.keys()))
    if volume is not None:
        updated_fields.append("volume")
    if speed is not None:
        updated_fields.append("speed")

    # Perform the modification using the Script_file method
    try:
        script.modify_segment(
            track_name,
            segment_id,
            clip_settings=clip_settings_dict,
            volume=volume,
            speed=speed,
        )
    except SegmentNotFound as e:
        logger.error(f"Failed to modify segment: {e!s}")
        raise ValueError(str(e)) from e
    except NameError as e:
        logger.error(f"Track not found: {e!s}")
        raise ValueError(str(e)) from e
    except TypeError as e:
        logger.error(f"Unsupported property modification: {e!s}")
        raise
    except Exception as e:
        logger.error(f"Error modifying segment: {e!s}")
        raise

    # Save the updated script back to cache
    await update_cache(draft_id, script)

    logger.info(
        f"Successfully modified segment {segment_id} in track {track_name}. "
        f"Updated fields: {updated_fields}"
    )

    return {
        "success": True,
        "message": f"Segment modified successfully in track '{track_name}'",
        "draft_id": draft_id,
        "track_name": track_name,
        "segment_id": segment_id,
        "updated_fields": updated_fields,
    }
