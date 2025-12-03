import logging
from typing import List, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from pyJianYingDraft.text_segment import Text_border, Text_style, TextStyleRange
from services.add_text_impl import add_text_impl
from util.helpers import hex_to_rgb

logger = logging.getLogger(__name__)
router = APIRouter(tags=["text"])

class TextStyleModel(BaseModel):
    size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    color: Optional[str] = None
    alpha: Optional[float] = None
    align: Optional[int] = None
    vertical: Optional[bool] = None
    letter_spacing: Optional[float] = None
    line_spacing: Optional[float] = None

class TextBorderModel(BaseModel):
    width: float = 0
    alpha: Optional[float] = None
    color: Optional[str] = None

class TextStyleRangeItem(BaseModel):
    start: int = 0
    end: int = 0
    style: Optional[TextStyleModel] = None
    border: Optional[TextBorderModel] = None
    font: Optional[str] = None

class AddTextRequest(BaseModel):
    text: str
    start: float = 0
    end: float = 5
    draft_id: Optional[str] = None
    transform_y: float = 0
    transform_x: float = 0
    font: str = "文轩体"
    font_color: Optional[str] = None
    color: Optional[str] = None # Alias for font_color
    font_size: Optional[float] = None
    size: Optional[float] = None # Alias for font_size
    track_name: str = "text_main"
    align: int = 1
    vertical: bool = False
    font_alpha: Optional[float] = None
    alpha: Optional[float] = None # Alias for font_alpha

    fixed_width: float = -1
    fixed_height: float = -1

    border_alpha: float = 1.0
    border_color: str = "#000000"
    border_width: float = 0.0

    background_color: str = "#000000"
    background_style: int = 0
    background_alpha: float = 0.0
    background_round_radius: float = 0.0
    background_height: float = 0.14
    background_width: float = 0.14
    background_horizontal_offset: float = 0.5
    background_vertical_offset: float = 0.5

    shadow_enabled: bool = False
    shadow_alpha: float = 0.76
    shadow_angle: float = -54.0
    shadow_color: str = "#000000"
    shadow_distance: float = 5.0
    shadow_smoothing: float = 0.22

    bubble_effect_id: Optional[str] = None
    bubble_resource_id: Optional[str] = None
    effect_effect_id: Optional[str] = None

    intro_animation: Optional[str] = None
    intro_duration: float = 0.5

    outro_animation: Optional[str] = None
    outro_duration: float = 0.5

    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None

    text_styles: List[TextStyleRangeItem] = []

@router.post("/add_text")
def add_text(request: AddTextRequest, response: Response):
    # Handle aliases
    font_color = request.color if request.color is not None else (request.font_color if request.font_color is not None else "#FFFFFF")
    font_size = request.size if request.size is not None else (request.font_size if request.font_size is not None else 8.0)
    font_alpha = request.alpha if request.alpha is not None else (request.font_alpha if request.font_alpha is not None else 1.0)

    text_styles = None
    if request.text_styles:
        text_styles = []
        for style_data in request.text_styles:
            style_model = style_data.style or TextStyleModel()

            style = Text_style(
                size=style_model.size if style_model.size is not None else font_size,
                bold=style_model.bold if style_model.bold is not None else False,
                italic=style_model.italic if style_model.italic is not None else False,
                underline=style_model.underline if style_model.underline is not None else False,
                color=hex_to_rgb(style_model.color if style_model.color is not None else font_color),
                alpha=style_model.alpha if style_model.alpha is not None else font_alpha,
                align=style_model.align if style_model.align is not None else 1,
                vertical=style_model.vertical if style_model.vertical is not None else request.vertical,
                letter_spacing=style_model.letter_spacing if style_model.letter_spacing is not None else 0,
                line_spacing=style_model.line_spacing if style_model.line_spacing is not None else 0
            )

            border = None
            border_model = style_data.border
            if border_model and border_model.width > 0:
                border = Text_border(
                    alpha=border_model.alpha if border_model.alpha is not None else request.border_alpha,
                    color=hex_to_rgb(border_model.color if border_model.color is not None else request.border_color),
                    width=border_model.width
                )

            style_range = TextStyleRange(
                start=style_data.start,
                end=style_data.end,
                style=style,
                border=border,
                font_str=style_data.font if style_data.font is not None else request.font
            )

            text_styles.append(style_range)

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = add_text_impl(
            text=request.text,
            start=request.start,
            end=request.end,
            draft_id=request.draft_id,
            transform_y=request.transform_y,
            transform_x=request.transform_x,
            font=request.font,
            font_color=font_color,
            font_size=font_size,
            track_name=request.track_name,
            align=request.align,
            vertical=request.vertical,
            font_alpha=font_alpha,
            border_alpha=request.border_alpha,
            border_color=request.border_color,
            border_width=request.border_width,
            background_color=request.background_color,
            background_style=request.background_style,
            background_alpha=request.background_alpha,
            background_round_radius=request.background_round_radius,
            background_height=request.background_height,
            background_width=request.background_width,
            background_horizontal_offset=request.background_horizontal_offset,
            background_vertical_offset=request.background_vertical_offset,
            shadow_enabled=request.shadow_enabled,
            shadow_alpha=request.shadow_alpha,
            shadow_angle=request.shadow_angle,
            shadow_color=request.shadow_color,
            shadow_distance=request.shadow_distance,
            shadow_smoothing=request.shadow_smoothing,
            bubble_effect_id=request.bubble_effect_id,
            bubble_resource_id=request.bubble_resource_id,
            effect_effect_id=request.effect_effect_id,
            intro_animation=request.intro_animation,
            intro_duration=request.intro_duration,
            outro_animation=request.outro_animation,
            outro_duration=request.outro_duration,
            fixed_width=request.fixed_width,
            fixed_height=request.fixed_height,
            text_styles=text_styles,
            bold=request.bold,
            italic=request.italic,
            underline=request.underline
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while processing text: {e!s}."
        return result

