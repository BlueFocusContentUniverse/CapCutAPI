import logging
from typing import Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from services.add_image_impl import add_image_impl

logger = logging.getLogger(__name__)
router = APIRouter(tags=["image"])

class AddImageRequest(BaseModel):
    draft_folder: Optional[str] = None
    image_url: str
    image_name: Optional[str] = None
    start: float = 0
    end: float = 3.0
    draft_id: Optional[str] = None
    transform_y: float = 0
    scale_x: float = 1
    scale_y: float = 1
    transform_x: float = 0
    track_name: str = "image_main"
    relative_index: int = 0
    intro_animation: Optional[str] = None
    intro_animation_duration: float = 0.5
    outro_animation: Optional[str] = None
    outro_animation_duration: float = 0.5
    combo_animation: Optional[str] = None
    combo_animation_duration: float = 0.5
    transition: Optional[str] = None
    transition_duration: float = 0.5
    mask_type: Optional[str] = None
    mask_center_x: float = 0.0
    mask_center_y: float = 0.0
    mask_size: float = 0.5
    mask_rotation: float = 0.0
    mask_feather: float = 0.0
    mask_invert: bool = False
    mask_rect_width: Optional[float] = None
    mask_round_corner: Optional[float] = None
    background_blur: Optional[int] = None

@router.post("/add_image")
@api_endpoint_logger
async def add_image(request: AddImageRequest, response: Response):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = await add_image_impl(
            draft_folder=request.draft_folder,
            image_url=request.image_url,
            image_name=request.image_name,
            start=request.start,
            end=request.end,
            draft_id=request.draft_id,
            transform_y=request.transform_y,
            scale_x=request.scale_x,
            scale_y=request.scale_y,
            transform_x=request.transform_x,
            track_name=request.track_name,
            relative_index=request.relative_index,
            intro_animation=request.intro_animation,
            intro_animation_duration=request.intro_animation_duration,
            outro_animation=request.outro_animation,
            outro_animation_duration=request.outro_animation_duration,
            combo_animation=request.combo_animation,
            combo_animation_duration=request.combo_animation_duration,
            transition=request.transition,
            transition_duration=request.transition_duration,
            mask_type=request.mask_type,
            mask_center_x=request.mask_center_x,
            mask_center_y=request.mask_center_y,
            mask_size=request.mask_size,
            mask_rotation=request.mask_rotation,
            mask_feather=request.mask_feather,
            mask_invert=request.mask_invert,
            mask_rect_width=request.mask_rect_width,
            mask_round_corner=request.mask_round_corner,
            background_blur=request.background_blur
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while processing image: {e!s}."
        response.status_code = 400
        return result


