"""
Service for managing segments in tracks
"""
import logging
from typing import Any, Dict, Optional

from draft_cache import get_from_cache, update_cache
from pyJianYingDraft.audio_segment import AudioSegment
from pyJianYingDraft.effect_segment import Effect_segment
from pyJianYingDraft.exceptions import SegmentNotFound
from pyJianYingDraft.text_segment import Text_segment
from pyJianYingDraft.video_segment import VideoSegment

logger = logging.getLogger(__name__)


def get_segment_details(draft_id: str, track_name: str, segment_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific segment

    Args:
        draft_id: The draft ID to query
        track_name: Name of the track containing the segment
        segment_id: ID of the segment to get details for

    Returns:
        Dictionary containing detailed segment information with all properties:
        {
            "id": str,
            "material_id": str,
            "type": str,
            "target_timerange": {
                "start": int,
                "duration": int
            },
            "start": int,
            "end": int,
            "duration": int,

            # For Media_segment (Audio/Video):
            "source_timerange": {
                "start": int,
                "duration": int
            } (optional),
            "speed": float,
            "volume": float,

            # For Visual_segment (Video/Text/Sticker):
            "clip_settings": {
                "alpha": float,
                "flip": {"horizontal": bool, "vertical": bool},
                "rotation": float,
                "scale": {"x": float, "y": float},
                "transform": {"x": float, "y": float}
            },
            "uniform_scale": {"on": bool, "value": float},

            # For Video_segment specific:
            "material_name": str (optional),
            "cartoon": bool (optional),
            "filters": [...] (optional),
            "masks": [...] (optional),
            "effects": [...] (optional),

            # For Text_segment specific:
            "content": str (optional),
            "font_info": {...} (optional),
            "style": {...} (optional),

            # For Audio_segment specific:
            "fade": {...} (optional),
            "audio_effects": [...] (optional),

            # Common for all segments:
            "common_keyframes": [...],
            "extra_material_refs": [...]
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

    # Find the segment by ID
    segment = None
    for seg in track.segments:
        if seg.segment_id == segment_id:
            segment = seg
            break

    if segment is None:
        raise ValueError(f"Segment '{segment_id}' not found in track '{track_name}'")

    logger.info(f"Found segment {segment_id} in track {track_name} of draft {draft_id}")

    # Build the basic segment info
    result = {
        "id": segment.segment_id,
        "material_id": segment.material_id,
        "type": type(segment).__name__,
        "target_timerange": {
            "start": segment.target_timerange.start,
            "duration": segment.target_timerange.duration
        },
        "start": segment.start,
        "end": segment.end,
        "duration": segment.duration,
    }

    # Add properties based on segment type hierarchy
    # Check if it's a Media_segment (has source_timerange, speed, volume)
    if hasattr(segment, "source_timerange"):
        result["source_timerange"] = {
            "start": segment.source_timerange.start if segment.source_timerange else None,
            "duration": segment.source_timerange.duration if segment.source_timerange else None
        } if segment.source_timerange else None
        result["speed"] = segment.speed.speed if hasattr(segment.speed, "speed") else segment.speed
        result["volume"] = segment.volume
        result["extra_material_refs"] = segment.extra_material_refs

    # Check if it's a Visual_segment (has clip_settings)
    if hasattr(segment, "clip_settings"):
        clip = segment.clip_settings
        result["clip_settings"] = {
            "alpha": clip.alpha,
            "flip": {
                "horizontal": clip.flip_horizontal,
                "vertical": clip.flip_vertical
            },
            "rotation": clip.rotation,
            "scale": {
                "x": clip.scale_x,
                "y": clip.scale_y
            },
            "transform": {
                "x": clip.transform_x,
                "y": clip.transform_y
            }
        }
        result["uniform_scale"] = {
            "on": segment.uniform_scale,
            "value": 1.0
        }

        # Add animations if present
        if hasattr(segment, "animations_instance") and segment.animations_instance:
            result["animations"] = {
                "has_animation": True,
                "animation_id": segment.animations_instance.global_id
            }

    # Add common keyframes
    if hasattr(segment, "common_keyframes"):
        result["common_keyframes"] = []
        for kf_list in segment.common_keyframes:
            keyframes_data = {
                "property": kf_list.keyframe_property.name if hasattr(kf_list.keyframe_property, "name") else str(kf_list.keyframe_property),
                "keyframes": [
                    {
                        "time_offset": kf.time_offset,
                        "value": kf.value
                    } for kf in kf_list.keyframes
                ]
            }
            result["common_keyframes"].append(keyframes_data)

    # Video_segment specific properties
    if isinstance(segment, VideoSegment):
        if hasattr(segment, "material_instance") and segment.material_instance:
            result["material_name"] = getattr(segment.material_instance, "name", None)
            result["material_path"] = getattr(segment.material_instance, "path", None)
            result["material_duration"] = getattr(segment.material_instance, "duration", None)
            result["material_width"] = getattr(segment.material_instance, "width", None)
            result["material_height"] = getattr(segment.material_instance, "height", None)

        result["cartoon"] = segment.cartoon if hasattr(segment, "cartoon") else False

        # Filters
        if hasattr(segment, "filters") and segment.filters:
            result["filters"] = [
                {
                    "name": f.name if hasattr(f, "name") else None,
                    "intensity": f.intensity if hasattr(f, "intensity") else None,
                    "id": f.filter_id if hasattr(f, "filter_id") else None
                } for f in segment.filters
            ]

        # Masks
        if hasattr(segment, "masks") and segment.masks:
            result["masks"] = [
                {
                    "name": m.mask_meta.name if hasattr(m, "mask_meta") else None,
                    "id": m.global_id if hasattr(m, "global_id") else None,
                    "center": {"x": m.center_x, "y": m.center_y} if hasattr(m, "center_x") else None,
                    "width": m.width if hasattr(m, "width") else None,
                    "height": m.height if hasattr(m, "height") else None,
                    "rotation": m.rotation if hasattr(m, "rotation") else None,
                    "invert": m.invert if hasattr(m, "invert") else None,
                    "feather": m.feather if hasattr(m, "feather") else None
                } for m in segment.masks
            ]

        # Effects (character/scene effects)
        if hasattr(segment, "effects") and segment.effects:
            result["effects"] = [
                {
                    "name": e.name if hasattr(e, "name") else None,
                    "id": e.effect_id if hasattr(e, "effect_id") else None,
                    "resource_id": e.resource_id if hasattr(e, "resource_id") else None,
                    "category": e.category_name if hasattr(e, "category_name") else None
                } for e in segment.effects
            ]

        # Transitions
        if hasattr(segment, "transition") and segment.transition:
            trans = segment.transition
            result["transition"] = {
                "name": trans.name if hasattr(trans, "name") else None,
                "id": trans.transition_id if hasattr(trans, "transition_id") else None,
                "duration": trans.duration if hasattr(trans, "duration") else None
            }

    # Text_segment specific properties
    elif isinstance(segment, Text_segment):
        result["content"] = segment.content if hasattr(segment, "content") else None

        if hasattr(segment, "font") and segment.font:
            result["font_info"] = {
                "name": segment.font.name if hasattr(segment.font, "name") else None,
                "id": segment.font.font_id if hasattr(segment.font, "font_id") else None
            }

        if hasattr(segment, "style") and segment.style:
            style = segment.style
            result["style"] = {
                "size": style.size if hasattr(style, "size") else None,
                "bold": style.bold if hasattr(style, "bold") else None,
                "italic": style.italic if hasattr(style, "italic") else None,
                "underline": style.underline if hasattr(style, "underline") else None,
                "color": style.color if hasattr(style, "color") else None,
                "alpha": style.alpha if hasattr(style, "alpha") else None,
                "align": style.align if hasattr(style, "align") else None,
                "vertical": style.vertical if hasattr(style, "vertical") else None,
                "letter_spacing": style.letter_spacing if hasattr(style, "letter_spacing") else None,
                "line_spacing": style.line_spacing if hasattr(style, "line_spacing") else None
            }

        if hasattr(segment, "border") and segment.border:
            border = segment.border
            result["border"] = {
                "color": border.color if hasattr(border, "color") else None,
                "alpha": border.alpha if hasattr(border, "alpha") else None,
                "width": border.width if hasattr(border, "width") else None
            }

        if hasattr(segment, "shadow") and segment.shadow:
            shadow = segment.shadow
            result["shadow"] = {
                "color": shadow.color if hasattr(shadow, "color") else None,
                "alpha": shadow.alpha if hasattr(shadow, "alpha") else None,
                "angle": shadow.angle if hasattr(shadow, "angle") else None,
                "distance": shadow.distance if hasattr(shadow, "distance") else None,
                "blur": shadow.blur if hasattr(shadow, "blur") else None
            }

    # Audio_segment specific properties
    elif isinstance(segment, AudioSegment):
        if hasattr(segment, "material_instance") and segment.material_instance:
            result["material_name"] = getattr(segment.material_instance, "name", None)
            result["material_path"] = getattr(segment.material_instance, "path", None)
            result["material_duration"] = getattr(segment.material_instance, "duration", None)

        if hasattr(segment, "fade") and segment.fade:
            fade = segment.fade
            result["fade"] = {
                "id": fade.fade_id if hasattr(fade, "fade_id") else None,
                "in_duration": fade.in_duration if hasattr(fade, "in_duration") else None,
                "out_duration": fade.out_duration if hasattr(fade, "out_duration") else None
            }

        if hasattr(segment, "effects") and segment.effects:
            result["audio_effects"] = [
                {
                    "name": e.name if hasattr(e, "name") else None,
                    "id": e.effect_id if hasattr(e, "effect_id") else None,
                    "resource_id": e.resource_id if hasattr(e, "resource_id") else None,
                    "category": e.category_name if hasattr(e, "category_name") else None
                } for e in segment.effects
            ]

    # Effect_segment specific properties
    elif isinstance(segment, Effect_segment):
        if hasattr(segment, "effect_meta") and segment.effect_meta:
            result["effect_info"] = {
                "name": segment.effect_meta.name if hasattr(segment.effect_meta, "name") else None,
                "resource_id": segment.effect_meta.resource_id if hasattr(segment.effect_meta, "resource_id") else None
            }

    logger.info(f"Successfully retrieved details for segment {segment_id}")

    return result


def delete_segment(draft_id: str, track_name: str, segment_index: Optional[int] = None,
                   segment_id: Optional[str] = None) -> Dict[str, Any]:
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
    logger.info(f"Deleting segment from draft {draft_id}, track {track_name}, "
                f"index={segment_index}, id={segment_id}")

    if not draft_id:
        raise ValueError("draft_id is required")

    if not track_name:
        raise ValueError("track_name is required")

    if (segment_index is None and segment_id is None) or \
       (segment_index is not None and segment_id is not None):
        raise ValueError("Must provide exactly one of segment_index or segment_id")

    # Get the script from cache
    script = get_from_cache(draft_id)
    if script is None:
        raise ValueError(f"Draft {draft_id} not found in cache")

    # Perform the deletion using the Script_file method
    try:
        script.delete_segment(track_name, segment_index=segment_index, segment_id=segment_id)
    except SegmentNotFound as e:
        logger.error(f"Failed to delete segment: {e!s}")
        raise ValueError(str(e)) from e
    except Exception as e:
        logger.error(f"Error deleting segment: {e!s}")
        raise

    # Save the updated script back to cache
    update_cache(draft_id, script)

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

    logger.info(f"Successfully deleted segment {segment_id} from track {track_name}. "
                f"Remaining segments: {remaining_count}, Draft duration: {script.duration}")

    return {
        "success": True,
        "message": f"Segment deleted successfully from track '{track_name}'",
        "draft_id": draft_id,
        "track_name": track_name,
        "deleted_segment_id": segment_id,
        "deleted_segment_index": segment_index,
        "remaining_segments_count": remaining_count,
    }
