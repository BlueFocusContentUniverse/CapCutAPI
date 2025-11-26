"""
API endpoints for managing video records and OSS metadata.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from repositories.video_repository import get_video_repository
from repositories.video_task_repository import get_video_task_repository
from util.cognito_auth import verify_api_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/videos",
    tags=["videos"],
    dependencies=[Depends(verify_api_token)]
)


class CreateVideoRequest(BaseModel):
    task_id: str
    oss_url: str
    video_name: Optional[str] = None
    resolution: Optional[str] = None
    framerate: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    thumbnail_url: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@router.post("/create")
@api_endpoint_logger
async def create_video(request: CreateVideoRequest):
    """
    Create a new video record with OSS metadata.
    """
    try:
        if not request.task_id or not request.oss_url:
            logger.warning("Missing required fields: task_id or oss_url")
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "Missing required fields: task_id and oss_url are required"
            })

        # Get draft_id from VideoTask
        task_repo = get_video_task_repository()
        task = task_repo.get_task(request.task_id)

        if task is None:
            logger.warning(f"VideoTask {request.task_id} not found")
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": f"VideoTask {request.task_id} not found"
            })

        draft_id = task["draft_id"]

        # Create video record
        video_repo = get_video_repository()
        video_id = video_repo.create_video(
            draft_id=draft_id,
            oss_url=request.oss_url,
            video_name=request.video_name,
            resolution=request.resolution,
            framerate=request.framerate,
            duration=request.duration,
            file_size=request.file_size,
            thumbnail_url=request.thumbnail_url,
            extra=request.extra,
        )

        if video_id is not None:
            # Link video_id to the task
            task_repo.link_video_to_task(request.task_id, video_id)

            logger.info(f"Successfully created video {video_id} for task {request.task_id}, draft {draft_id}")
            return {
                "success": True,
                "output": {
                    "video_id": video_id,
                    "draft_id": draft_id,
                    "task_id": request.task_id
                }
            }
        else:
            return JSONResponse(status_code=500, content={
                "success": False,
                "error": "Failed to create video record"
            })

    except Exception as e:
        logger.error(f"Error creating video: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })


@router.get("/{video_id}")
@api_endpoint_logger
async def get_video(video_id: str):
    """
    Get video details by video_id.
    """
    try:
        repo = get_video_repository()
        video = repo.get_video(video_id)

        if video is None:
            logger.warning(f"Video {video_id} not found")
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": "Video not found"
            })

        return {
            "success": True,
            "output": video
        }

    except Exception as e:
        logger.error(f"Error retrieving video {video_id}: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })


@router.get("/by-draft/{draft_id}")
@api_endpoint_logger
async def get_videos_by_draft(draft_id: str):
    """
    Get all videos associated with a draft_id.
    """
    try:
        repo = get_video_repository()
        videos = repo.get_videos_by_draft(draft_id)

        return {
            "success": True,
            "output": {
                "videos": videos,
                "count": len(videos)
            }
        }

    except Exception as e:
        logger.error(f"Error retrieving videos for draft {draft_id}: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })


class UpdateVideoRequest(BaseModel):
    video_name: Optional[str] = None
    resolution: Optional[str] = None
    framerate: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    oss_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@router.put("/{video_id}")
@api_endpoint_logger
async def update_video(video_id: str, request: UpdateVideoRequest):
    """
    Update video metadata.
    """
    try:
        repo = get_video_repository()
        success = repo.update_video(
            video_id=video_id,
            video_name=request.video_name,
            resolution=request.resolution,
            framerate=request.framerate,
            duration=request.duration,
            file_size=request.file_size,
            oss_url=request.oss_url,
            thumbnail_url=request.thumbnail_url,
            extra=request.extra,
        )

        if success:
            logger.info(f"Successfully updated video {video_id}")
            return {
                "success": True,
                "output": {"video_id": video_id}
            }
        else:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": "Video not found or update failed"
            })

    except Exception as e:
        logger.error(f"Error updating video {video_id}: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })


@router.delete("/{video_id}")
@api_endpoint_logger
async def delete_video(
    video_id: str,
    delete_oss: bool = Query(True, description="Whether to delete remote OSS object")
):
    """
    Delete a video record and optionally its remote OSS object.
    """
    try:
        repo = get_video_repository()
        success = repo.delete_video(video_id, delete_oss=delete_oss)

        if success:
            logger.info(f"Successfully deleted video {video_id} (delete_oss={delete_oss})")
            return {
                "success": True,
                "output": {
                    "video_id": video_id,
                    "deleted_oss": delete_oss
                }
            }
        else:
            return JSONResponse(status_code=404, content={
                "success": False,
                "error": "Video not found or deletion failed"
            })

    except Exception as e:
        logger.error(f"Error deleting video {video_id}: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })


@router.get("")
@api_endpoint_logger
async def list_videos(
    page: int = Query(1, description="Page number (1-indexed)"),
    page_size: int = Query(100, description="Number of items per page"),
    draft_id: Optional[str] = Query(None, description="Filter by draft_id")
):
    """
    List videos with pagination.
    """
    try:
        repo = get_video_repository()
        result = repo.list_videos(page=page, page_size=page_size, draft_id=draft_id)

        return {
            "success": True,
            "output": {
                "videos": result["videos"],
                "pagination": result["pagination"]
            }
        }

    except Exception as e:
        logger.error(f"Error listing videos: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e)
        })

