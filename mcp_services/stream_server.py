#!/usr/bin/env python3
"""
Streaming-capable MCP server for CapCut API tools.

This server reuses the tool registry and execution logic defined in
`mcp_server.py` but exposes them through the `mcp` FastMCP server,
which supports stdio and SSE (HTTP) transports.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import mcp.types as types
from fastmcp import FastMCP

# pydantic is intentionally not required here for flat handlers
# Reuse tool schemas and executor from the existing implementation
from mcp_services.mcp_tools import TOOLS
from services.add_audio_track import add_audio_track, batch_add_audio_track
from services.add_effect_impl import add_effect_impl
from services.add_image_impl import add_image_impl
from services.add_sticker_impl import add_sticker_impl
from services.add_subtitle_impl import add_subtitle_impl
from services.add_text_impl import add_text_impl
from services.add_video_keyframe_impl import add_video_keyframe_impl
from services.add_video_track import add_video_track, batch_add_video_track
from services.create_draft import create_draft
from services.generate_video_impl import generate_video_impl
from services.get_audio_effect_types_impl import get_audio_effect_types_impl
from services.get_font_types_impl import get_font_types_impl
from services.segment_management import (
    delete_segment,
    get_segment_details,
    modify_segment,
)
from services.track_management import delete_track, get_track_details, get_tracks

logger = logging.getLogger(__name__)


# Manual tool handlers with flattened parameters (required first)
async def tool_create_draft(
    width: int = 1080,
    height: int = 1920,
    framerate: float = 30.0,
    name: str = "mcp_draft",
    resource: str = "mcp",
) -> Dict[str, Any]:
    _, draft_id = await create_draft(
        width=width, height=height, framerate=framerate, name=name, resource=resource
    )
    return {
        "draft_id": draft_id,
    }


async def tool_batch_add_videos(
    videos: List[Dict[str, Any]],
    draft_id: Optional[str] = None,
    transform_x: float = 0,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    track_name: str = "main",
    relative_index: int = 0,
    transition: Optional[str] = None,
    transition_duration: float = 0.5,
    volume: float = 1.0,
    intro_animation: Optional[str] = None,
    intro_animation_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_animation_duration: float = 0.5,
    combo_animation: Optional[str] = None,
    combo_animation_duration: float = 0.5,
    mask_type: Optional[str] = None,
    mask_center_x: float = 0.5,
    mask_center_y: float = 0.5,
    mask_size: float = 1.0,
    mask_rotation: float = 0.0,
    mask_feather: float = 0.0,
    mask_invert: bool = False,
    mask_rect_width: Optional[float] = None,
    mask_round_corner: Optional[float] = None,
    filter_type: Optional[str] = None,
    filter_intensity: float = 100.0,
    background_blur: Optional[int] = None,
) -> Dict[str, Any]:
    """Batch add multiple videos to the track."""
    if not videos:
        error_obj = {"code": "invalid_input", "message": "videos array is empty"}
        logger.error(error_obj["message"])
        raise RuntimeError(json.dumps(error_obj))

    try:
        batch_result = await batch_add_video_track(
            videos=videos,
            draft_folder=None,
            draft_id=draft_id,
            transform_y=transform_y,
            scale_x=scale_x,
            scale_y=scale_y,
            transform_x=transform_x,
            track_name=track_name,
            relative_index=relative_index,
            transition=transition,
            transition_duration=transition_duration,
            volume=volume,
            intro_animation=intro_animation,
            intro_animation_duration=intro_animation_duration,
            outro_animation=outro_animation,
            outro_animation_duration=outro_animation_duration,
            combo_animation=combo_animation,
            combo_animation_duration=combo_animation_duration,
            mask_type=mask_type,
            mask_center_x=mask_center_x,
            mask_center_y=mask_center_y,
            mask_size=mask_size,
            mask_rotation=mask_rotation,
            mask_feather=mask_feather,
            mask_invert=mask_invert,
            mask_rect_width=mask_rect_width,
            mask_round_corner=mask_round_corner,
            filter_type=filter_type,
            filter_intensity=filter_intensity,
            background_blur=background_blur,
            default_mode="cover",
        )
    except Exception as exc:
        logger.error(f"Failed to batch add videos: {exc}", exc_info=True)
        err = {"code": "exception", "message": str(exc)}
        raise RuntimeError(json.dumps(err)) from exc

    outputs = batch_result.get("outputs")
    skipped = batch_result.get("skipped")
    draft_id = batch_result.get("draft_id")

    # If some videos were skipped, treat the result as an error response to signal attention is needed.
    if skipped:
        skipped_descriptions = [
            entry.get("video_url") or f"index {entry.get('index')}" for entry in skipped
        ]
        error_obj = {
            "code": "skipped_items",
            "message": "Skipped videos",
            "skipped": skipped_descriptions,
            "draft_id": draft_id,
        }
        logger.warning(error_obj["message"] + ": " + str(skipped_descriptions))
        raise RuntimeError(json.dumps(error_obj))

    return {
        "success": True,
        "output": outputs,
        "draft_id": draft_id,
        "skipped": skipped,
    }


async def tool_add_video(
    video_url: str,
    draft_id: str,
    start: float = 0,
    end: Optional[float] = None,
    mode: str = "cover",
    target_duration: Optional[float] = None,
    duration: Optional[float] = None,
    target_start: float = 0,
    transform_x: float = 0,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    speed: float = 1.0,
    track_name: str = "main",
    video_name: Optional[str] = None,
    volume: float = 1.0,
    transition: Optional[str] = None,
    transition_duration: float = 0.5,
    mask_type: Optional[str] = None,
    background_blur: Optional[int] = None,
    intro_animation: Optional[str] = None,
    intro_animation_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_animation_duration: float = 0.5,
    combo_animation: Optional[str] = None,
    combo_animation_duration: float = 0.5,
) -> Dict[str, str]:
    return await add_video_track(
        video_url=video_url,
        draft_id=draft_id,
        start=start,
        end=end,
        mode=mode,
        target_duration=target_duration,
        duration=duration,
        target_start=target_start,
        transform_x=transform_x,
        transform_y=transform_y,
        scale_x=scale_x,
        scale_y=scale_y,
        speed=speed,
        track_name=track_name,
        volume=volume,
        transition=transition,
        transition_duration=transition_duration,
        mask_type=mask_type,
        background_blur=background_blur,
        intro_animation=intro_animation,
        intro_animation_duration=intro_animation_duration,
        outro_animation=outro_animation,
        outro_animation_duration=outro_animation_duration,
        combo_animation=combo_animation,
        combo_animation_duration=combo_animation_duration,
        video_name=video_name,
    )


async def tool_add_audio(
    audio_url: str,
    draft_id: str,
    start: float = 0,
    end: Optional[float] = None,
    target_start: float = 0,
    volume: float = 1.0,
    speed: float = 1.0,
    audio_name: Optional[str] = None,
    track_name: str = "audio_main",
    duration: Optional[float] = None,
    effect_type: Optional[str] = None,
    effect_params: Optional[List[float]] = None,
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
) -> Dict[str, Any]:
    sound_effects = []
    if effect_type:
        params = effect_params if effect_params is not None else []
        sound_effects.append((effect_type, params))

    return await add_audio_track(
        audio_url=audio_url,
        draft_id=draft_id,
        start=start,
        end=end,
        target_start=target_start,
        volume=volume,
        speed=speed,
        track_name=track_name,
        duration=duration,
        sound_effects=sound_effects if sound_effects else None,
        audio_name=audio_name,
        fade_in_duration=fade_in_duration,
        fade_out_duration=fade_out_duration,
    )


async def tool_batch_add_audios(
    audios: List[Dict[str, Any]],
    draft_id: Optional[str] = None,
    volume: float = 1.0,
    track_name: str = "audio_main",
    effect_type: Optional[str] = None,
    effect_params: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Batch add multiple audios to the track."""
    if not audios:
        error_obj = {"code": "invalid_input", "message": "audios array is empty"}
        logger.error(error_obj["message"])
        raise RuntimeError(json.dumps(error_obj))

    sound_effects = None
    if effect_type is not None:
        sound_effects = [(effect_type, effect_params)]

    try:
        batch_result = await batch_add_audio_track(
            audios=audios,
            draft_folder=None,
            draft_id=draft_id,
            volume=volume,
            track_name=track_name,
            speed=1.0,
            sound_effects=sound_effects,
        )
    except Exception as exc:
        logger.error(f"Failed to batch add audios: {exc}", exc_info=True)
        err = {"code": "exception", "message": str(exc)}
        raise RuntimeError(json.dumps(err)) from exc

    outputs = batch_result.get("outputs")
    skipped = batch_result.get("skipped")
    draft_id = batch_result.get("draft_id")

    # If some audios were skipped, treat the result as an error response to signal attention is needed.
    if skipped:
        skipped_descriptions = [
            entry.get("audio_url") or f"index {entry.get('index')}" for entry in skipped
        ]
        error_obj = {
            "code": "skipped_items",
            "message": "Skipped audios",
            "skipped": skipped_descriptions,
            "draft_id": draft_id,
        }
        logger.warning(error_obj["message"] + ": " + str(skipped_descriptions))
        raise RuntimeError(json.dumps(error_obj))

    return {
        "success": True,
        "output": outputs,
        "draft_id": draft_id,
        "skipped": skipped,
    }


