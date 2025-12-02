"""
Service for managing tracks in Script_file instances
"""
import logging
from typing import Any, Dict

from draft_cache import get_from_cache, update_cache
from pyJianYingDraft.llm_export import export_track_for_llm, export_tracks_for_llm

logger = logging.getLogger(__name__)


def get_tracks(draft_id: str) -> Dict[str, Any]:
    """
    Get all tracks from a draft in LLM-friendly format.

    Args:
        draft_id: The draft ID to query

    Returns:
        Dictionary containing track information with only meaningful params:
        {
            "tracks": [
                {
                    "name": str,
                    "type": str,
                    "mute": bool,
                    "segment_count": int,
                    "end_time": float (seconds),
                    "segments": [...]
                }
            ],
            "imported_tracks": [...],
            "total_tracks": int
        }

    Raises:
        ValueError: If draft_id is not found
    """
    if not draft_id:
        raise ValueError("draft_id is required")

    script = get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    return export_tracks_for_llm(
        script.tracks,
        script.imported_tracks,
        include_segments=True
    )


def delete_track(draft_id: str, track_name: str) -> Dict[str, Any]:
    """
    Delete a track from a draft by name

    Args:
        draft_id: The draft ID to modify
        track_name: Name of the track to delete

    Returns:
        Dictionary containing deletion result:
        {
            "deleted_track": str,
            "remaining_tracks": int,
            "new_duration": int (microseconds)
        }

    Raises:
        ValueError: If draft_id is not found or track_name doesn't exist
    """
    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    script = get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    # Delete the track (this will raise NameError if track doesn't exist)
    try:
        script.delete_track(track_name)
    except NameError as e:
        raise ValueError(str(e))

    # Update cache with modified script
    update_cache(draft_id, script)

    # Calculate remaining tracks
    remaining_tracks = len(script.tracks) + len(script.imported_tracks)

    result = {
        "deleted_track": track_name,
        "remaining_tracks": remaining_tracks,
        "new_duration": script.duration
    }

    logger.info(f"Deleted track '{track_name}' from draft {draft_id}")

    return result


def get_track_details(draft_id: str, track_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific track in LLM-friendly format.

    Args:
        draft_id: The draft ID to query
        track_name: Name of the track to get details for

    Returns:
        Dictionary containing LLM-friendly track information:
        {
            "name": str,
            "type": str,
            "mute": bool,
            "segment_count": int,
            "end_time": float (seconds),
            "segments": [...]
        }

    Raises:
        ValueError: If draft_id or track_name is not found
    """
    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    script = get_from_cache(draft_id)
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

    return export_track_for_llm(track, include_segments=True)

