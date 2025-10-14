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
from flask import Flask
from mcp.server.fastmcp import FastMCP

from api.metadata import get_audio_effect_types, get_font_types
from db import init_db

# pydantic is intentionally not required here for flat handlers
# Reuse tool schemas and executor from the existing implementation
from mcp_tools import TOOLS, execute_tool
from services.add_effect_impl import add_effect_impl
from services.add_text_impl import add_text_impl
from services.add_video_track import add_video_track
from services.create_draft import get_or_create_draft
from services.generate_video_impl import generate_video_impl
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
def tool_create_draft(width: int = 1080, height: int = 1920,framerate: float = 30.0, name: str = "mcp_draft", resource: str = "mcp") -> Dict[str, Any]:
    draft_id, script =  get_or_create_draft(width=width, height=height, framerate=framerate, name=name, resource=resource)
    return {
        "draft_id": draft_id,
    }

def tool_add_video(
    video_url: str,
    draft_id: str,
    start: float = 0,
    end: Optional[float] = None,
    target_start: float = 0,
    width: int = 1080,
    height: int = 1920,
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
        target_start=target_start,
        width=width,
        height=height,
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


def tool_add_audio(
    audio_url: str,
    draft_id: str,
    start: float = 0,
    end: Optional[float] = None,
    target_start: float = 0,
    volume: float = 1.0,
    speed: float = 1.0,
    track_name: str = "audio_main",
    width: int = 1080,
    height: int = 1920,
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
        "width": width,
        "height": height,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return execute_tool("add_audio", arguments)


def tool_add_image(
    image_url: str,
    draft_id: str,
    start: float = 0,
    end: float = 3.0,
    width: int = 1080,
    height: int = 1920,
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
        "width": width,
        "height": height,
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
    align: int = 1,
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
    )


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
    width: int = 1080,
    height: int = 1920,
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
        "width": width,
        "height": height,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return execute_tool("add_subtitle", arguments)


def tool_add_effect(
    effect_type: str,
    draft_id: str,
    effect_category: str = "scene",
    start: float = 0,
    end: float = 3.0,
    track_name: str = "effect_01",
    params: Optional[List[Any]] = None,
    width: int = 1080,
    height: int = 1920,
) -> Dict[str, Any]:
    return add_effect_impl(
        effect_type=effect_type,
        effect_category=effect_category,
        draft_id=draft_id,
        start=start,
        end=end,
        track_name=track_name,
        params=params,
        width=width,
        height=height,
    )


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
    width: int = 1080,
    height: int = 1920,
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
        "width": width,
        "height": height,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    return execute_tool("add_sticker", arguments)


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


def tool_get_font_types() -> Dict[str, Any]:
    """Fetch available font types using the Flask view function."""
    app = Flask(__name__)
    with app.app_context():
        resp = get_font_types()
        try:
            return resp.get_json()
        except Exception as e:
            return {"success": False, "error": f"Failed to get font types: {e}"}


def tool_get_audio_effect_types() -> Dict[str, Any]:
    """Fetch available audio effect types using the Flask view function."""
    app = Flask(__name__)
    with app.app_context():
        resp = get_audio_effect_types()
        try:
            return resp.get_json()
        except Exception as e:
            return {"success": False, "error": f"Failed to get audio effect types: {e}"}


def tool_get_tracks(draft_id: str) -> Dict[str, Any]:
    """Get all tracks from a draft."""
    return get_tracks(draft_id=draft_id)


def tool_delete_track(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Delete a track from a draft."""
    return delete_track(draft_id=draft_id, track_name=track_name)


def tool_get_track_details(draft_id: str, track_name: str) -> Dict[str, Any]:
    """Get detailed information about a specific track."""
    return get_track_details(draft_id=draft_id, track_name=track_name)


def _register_tools(app: FastMCP) -> None:
    """Register tools with explicit flat-parameter handlers."""
    app.add_tool(
        tool_create_draft, name="create_draft", description="创建新的CapCut草稿"
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