async def tool_add_image(
    image_url: str,
    image_name: str,
    draft_id: str,
    start: float = 0,
    end: float = 3.0,
    transform_x: float = 0,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    track_name: str = "main",
    relative_index: int = 0,
    intro_animation: Optional[str] = None,
    intro_animation_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_animation_duration: float = 0.5,
    combo_animation: Optional[str] = None,
    combo_animation_duration: float = 0.5,
    transition: Optional[str] = None,
    transition_duration: float = 0.5,
    mask_type: Optional[str] = None,
    mask_center_x: float = 0.0,
    mask_center_y: float = 0.0,
    mask_size: float = 0.5,
    mask_rotation: float = 0.0,
    mask_feather: float = 0.0,
    mask_invert: bool = False,
    mask_rect_width: Optional[float] = None,
    mask_round_corner: Optional[float] = None,
    background_blur: Optional[int] = None,
) -> Dict[str, Any]:
    return await add_image_impl(
        image_url=image_url,
        image_name=image_name,
        draft_id=draft_id,
        start=start,
        end=end,
        transform_x=transform_x,
        transform_y=transform_y,
        scale_x=scale_x,
        scale_y=scale_y,
        track_name=track_name,
        intro_animation=intro_animation,
        outro_animation=outro_animation,
        relative_index=relative_index,
        intro_animation_duration=intro_animation_duration,
        outro_animation_duration=outro_animation_duration,
        combo_animation=combo_animation,
        combo_animation_duration=combo_animation_duration,
        transition=transition,
        transition_duration=transition_duration,
        mask_type=mask_type,
        mask_center_x=mask_center_x,
        mask_center_y=mask_center_y,
        mask_size=mask_size,
        mask_rotation=mask_rotation,
        mask_feather=mask_feather,
        mask_invert=mask_invert,
        mask_rect_width=mask_rect_width,
        mask_round_corner=mask_round_corner,
        background_blur=background_blur,
    )


