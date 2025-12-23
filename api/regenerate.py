import logging
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from services.regenerate_video_impl import regenerate_video_impl

logger = logging.getLogger(__name__)
router = APIRouter(tags=["regenerate"])


class RegenerateVideoRequest(BaseModel):
    task_id: str


@router.post("/regenerate")
async def regenerate_video_api(request: RegenerateVideoRequest) -> Dict[str, Any]:
    """API endpoint for regenerating a video using existing task_id.

    Request body:
        {
            "task_id": str (required) - Task ID to regenerate
        }

    Returns:
        JSON response with success status and task ID
    """
    logger.info(f"Regenerating video for task_id: {request.task_id}")

    result = await regenerate_video_impl(request.task_id)

    return result
