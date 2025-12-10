import logging
from typing import Literal, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel

from services.generate_video_impl import generate_video_impl
from services.get_video_task_status_impl import get_video_task_status_impl

logger = logging.getLogger(__name__)
router = APIRouter(tags=["generate"])


class GenerateVideoRequest(BaseModel):
    draft_id: str
    resolution: Optional[Literal["720P", "1080P", "2K", "4K"]] = "720P"
    framerate: Optional[Literal["30fps", "50fps", "60fps"]] = "30fps"
    name: Optional[str] = None


@router.get("/video_task_status")
def get_video_task_status(task_id: str):
    """API endpoint to get the status of a video generation task.

    Query Parameters:
        task_id: str (required) - The unique identifier of the video task

    Returns:
        JSON response with task status information
    """
    logger.info(f"Getting video task status for task_id: {task_id}")

    result = get_video_task_status_impl(task_id)

    return result


@router.post("/generate_video")
def generate_video_api(request: GenerateVideoRequest, response: Response):
    """API endpoint to generate a video from a draft.

    Request Body:
        {
            "draft_id": str (required) - The draft identifier to render,
            "resolution": str (optional) - Target resolution ("720P", "1080P", "2K", "4K"),
            "framerate": str (optional) - Target framerate ("30fps", "50fps", "60fps"),
            "name": str (optional) - Override for the draft/video name
        }

    Returns:
        JSON response with success status and task_id
    """
    logger.info(
        f"Generating video for draft_id: {request.draft_id}, resolution: {request.resolution}, framerate: {request.framerate}"
    )

    result = generate_video_impl(
        draft_id=request.draft_id,
        resolution=request.resolution,
        framerate=request.framerate,
        name=request.name,
    )

    return result
