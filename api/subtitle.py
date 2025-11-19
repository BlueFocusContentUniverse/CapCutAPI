from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from services.add_subtitle_impl import add_subtitle_impl

router = APIRouter(tags=["subtitle"])


class AddSubtitleRequest(BaseModel):
    srt: str
    draft_id: Optional[str] = None
    time_offset: float = 0.0
    font: str = "思源粗宋"
    font_size: float = 5.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font_color: str = "#FFFFFF"
    align: int = 1
    vertical: bool = False
    alpha: float = 1.0
    border_alpha: float = 1.0
    border_color: str = "#000000"
    border_width: float = 0.0
    background_color: str = "#000000"
    background_style: int = 0
    background_alpha: float = 0.0
    transform_x: float = 0.0
    transform_y: float = -0.8
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    track_name: str = "subtitle"
    width: int = 1080
    height: int = 1920


@router.post("/add_subtitle")
@api_endpoint_logger
async def add_subtitle(request: AddSubtitleRequest):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.srt:
        result["error"] = "Hi, the required parameters 'srt' are missing."
        return result

    try:
        draft_result = add_subtitle_impl(
            srt_path=request.srt,
            draft_id=request.draft_id,
            track_name=request.track_name,
            time_offset=request.time_offset,
            font=request.font,
            font_size=request.font_size,
            bold=request.bold,
            italic=request.italic,
            underline=request.underline,
            font_color=request.font_color,
            align=request.align,
            vertical=request.vertical,
            alpha=request.alpha,
            border_alpha=request.border_alpha,
            border_color=request.border_color,
            border_width=request.border_width,
            background_color=request.background_color,
            background_style=request.background_style,
            background_alpha=request.background_alpha,
            transform_x=request.transform_x,
            transform_y=request.transform_y,
            scale_x=request.scale_x,
            scale_y=request.scale_y,
            rotation=request.rotation,
            width=request.width,
            height=request.height
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while processing subtitle: {e!s}."
        return result