async def tool_add_text(
    text: str,
    start: float,
    end: float,
    draft_id: str,
    transform_y: float = -0.8,
    transform_x: float = 0,
    track_name: str = "text_main",
    font: Optional[str] = None,
    font_color: str = "#ffffff",
    font_size: int = 24,
    fixed_width: float = 0.9,
    fixed_height: float = -1,
    align: int = 1,
    border_width: float = 0.0,
    border_color: str = "#000000",
    border_alpha: float = 1.0,
    vertical: bool = False,
    font_alpha: float = 1.0,
    shadow_enabled: bool = False,
    shadow_color: str = "#000000",
    shadow_alpha: float = 0.76,
    shadow_angle: float = -54.0,
    shadow_distance: float = 5.0,
    shadow_smoothing: float = 0.22,
    intro_animation: Optional[str] = None,
    intro_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_duration: float = 0.5,
    background_color: Optional[str] = "#000000",
    background_alpha: float = 0,
    background_style: int = 0,
    background_round_radius: float = 0.0,
    background_height: float = 0.14,
    background_width: float = 0.14,
    background_horizontal_offset: float = 0.5,
    background_vertical_offset: float = 0.5,
    italic: bool = False,
    bold: bool = False,
    underline: bool = False,
    text_styles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return await add_text_impl(
        text=text,
        start=start,
        end=end,
        draft_id=draft_id,
        font=font,
        font_color=font_color,
        font_size=font_size,
        border_alpha=border_alpha,
        border_width=border_width,
        border_color=border_color,
        track_name=track_name,
        align=align,
        vertical=vertical,
        transform_y=transform_y,
        transform_x=transform_x,
        font_alpha=font_alpha,
        shadow_enabled=shadow_enabled,
        shadow_color=shadow_color,
        shadow_alpha=shadow_alpha,
        shadow_angle=shadow_angle,
        shadow_distance=shadow_distance,
        shadow_smoothing=shadow_smoothing,
        intro_animation=intro_animation,
        intro_duration=intro_duration,
        outro_animation=outro_animation,
        outro_duration=outro_duration,
        background_color=background_color,
        background_alpha=background_alpha,
        background_style=background_style,
        background_round_radius=background_round_radius,
        background_height=background_height,
        background_width=background_width,
        background_horizontal_offset=background_horizontal_offset,
        background_vertical_offset=background_vertical_offset,
        text_styles=text_styles,
        fixed_width=fixed_width,
        fixed_height=fixed_height,
        italic=italic,
        bold=bold,
        underline=underline,
    )


async def tool_add_subtitle(
    srt_path: str,
    draft_id: str,
    track_name: str = "subtitle",
    time_offset: float = 0,
    font: Optional[str] = None,
    font_size: float = 8.0,
    font_color: str = "#FFFFFF",
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    border_width: float = 0.0,
    border_color: str = "#000000",
    background_color: str = "#000000",
    background_alpha: float = 0.0,
    transform_x: float = 0.0,
    transform_y: float = -0.8,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "srt_path": srt_path,
        "draft_id": draft_id,
        "track_name": track_name,
        "time_offset": time_offset,
        "font": font,
        "font_size": font_size,
        "font_color": font_color,
        "bold": bold,
        "italic": italic,
        "underline": underline,
        "border_width": border_width,
        "border_color": border_color,
        "background_color": background_color,
        "background_alpha": background_alpha,
        "transform_x": transform_x,
        "transform_y": transform_y,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return await add_subtitle_impl(**arguments)


async def tool_add_effect(
    effect_type: str,
    draft_id: str,
    effect_category: str = "scene",
    start: float = 0,
    end: float = 3.0,
    track_name: str = "effect_01",
    params: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    return await add_effect_impl(
        effect_type=effect_type,
        effect_category=effect_category,
        draft_id=draft_id,
        start=start,
        end=end,
        track_name=track_name,
        params=params,
    )


async def tool_add_sticker(
    resource_id: str,
    start: float,
    end: float,
    draft_id: str,
    transform_x: float = 0,
    transform_y: float = 0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    alpha: float = 1.0,
    rotation: float = 0.0,
    track_name: str = "sticker_main",
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "resource_id": resource_id,
        "draft_id": draft_id,
        "start": start,
        "end": end,
        "transform_x": transform_x,
        "transform_y": transform_y,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "alpha": alpha,
        "rotation": rotation,
        "track_name": track_name,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return await add_sticker_impl(**arguments)


async def tool_add_video_keyframe(
    draft_id: str,
    track_name: str = "main",
    property_type: Optional[str] = None,
    time: float = 0.0,
    value: Optional[str] = None,
    property_types: Optional[List[str]] = None,
    times: Optional[List[float]] = None,
    values: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "draft_id": draft_id,
        "track_name": track_name,
        "property_type": property_type,
        "time": time,
        "value": value,
        "property_types": property_types,
        "times": times,
        "values": values,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return await add_video_keyframe_impl(**arguments)


async def tool_generate_video(
    draft_id: str,
    resolution: str = "1080P",
    framerate: str = "30fps",
    name: Optional[str] = None,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "draft_id": draft_id,
        "resolution": resolution,
        "framerate": framerate,
        "name": name,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return await generate_video_impl(**arguments)


async def tool_regenerate_video(task_id: str) -> Dict[str, Any]:
    """重新生成视频，使用现有的task_id."""
    from services.regenerate_video_impl import regenerate_video_impl

    return await regenerate_video_impl(task_id=task_id)


async def tool_get_video_task_status(task_id: str) -> Dict[str, Any]:
    """Get the status of a video generation task."""
    from services.get_video_task_status_impl import get_video_task_status_impl

    return await get_video_task_status_impl(task_id=task_id)


def tool_get_font_types() -> Dict[str, Any]:
    """Fetch available font types."""
    return get_font_types_impl()


def tool_get_audio_effect_types() -> Dict[str, Any]:
    """Fetch available audio effect types."""
    return get_audio_effect_types_impl()


async def tool_get_tracks(draft_id: str) -> Dict[str, Any]:
    """Get all tracks from a draft."""
    return await get_tracks(draft_id=draft_id)


async def tool_delete_track(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Delete a track from a draft."""
    return await delete_track(draft_id=draft_id, track_name=track_name)


async def tool_get_track_details(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Get detailed information about a specific track."""
    return await get_track_details(draft_id=draft_id, track_name=track_name)


async def tool_get_segment_details(
    draft_id: str, track_name: str, segment_id: str
) -> Dict[str, Any]:
    """Get detailed information about a specific segment."""
    return await get_segment_details(
        draft_id=draft_id, track_name=track_name, segment_id=segment_id
    )


async def tool_delete_segment(
    draft_id: str,
    track_name: str,
    segment_index: Optional[int] = None,
    segment_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete a segment from a track by index or ID."""
    return await delete_segment(
        draft_id=draft_id,
        track_name=track_name,
        segment_index=segment_index,
        segment_id=segment_id,
    )


async def tool_modify_segment(
    draft_id: str,
    track_name: str,
    segment_id: str,
    alpha: Optional[float] = None,
    flip_horizontal: Optional[bool] = None,
    flip_vertical: Optional[bool] = None,
    rotation: Optional[float] = None,
    scale_x: Optional[float] = None,
    scale_y: Optional[float] = None,
    transform_x: Optional[float] = None,
    transform_y: Optional[float] = None,
    volume: Optional[float] = None,
    speed: Optional[float] = None,
) -> Dict[str, Any]:
    """Modify a segment's properties (clip settings, volume, speed).

    Args:
        draft_id: The draft ID containing the segment
        track_name: Name of the track containing the segment
        segment_id: ID of the segment to modify
        alpha: Opacity (0-1)
        flip_horizontal: Horizontal flip
        flip_vertical: Vertical flip
        rotation: Rotation angle in degrees
        scale_x: Horizontal scale
        scale_y: Vertical scale
        transform_x: Horizontal position
        transform_y: Vertical position
        volume: Audio volume level (0-2)
        speed: Playback speed multiplier

    Returns:
        Dictionary with success status and updated segment info
    """
    # Build clip_settings dict from individual parameters
    clip_settings: Optional[Dict[str, Any]] = None
    clip_params = {
        "alpha": alpha,
        "flip_horizontal": flip_horizontal,
        "flip_vertical": flip_vertical,
        "rotation": rotation,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "transform_x": transform_x,
        "transform_y": transform_y,
    }
    # Filter out None values
    clip_settings_filtered = {k: v for k, v in clip_params.items() if v is not None}
    if clip_settings_filtered:
        clip_settings = clip_settings_filtered

    # Validate that at least one parameter is provided
    if clip_settings is None and volume is None and speed is None:
        raise ValueError(
            "At least one of clip_settings parameters, volume, or speed must be provided"
        )

    return await modify_segment(
        draft_id=draft_id,
        track_name=track_name,
        segment_id=segment_id,
        clip_settings=clip_settings,
        volume=volume,
        speed=speed,
    )


def _register_tools(app: FastMCP) -> None:
    """Register tools with explicit flat-parameter handlers."""
    app.tool(tool_create_draft, name="create_draft", description="创建新的CapCut草稿")
    app.tool(
        tool_batch_add_videos,
        name="batch_add_videos",
        description="批量添加多个视频到草稿，每个视频可独立设置video_url、start、end、target_start、speed，其他参数共享",
    )
    app.tool(
        tool_add_video,
        name="add_video",
        description="添加视频到草稿，支持转场、蒙版、背景模糊等效果",
    )
    app.tool(
        tool_add_audio, name="add_audio", description="添加音频到草稿，支持音效处理"
    )
    app.tool(
        tool_batch_add_audios,
        name="batch_add_audios",
        description="批量添加多个音频到草稿，每个音频可独立设置audio_url、start、end、target_start、speed、duration，其他参数共享",
    )
    app.tool(
        tool_add_image,
        name="add_image",
        description="添加图片到草稿，支持动画、转场、蒙版等效果",
    )
    app.tool(
        tool_add_text,
        name="add_text",
        description="添加文本到草稿，支持文本多样式、文字阴影和文字背景",
    )
    app.tool(
        tool_add_subtitle,
        name="add_subtitle",
        description="添加字幕到草稿，支持SRT文件和样式设置",
    )
    app.tool(tool_add_effect, name="add_effect", description="添加特效到草稿")
    app.tool(tool_add_sticker, name="add_sticker", description="添加贴纸到草稿")
    app.tool(
        tool_add_video_keyframe,
        name="add_video_keyframe",
        description="添加视频关键帧，支持属性动画",
    )
    app.tool(tool_generate_video, name="generate_video", description="生成渲染视频")
    app.tool(
        tool_regenerate_video,
        name="regenerate_video",
        description="重新生成视频，使用现有的task_id",
    )
    app.tool(
        tool_get_video_task_status,
        name="get_video_task_status",
        description="查询视频渲染任务状态",
    )
    app.tool(tool_get_font_types, name="get_font_types", description="获取字体类型列表")
    app.tool(
        tool_get_audio_effect_types,
        name="get_audio_effect_types",
        description="获取音频特效类型列表",
    )
    app.tool(
        tool_get_tracks,
        name="get_tracks",
        description="获取草稿中的所有轨道信息",
    )
    app.tool(
        tool_delete_track,
        name="delete_track",
        description="从草稿中删除指定的轨道",
    )
    app.tool(
        tool_get_track_details,
        name="get_track_details",
        description="获取指定轨道的详细信息",
    )
    app.tool(
        tool_get_segment_details,
        name="get_segment_details",
        description="获取指定片段的详细信息",
    )
    app.tool(
        tool_delete_segment,
        name="delete_segment",
        description="从轨道中删除指定的片段",
    )
    app.tool(
        tool_modify_segment,
        name="modify_segment",
        description="修改片段属性，支持透明度、翻转、旋转、缩放、位移、音量、速度等调整",
    )


def _override_list_tools(app: FastMCP) -> None:
    """Override list_tools to include inputSchema from TOOLS (and optional outputSchema)."""
    tool_map: Dict[str, Dict[str, Any]] = {
        t.get("name", ""): t for t in TOOLS if t.get("name")
    }

    @app._mcp_server.list_tools()  # type: ignore[attr-defined]
    async def list_tools() -> list[types.Tool]:
        result: list[types.Tool] = []
        for name, spec in tool_map.items():
            result.append(
                types.Tool(
                    name=name,
                    description=spec.get("description", ""),
                    inputSchema=spec.get("inputSchema", {"type": "object"}),
                    outputSchema=spec.get("outputSchema"),
                )
            )
        return result


def _register_prompts(app: FastMCP) -> None:
    """Register and implement MCP prompts for FastMCP server."""

    @app.prompt(name="Capcut Quickstart", description="Capcut Quickstart guide")
    def quickstart(language: Optional[str] = None) -> str:
        lang = (language or "en").lower()
        if lang.startswith("zh"):
            return (
                "CapCut API 快速开始:\n"
                "1) 使用 create_draft 创建草稿。\n"
                "2) 使用 add_video / add_audio / add_image / add_text 添加素材。\n"
                "3) 使用 add_effect / add_sticker / add_video_keyframe 增强效果。\n"
                "4) 使用 generate_video 渲染输出。\n"
                "可用工具请先调用 list_tools 查询输入参数。"
            )
        return (
            "CapCut API Quickstart:\n"
            "1) Use create_draft to create a project.\n"
            "2) Add media via add_video / add_audio / add_image / add_text.\n"
            "3) Enhance with add_effect / add_sticker / add_video_keyframe.\n"
            "4) Render with generate_video.\n"
            "Call list_tools to see schemas for each tool."
        )


def _register_resources(app: FastMCP) -> None:
    """Register and implement MCP resources for FastMCP server."""

    @app.resource(
        "config://settings", name="Default settings", description="Default settings"
    )
    def default_settings() -> str:
        """Get application settings."""
        return """{
            "language": "zh",
        }"""


def create_fastmcp_app() -> FastMCP:
    """Factory to create a FastMCP app with tools registered and list_tools overridden."""
    app = FastMCP("capcut-api", version="1.9.0", stateless_http=True)
    _register_tools(app)
    _override_list_tools(app)
    _register_prompts(app)
    _register_resources(app)
    return app
