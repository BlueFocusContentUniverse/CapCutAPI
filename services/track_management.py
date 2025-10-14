"""
Service for managing tracks in Script_file instances
"""
import logging
from typing import Any, Dict

from draft_cache import get_from_cache, update_cache

logger = logging.getLogger(__name__)


def get_tracks(draft_id: str) -> Dict[str, Any]:
    """
    Get all tracks from a draft

    Args:
        draft_id: The draft ID to query

    Returns:
        Dictionary containing track information:
        {
            "tracks": [
                {
                    "name": str,
                    "type": str,
                    "render_index": int,
                    "mute": bool,
                    "segment_count": int,
                    "end_time": int (microseconds)
                },
                ...
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

    # Collect regular tracks
    tracks_info = []
    for track_name, track in script.tracks.items():
        track_info = {
            "name": track.name,
            "type": track.track_type.name,
            "render_index": track.render_index,
            "mute": track.mute,
            "segment_count": len(track.segments),
            "end_time": track.end_time
        }
        tracks_info.append(track_info)

    # Collect imported tracks
    imported_tracks_info = []
    for track in script.imported_tracks:
        track_info = {
            "name": track.name,
            "type": track.track_type.name,
            "render_index": track.render_index,
            "mute": track.mute,
            "segment_count": len(track.segments),
            "end_time": track.end_time
        }
        imported_tracks_info.append(track_info)

    result = {
        "tracks": tracks_info,
        "imported_tracks": imported_tracks_info,
        "total_tracks": len(tracks_info) + len(imported_tracks_info)
    }

    return result


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
    Get detailed information about a specific track
    
    Args:
        draft_id: The draft ID to query
        track_name: Name of the track to get details for
        
    Returns:
        Dictionary containing detailed track information:
        {
            "name": str,
            "type": str,
            "render_index": int,
            "mute": bool,
            "segment_count": int,
            "end_time": int (microseconds),
            "segments": [
                {
                    "start": int,
                    "end": int,
                    "duration": int,
                    "type": str
                },
                ...
            ]
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

    # Collect segment information
    segments_info = []
    for segment in track.segments:
        segment_info = {
            "start": segment.target_timerange.start,
            "end": segment.target_timerange.end,
            "duration": segment.target_timerange.duration,
            "type": type(segment).__name__
        }
        segments_info.append(segment_info)

    result = {
        "name": track.name,
        "type": track.track_type.name,
        "render_index": track.render_index,
        "mute": track.mute,
        "segment_count": len(track.segments),
        "end_time": track.end_time,
        "segments": segments_info
    }

    return result

