#!/usr/bin/env python3
"""
Streaming-capable MCP server for CapCut API tools.

This server reuses the tool registry and execution logic defined in
`mcp_server.py` but exposes them through the `mcp` FastMCP server,
which supports stdio and SSE (HTTP) transports.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.types as types
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from api.metadata import get_audio_effect_types_logic, get_font_types_logic
from db import init_db
from logging_utils import mcp_tool_logger

# pydantic is intentionally not required here for flat handlers
# Reuse tool schemas and executor from the existing implementation
from mcp_tools import TOOLS, execute_tool
from services.add_effect_impl import add_effect_impl
from services.add_text_impl import add_text_impl
from services.add_video_track import add_video_track
from services.create_draft import create_draft
from services.generate_video_impl import generate_video_impl
from services.segment_management import delete_segment, get_segment_details
from services.track_management import delete_track, get_track_details, get_tracks

# Load environment variables from .env file
env_file = Path(__file__).parent / ".env"
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO)
if env_file.exists():
    load_dotenv(env_file)
    logger.info(f"Loaded environment from: {env_file}")
else:
    logger.warning(f"Environment file not found: {env_file}")
    logger.info("Using default environment variables")


# Manual tool handlers with flattened parameters (required first)
@mcp_tool_logger("create_draft")
def tool_create_draft(width: int = 1080, height: int = 1920,framerate: float = 30.0, name: str = "mcp_draft", resource: str = "mcp") -> Dict[str, Any]:
    _, draft_id =  create_draft(width=width, height=height, framerate=framerate, name=name, resource=resource)
    return {
        "draft_id": draft_id,
    }

@mcp_tool_logger("batch_add_videos")
def tool_batch_add_videos(
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
    fade_in_duration: float = 0.0,
    fade_out_duration: float = 0.0,
    background_blur: Optional[int] = None,
) -> Dict[str, Any]:
    """Batch add multiple videos to the track."""
    if not videos:
        return {"success": False, "error": "videos array is empty"}

    outputs = []
    current_draft_id = draft_id

    for idx, video in enumerate(videos):
        video_url = video.get("video_url")
        if not video_url:
            logger.warning(f"Video at index {idx} is missing 'video_url', skipping.")
            continue

        video_start = video.get("start", 0)
        video_end = video.get("end", 0)
        video_target_start = video.get("target_start", 0)
        video_speed = video.get("speed", 1.0)
        mode = video.get("mode", "cover")
        duration = video.get("duration", None)
        target_duration = video.get("target_duration", None)

        result = add_video_track(
            video_url=video_url,
            start=video_start,
            end=video_end,
            mode=mode,
            target_duration=target_duration,
            target_start=video_target_start,
            draft_id=current_draft_id,
            transform_y=transform_y,
            scale_x=scale_x,
            scale_y=scale_y,
            transform_x=transform_x,
            speed=video_speed,
            track_name=track_name,
            relative_index=relative_index,
            duration=duration,
            intro_animation=intro_animation,
            intro_animation_duration=intro_animation_duration,
            outro_animation=outro_animation,
            outro_animation_duration=outro_animation_duration,
            combo_animation=combo_animation,
            combo_animation_duration=combo_animation_duration,
            transition=transition,
            transition_duration=transition_duration,
            volume=volume,
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
            fade_in_duration=fade_in_duration,
            fade_out_duration=fade_out_duration,
            background_blur=background_blur,
        )

        outputs.append({
            "video_url": video_url,
            "result": result
        })

        # Update draft_id for subsequent videos
        current_draft_id = result

    return {
        "success": True,
        "output": outputs,
        "final_draft_id": current_draft_id
    }


@mcp_tool_logger("add_video")
def tool_add_video(
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
    return add_video_track(
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
    )


@mcp_tool_logger("add_audio")
def tool_add_audio(
    audio_url: str,
    draft_id: str,
    start: float = 0,
    end: Optional[float] = None,
    target_start: float = 0,
    volume: float = 1.0,
    speed: float = 1.0,
    track_name: str = "audio_main",
    duration: Optional[float] = None,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "audio_url": audio_url,
        "draft_id": draft_id,
        "start": start,
        "end": end,
        "target_start": target_start,
        "volume": volume,
        "speed": speed,
        "track_name": track_name,
        "duration": duration,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return execute_tool("add_audio", arguments)


@mcp_tool_logger("batch_add_audios")
def tool_batch_add_audios(
    audios: List[Dict[str, Any]],
    draft_id: Optional[str] = None,
    volume: float = 1.0,
    track_name: str = "audio_main",
    effect_type: Optional[str] = None,
    effect_params: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Batch add multiple audios to the track."""
    from services.add_audio_track import add_audio_track
    
    if not audios:
        return {"success": False, "error": "audios array is empty"}

    sound_effects = None
    if effect_type is not None:
        sound_effects = [(effect_type, effect_params)]

    outputs = []
    current_draft_id = draft_id

    for idx, audio in enumerate(audios):
        audio_url = audio.get("audio_url")
        if not audio_url:
            logger.warning(f"Audio at index {idx} is missing 'audio_url', skipping.")
            continue

        audio_start = audio.get("start", 0)
        audio_end = audio.get("end", None)
        audio_target_start = audio.get("target_start", 0)
        audio_speed = audio.get("speed", 1.0)
        audio_duration = audio.get("duration", None)

        result = add_audio_track(
            audio_url=audio_url,
            start=audio_start,
            end=audio_end,
            target_start=audio_target_start,
            draft_id=current_draft_id,
            volume=volume,
            track_name=track_name,
            speed=audio_speed,
            sound_effects=sound_effects,
            duration=audio_duration
        )

        outputs.append({
            "audio_url": audio_url,
            "result": result
        })

        # Update draft_id for subsequent audios
        current_draft_id = result

    return {
        "success": True,
        "output": outputs,
        "final_draft_id": current_draft_id
    }


