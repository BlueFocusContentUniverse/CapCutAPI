import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from services.add_video_keyframe_impl import add_video_keyframe_impl
from services.add_video_track import add_video_track, batch_add_video_track

logger = logging.getLogger(__name__)
router = APIRouter(tags=["video"])

class AddVideoRequest(BaseModel):
    draft_folder: Optional[str] = None
    video_url: str
    video_name: Optional[str] = None
    start: float = 0
    end: float = 0
    mode: str = "cover"
    target_duration: Optional[float] = None
    draft_id: Optional[str] = None
    transform_y: float = 0
    scale_x: float = 1
    scale_y: float = 1
    transform_x: float = 0
    speed: float = 1.0
    target_start: float = 0
    track_name: str = "video_main"
    relative_index: int = 0
    duration: Optional[float] = None
    transition: Optional[str] = None
    transition_duration: float = 0.5
    volume: float = 1.0
    intro_animation: Optional[str] = None
    intro_animation_duration: float = 0.5
    outro_animation: Optional[str] = None
    outro_animation_duration: float = 0.5
    combo_animation: Optional[str] = None
    combo_animation_duration: float = 0.5
    mask_type: Optional[str] = None
    mask_center_x: float = 0.5
    mask_center_y: float = 0.5
    mask_size: float = 1.0
    mask_rotation: float = 0.0
    mask_feather: float = 0.0
    mask_invert: bool = False
    mask_rect_width: Optional[float] = None
    mask_round_corner: Optional[float] = None
    filter_type: Optional[str] = None
    filter_intensity: float = 100.0
    fade_in_duration: float = 0.0
    fade_out_duration: float = 0.0
    background_blur: Optional[int] = None

class VideoItem(BaseModel):
    video_url: str
    start: float = 0
    end: float = 0
    target_start: float = 0
    speed: float = 1.0
    mode: str = "cover"
    target_duration: Optional[float] = None
    duration: Optional[float] = None
    video_name: Optional[str] = None

class BatchAddVideosRequest(BaseModel):
    draft_folder: Optional[str] = None
    draft_id: Optional[str] = None
    videos: List[VideoItem]

    # Common parameters
    transform_y: float = 0
    scale_x: float = 1
    scale_y: float = 1
    transform_x: float = 0
    track_name: str = "video_main"
    relative_index: int = 0
    transition: Optional[str] = None
    transition_duration: float = 0.5
    volume: float = 1.0
    intro_animation: Optional[str] = None
    intro_animation_duration: float = 0.5
    outro_animation: Optional[str] = None
    outro_animation_duration: float = 0.5
    combo_animation: Optional[str] = None
    combo_animation_duration: float = 0.5
    mask_type: Optional[str] = None
    mask_center_x: float = 0.5
    mask_center_y: float = 0.5
    mask_size: float = 1.0
    mask_rotation: float = 0.0
    mask_feather: float = 0.0
    mask_invert: bool = False
    mask_rect_width: Optional[float] = None
    mask_round_corner: Optional[float] = None
    filter_type: Optional[str] = None
    filter_intensity: float = 100.0
    fade_in_duration: float = 0.0
    fade_out_duration: float = 0.0
    background_blur: Optional[int] = None
    mode: str = "cover"

class AddVideoKeyframeRequest(BaseModel):
    draft_id: Optional[str] = None
    track_name: str = "video_main"
    property_type: str = "alpha"
    time: float = 0.0
    value: str = "1.0"
    property_types: Optional[List[str]] = None
    times: Optional[List[float]] = None
    values: Optional[List[Any]] = None

