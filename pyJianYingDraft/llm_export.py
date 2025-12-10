"""
LLM-friendly export utilities for tracks and segments.

This module provides simplified data structures that contain only
the meaningful parameters for LLM understanding and modification,
removing internal IDs, flags, and other technical details.
"""

from typing import Any, Dict, List, Optional

from .audio_segment import AudioSegment
from .segment import BaseSegment, MediaSegment, VisualSegment
from .text_segment import Text_segment
from .track import Track
from .video_segment import StickerSegment, VideoSegment


def export_clip_settings_for_llm(segment: VisualSegment) -> Dict[str, Any]:
    """Export clip settings in LLM-friendly format."""
    clip = segment.clip_settings
    return {
        "alpha": clip.alpha,
        "rotation": clip.rotation,
        "scale": {"x": clip.scale_x, "y": clip.scale_y},
        "position": {"x": clip.transform_x, "y": clip.transform_y},
        "flip": {"horizontal": clip.flip_horizontal, "vertical": clip.flip_vertical},
    }


def export_segment_for_llm(segment: BaseSegment) -> Dict[str, Any]:
    """
    Export a segment in LLM-friendly format with only meaningful parameters.

    Args:
        segment: Any segment type (Video, Audio, Text, Sticker, Effect)

    Returns:
        Dictionary with only LLM-relevant fields:
        - id: Segment identifier for modification
        - type: Segment type name
        - start_time: Start time in seconds
        - duration: Duration in seconds
        - end_time: End time in seconds
        - For media segments: volume, speed
        - For visual segments: clip settings (alpha, rotation, scale, position, flip)
        - For text segments: text content
        - For video segments: material name/path
    """
    # Convert microseconds to seconds for readability
    start_sec = segment.target_timerange.start / 1_000_000
    duration_sec = segment.target_timerange.duration / 1_000_000
    end_sec = segment.target_timerange.end / 1_000_000

    result: Dict[str, Any] = {
        "id": segment.segment_id,
        "type": type(segment).__name__,
        "start_time": round(start_sec, 3),
        "duration": round(duration_sec, 3),
        "end_time": round(end_sec, 3),
    }

    # MediaSegment properties (Audio, Video, Sticker, Text all inherit from this)
    if isinstance(segment, MediaSegment):
        result["volume"] = segment.volume
        result["speed"] = segment.speed.speed

    # VisualSegment properties (Video, Sticker, Text)
    if isinstance(segment, VisualSegment):
        result["clip"] = export_clip_settings_for_llm(segment)

    # VideoSegment specific
    if isinstance(segment, VideoSegment):
        if hasattr(segment, "material_instance") and segment.material_instance:
            result["material"] = {
                "name": getattr(segment.material_instance, "name", None),
                "path": getattr(segment.material_instance, "path", None),
                "width": getattr(segment.material_instance, "width", None),
                "height": getattr(segment.material_instance, "height", None),
            }
        # Include keyframes if present
        if segment.common_keyframes:
            result["keyframes"] = [
                {
                    "property": kf_list.keyframe_property.name,
                    "values": [
                        {
                            "time_offset": round(kf.time_offset / 1_000_000, 3),
                            "value": kf.value,
                        }
                        for kf in kf_list.keyframes
                    ],
                }
                for kf_list in segment.common_keyframes
            ]

    # Text_segment specific
    elif isinstance(segment, Text_segment):
        result["text"] = segment.text
        if segment.font:
            result["font"] = segment.font.name
        if segment.style:
            result["style"] = {
                "size": segment.style.size,
                "color": segment.style.color,
                "bold": segment.style.bold,
                "italic": segment.style.italic,
            }

    # AudioSegment specific
    elif isinstance(segment, AudioSegment):
        if hasattr(segment, "material_instance") and segment.material_instance:
            result["material"] = {
                "name": getattr(segment.material_instance, "name", None),
                "path": getattr(segment.material_instance, "path", None),
            }
        if hasattr(segment, "fade") and segment.fade:
            result["fade"] = {
                "in_duration": round(segment.fade.in_duration / 1_000_000, 3),
                "out_duration": round(segment.fade.out_duration / 1_000_000, 3),
            }

    # StickerSegment specific
    elif isinstance(segment, StickerSegment):
        result["resource_id"] = segment.resource_id

    return result


def export_track_for_llm(track: Track, include_segments: bool = True) -> Dict[str, Any]:
    """
    Export a track in LLM-friendly format.

    Args:
        track: The track to export
        include_segments: Whether to include full segment details (default True)

    Returns:
        Dictionary with only LLM-relevant fields:
        - name: Track name for identification
        - type: Track type (video, audio, text, etc.)
        - mute: Whether the track is muted
        - segment_count: Number of segments
        - end_time: Track end time in seconds
        - segments: List of segment data (if include_segments=True)
    """
    result: Dict[str, Any] = {
        "name": track.name,
        "type": track.track_type.name,
        "mute": track.mute,
        "segment_count": len(track.segments),
        "end_time": round(track.end_time / 1_000_000, 3),
    }

    if include_segments:
        result["segments"] = [export_segment_for_llm(seg) for seg in track.segments]

    return result


def export_tracks_for_llm(
    tracks: Dict[str, Track],
    imported_tracks: Optional[List[Track]] = None,
    include_segments: bool = True,
) -> Dict[str, Any]:
    """
    Export all tracks in LLM-friendly format.

    Args:
        tracks: Dictionary of regular tracks
        imported_tracks: List of imported tracks (optional)
        include_segments: Whether to include full segment details (default True)

    Returns:
        Dictionary containing:
        - tracks: List of track data
        - imported_tracks: List of imported track data
        - total_tracks: Total count
    """
    tracks_list = [
        export_track_for_llm(track, include_segments) for track in tracks.values()
    ]

    imported_list = []
    if imported_tracks:
        imported_list = [
            export_track_for_llm(track, include_segments) for track in imported_tracks
        ]

    return {
        "tracks": tracks_list,
        "imported_tracks": imported_list,
        "total_tracks": len(tracks_list) + len(imported_list),
    }