@mcp_tool_logger("add_image")
def tool_add_image(
    image_url: str,
    draft_id: str,
    start: float = 0,
    end: float = 3.0,
    transform_x: float = 0,
    transform_y: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    track_name: str = "main",
    intro_animation: Optional[str] = None,
    outro_animation: Optional[str] = None,
    transition: Optional[str] = None,
    mask_type: Optional[str] = None,
) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {
        "image_url": image_url,
        "draft_id": draft_id,
        "start": start,
        "end": end,
        "transform_x": transform_x,
        "transform_y": transform_y,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "track_name": track_name,
        "intro_animation": intro_animation,
        "outro_animation": outro_animation,
        "transition": transition,
        "mask_type": mask_type,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return execute_tool("add_image", arguments)


@mcp_tool_logger("add_text")
def tool_add_text(
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
    fixed_width: float = 0.7,
    fixed_height: float = -1,
    align: int = 1,
    border_width: float = 0.0,
    border_color: str = "#000000",
    border_alpha: float = 1.0,
    vertical: bool = False,
    font_alpha: float = 1.0,
    shadow_enabled: bool = False,
    shadow_color: str = "#000000",
    shadow_alpha: float = 0.8,
    shadow_angle: float = 315.0,
    shadow_distance: float = 5.0,
    shadow_smoothing: float = 0.0,
    intro_animation: Optional[str] = None,
    intro_duration: float = 0.5,
    outro_animation: Optional[str] = None,
    outro_duration: float = 0.5,
    background_color: Optional[str] = None,
    background_alpha: float = 1.0,
    background_style: int = 0,
    background_round_radius: float = 0.0,
    text_styles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return add_text_impl(
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
        text_styles=text_styles,
        fixed_width=fixed_width,
        fixed_height=fixed_height,
    )


@mcp_tool_logger("add_subtitle")
def tool_add_subtitle(
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
    return execute_tool("add_subtitle", arguments)


@mcp_tool_logger("add_effect")
def tool_add_effect(
    effect_type: str,
    draft_id: str,
    effect_category: str = "scene",
    start: float = 0,
    end: float = 3.0,
    track_name: str = "effect_01",
    params: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    return add_effect_impl(
        effect_type=effect_type,
        effect_category=effect_category,
        draft_id=draft_id,
        start=start,
        end=end,
        track_name=track_name,
        params=params,
    )


@mcp_tool_logger("add_sticker")
def tool_add_sticker(
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
    return execute_tool("add_sticker", arguments)


@mcp_tool_logger("add_video_keyframe")
def tool_add_video_keyframe(
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
    return execute_tool("add_video_keyframe", arguments)


@mcp_tool_logger("generate_video")
def tool_generate_video(
    draft_id: str,
    resolution: str = "1080p",
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
    return generate_video_impl(**arguments)


@mcp_tool_logger("get_video_task_status")
def tool_get_video_task_status(task_id: str) -> Dict[str, Any]:
    """Get the status of a video generation task."""
    from services.get_video_task_status_impl import get_video_task_status_impl
    return get_video_task_status_impl(task_id=task_id)


@mcp_tool_logger("get_font_types")
def tool_get_font_types() -> Dict[str, Any]:
    """Fetch available font types."""
    return get_font_types_logic()


@mcp_tool_logger("get_audio_effect_types")
def tool_get_audio_effect_types() -> Dict[str, Any]:
    """Fetch available audio effect types."""
    return get_audio_effect_types_logic()


@mcp_tool_logger("get_tracks")
def tool_get_tracks(draft_id: str) -> Dict[str, Any]:
    """Get all tracks from a draft."""
    return get_tracks(draft_id=draft_id)


@mcp_tool_logger("delete_track")
def tool_delete_track(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Delete a track from a draft."""
    return delete_track(draft_id=draft_id, track_name=track_name)


@mcp_tool_logger("get_track_details")
def tool_get_track_details(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Get detailed information about a specific track."""
    return get_track_details(draft_id=draft_id, track_name=track_name)


@mcp_tool_logger("get_segment_details")
def tool_get_segment_details(draft_id: str, track_name: str, segment_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific segment."""
    return get_segment_details(draft_id=draft_id, track_name=track_name, segment_id=segment_id)


@mcp_tool_logger("delete_segment")
def tool_delete_segment(
    draft_id: str,
    track_name: str,
    segment_index: Optional[int] = None,
    segment_id: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a segment from a track by index or ID."""
    return delete_segment(
        draft_id=draft_id,
        track_name=track_name,
        segment_index=segment_index,
        segment_id=segment_id
    )


def _register_tools(app: FastMCP) -> None:
    """Register tools with explicit flat-parameter handlers."""
    app.add_tool(
        tool_create_draft, name="create_draft", description="创建新的CapCut草稿"
    )
    app.add_tool(
        tool_batch_add_videos,
        name="batch_add_videos",
        description="批量添加多个视频到草稿，每个视频可独立设置video_url、start、end、target_start、speed，其他参数共享",
    )
    app.add_tool(
        tool_add_video,
        name="add_video",
        description="添加视频到草稿，支持转场、蒙版、背景模糊等效果",
    )
    app.add_tool(
        tool_add_audio, name="add_audio", description="添加音频到草稿，支持音效处理"
    )
    app.add_tool(
        tool_batch_add_audios,
        name="batch_add_audios",
        description="批量添加多个音频到草稿，每个音频可独立设置audio_url、start、end、target_start、speed、duration，其他参数共享",
    )
    app.add_tool(
        tool_add_image,
        name="add_image",
        description="添加图片到草稿，支持动画、转场、蒙版等效果",
    )
    app.add_tool(
        tool_add_text,
        name="add_text",
        description="添加文本到草稿，支持文本多样式、文字阴影和文字背景",
    )
    app.add_tool(
        tool_add_subtitle,
        name="add_subtitle",
        description="添加字幕到草稿，支持SRT文件和样式设置",
    )
    app.add_tool(tool_add_effect, name="add_effect", description="添加特效到草稿")
    app.add_tool(tool_add_sticker, name="add_sticker", description="添加贴纸到草稿")
    app.add_tool(
        tool_add_video_keyframe,
        name="add_video_keyframe",
        description="添加视频关键帧，支持属性动画",
    )
    app.add_tool(tool_generate_video, name="generate_video", description="生成渲染视频")
    app.add_tool(
        tool_get_video_task_status,
        name="get_video_task_status",
        description="查询视频渲染任务状态"
    )
    app.add_tool(
        tool_get_font_types, name="get_font_types", description="获取字体类型列表"
    )
    app.add_tool(
        tool_get_audio_effect_types,
        name="get_audio_effect_types",
        description="获取音频特效类型列表",
    )
    app.add_tool(
        tool_get_tracks,
        name="get_tracks",
        description="获取草稿中的所有轨道信息",
    )
    app.add_tool(
        tool_delete_track,
        name="delete_track",
        description="从草稿中删除指定的轨道",
    )
    app.add_tool(
        tool_get_track_details,
        name="get_track_details",
        description="获取指定轨道的详细信息",
    )
    app.add_tool(
        tool_get_segment_details,
        name="get_segment_details",
        description="获取指定片段的详细信息",
    )
    app.add_tool(
        tool_delete_segment,
        name="delete_segment",
        description="从轨道中删除指定的片段",
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


# def create_fastmcp_app(host: str = "127.0.0.1", port: int = 3333, path: str = "/mcp") -> FastMCP:
#     """Factory to create a FastMCP app with tools registered and list_tools overridden."""
#     app = FastMCP("capcut-api", host=host, port=port, streamable_http_path=path)
#     _register_tools(app)
#     _override_list_tools(app)
#     _register_prompts(app)
#     _register_resources(app)
#     return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Streaming-capable MCP server for CapCut API"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="streamable host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=3333, help="streamable port (default: 3333)"
    )
    args = parser.parse_args()

    try:
        init_db()
        logger.info("Database initialization successful")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    app = FastMCP("capcut-api", host=args.host, port=args.port)
    _register_tools(app)
    _override_list_tools(app)
    _register_prompts(app)
    _register_resources(app)

    print(
        f"Starting CapCut FastMCP SSE server on http://{args.host}:{args.port}",
        file=sys.stderr,
    )
    app.run(transport="streamable-http", mount_path="/streamable")


if __name__ == "__main__":
    main()