@router.post("/add_video")
async def add_video(request: AddVideoRequest, response: Response):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = await add_video_track(
            draft_folder=request.draft_folder,
            video_url=request.video_url,
            start=request.start,
            end=request.end,
            mode=request.mode,
            target_duration=request.target_duration,
            target_start=request.target_start,
            draft_id=request.draft_id,
            transform_y=request.transform_y,
            scale_x=request.scale_x,
            scale_y=request.scale_y,
            transform_x=request.transform_x,
            speed=request.speed,
            track_name=request.track_name,
            relative_index=request.relative_index,
            duration=request.duration,
            intro_animation=request.intro_animation,
            intro_animation_duration=request.intro_animation_duration,
            outro_animation=request.outro_animation,
            outro_animation_duration=request.outro_animation_duration,
            combo_animation=request.combo_animation,
            combo_animation_duration=request.combo_animation_duration,
            video_name=request.video_name,
            transition=request.transition,
            transition_duration=request.transition_duration,
            volume=request.volume,
            mask_type=request.mask_type,
            mask_center_x=request.mask_center_x,
            mask_center_y=request.mask_center_y,
            mask_size=request.mask_size,
            mask_rotation=request.mask_rotation,
            mask_feather=request.mask_feather,
            mask_invert=request.mask_invert,
            mask_rect_width=request.mask_rect_width,
            mask_round_corner=request.mask_round_corner,
            filter_type=request.filter_type,
            filter_intensity=request.filter_intensity,
            fade_in_duration=request.fade_in_duration,
            fade_out_duration=request.fade_out_duration,
            background_blur=request.background_blur
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while processing video: {e!s}."
        response.status_code = 400
        return result


@router.post("/batch_add_videos")
async def batch_add_videos(request: BatchAddVideosRequest, response: Response):
    result = {
        "success": False,
        "output": [],
        "error": ""
    }

    if not request.videos:
        result["error"] = "Hi, the required parameter 'videos' is missing or empty."
        response.status_code = 400
        return result

    try:
        # Convert Pydantic models to dicts for the service function
        videos_data = [v.dict() for v in request.videos]

        batch_result = await batch_add_video_track(
            videos=videos_data,
            draft_folder=request.draft_folder,
            draft_id=request.draft_id,
            transform_y=request.transform_y,
            scale_x=request.scale_x,
            scale_y=request.scale_y,
            transform_x=request.transform_x,
            track_name=request.track_name,
            relative_index=request.relative_index,
            transition=request.transition,
            transition_duration=request.transition_duration,
            volume=request.volume,
            intro_animation=request.intro_animation,
            intro_animation_duration=request.intro_animation_duration,
            outro_animation=request.outro_animation,
            outro_animation_duration=request.outro_animation_duration,
            combo_animation=request.combo_animation,
            combo_animation_duration=request.combo_animation_duration,
            mask_type=request.mask_type,
            mask_center_x=request.mask_center_x,
            mask_center_y=request.mask_center_y,
            mask_size=request.mask_size,
            mask_rotation=request.mask_rotation,
            mask_feather=request.mask_feather,
            mask_invert=request.mask_invert,
            mask_rect_width=request.mask_rect_width,
            mask_round_corner=request.mask_round_corner,
            filter_type=request.filter_type,
            filter_intensity=request.filter_intensity,
            fade_in_duration=request.fade_in_duration,
            fade_out_duration=request.fade_out_duration,
            background_blur=request.background_blur,
            default_mode=request.mode,
        )

        result["success"] = True
        result["output"] = batch_result["outputs"]
        if batch_result["skipped"]:
            skipped_descriptions = [
                entry.get("video_url") or f"index {entry.get('index')}"
                for entry in batch_result["skipped"]
            ]
            result["error"] = f"Skipped videos: {skipped_descriptions}"
            result["success"] = False
            response.status_code = 400
            return result
        return result

    except Exception as e:
        logger.error(f"Error occurred while processing batch videos: {e!s}", exc_info=True)
        result["error"] = f"Error occurred while processing batch videos: {e!s}."
        response.status_code = 400
        return result


@router.post("/add_video_keyframe")
def add_video_keyframe(request: AddVideoKeyframeRequest, response: Response):
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_result = add_video_keyframe_impl(
            draft_id=request.draft_id,
            track_name=request.track_name,
            property_type=request.property_type,
            time=request.time,
            value=request.value,
            property_types=request.property_types,
            times=request.times,
            values=request.values
        )

        result["success"] = True
        result["output"] = draft_result
        return result

    except Exception as e:
        result["error"] = f"Error occurred while adding keyframe: {e!s}."
        response.status_code = 400
        return result


