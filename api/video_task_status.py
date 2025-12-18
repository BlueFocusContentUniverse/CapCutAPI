"""
API endpoints for updating VideoTask status (intended for Celery workers).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from models import VideoTaskStatus
from repositories.video_task_repository import get_video_task_repository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/video-tasks",
    tags=["video-tasks"],
)


@router.get("")
async def list_tasks(
    response: Response,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    draft_id: Optional[str] = Query(None, description="Filter by draft_id"),
    video_name: Optional[str] = Query(None, description="Fuzzy match on video_name"),
    render_status: Optional[str] = Query(None, description="Filter by render_status"),
    start_date: Optional[str] = Query(
        None, description="Filter created_at >= this ISO datetime or unix seconds"
    ),
    end_date: Optional[str] = Query(
        None, description="Filter created_at <= this ISO datetime or unix seconds"
    ),
):
    """List video tasks with pagination, including video.oss_url if present."""
    try:
        parsed_render_status = None
        if render_status:
            parsed_render_status = _parse_render_status(render_status)

        def _parse_date(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            try:
                # unix seconds
                ts = float(value)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except ValueError:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt

        parsed_start = _parse_date(start_date)
        parsed_end = _parse_date(end_date)

        repo = get_video_task_repository()
        result = await repo.list_tasks(
            page=page,
            page_size=page_size,
            draft_id=draft_id,
            video_name=video_name,
            render_status=parsed_render_status,
            start_date=parsed_start,
            end_date=parsed_end,
        )

        return result

    except ValueError as e:
        # render_status parse error
        response.status_code = 400
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Error listing VideoTasks: {e}")
        response.status_code = 500
        return {"error": str(e)}


class UpdateTaskStatusRequest(BaseModel):
    status: Optional[str] = None
    render_status: Optional[str] = None
    progress: Optional[float] = None
    message: Optional[str] = None
    video_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class LinkVideoRequest(BaseModel):
    video_id: str


def _parse_render_status(status_str: str) -> VideoTaskStatus:
    """
    Parse render_status string to VideoTaskStatus enum.

    Args:
        status_str: Status string (case-insensitive)

    Returns:
        VideoTaskStatus enum value

    Raises:
        ValueError: If status_str is not a valid VideoTaskStatus
    """
    status_str_upper = status_str.upper()
    try:
        return VideoTaskStatus[status_str_upper]
    except KeyError:
        # Try matching by value
        for status in VideoTaskStatus:
            if status.value.upper() == status_str_upper:
                return status
        raise ValueError(
            f"Invalid render_status: {status_str}. Valid values: {[s.value for s in VideoTaskStatus]}"
        ) from None


@router.put("/{task_id}/status")
async def update_task_status(
    task_id: str, request: UpdateTaskStatusRequest, response: Response
):
    """
    Update VideoTask status fields (for Celery workers).

    Path Parameters:
        task_id: Task identifier

    Request Body:
        {
            "status": str (optional) - Status string (e.g., "initialized", "pending", "processing", "completed", "failed"),
            "render_status": str (optional) - Render status enum value (INITIALIZED, PENDING, PROCESSING, COMPLETED, FAILED),
            "progress": float (optional) - Progress value (0.0 - 100.0),
            "message": str (optional) - Status message,
            "video_id": str (optional) - Video ID (UUID) to link to the task,
            "extra": dict (optional) - Additional metadata (merged with existing extra data)
        }

    Returns:
        JSON response with success status

    Example:
        PUT /api/video-tasks/abc123/status
        {
            "render_status": "PROCESSING",
            "status": "processing",
            "progress": 45.5,
            "message": "Encoding video..."
        }
    """
    try:
        # Parse render_status if provided
        render_status = None
        if request.render_status:
            try:
                render_status = _parse_render_status(request.render_status)
            except ValueError as e:
                logger.warning(f"Invalid render_status for task {task_id}: {e}")
                response.status_code = 400
                return {"success": False, "error": str(e)}

        # Validate progress if provided
        if request.progress is not None:
            if request.progress < 0.0 or request.progress > 100.0:
                logger.warning(
                    f"Invalid progress value for task {task_id}: {request.progress}"
                )
                response.status_code = 400
                return {
                    "success": False,
                    "error": "Progress must be between 0.0 and 100.0",
                }

        # Update task status
        repo = get_video_task_repository()
        success = await repo.update_task_status(
            task_id=task_id,
            status=request.status,
            render_status=render_status,
            progress=request.progress,
            message=request.message,
            video_id=request.video_id,
            extra=request.extra,
        )

        if success:
            logger.info(f"Successfully updated VideoTask {task_id}")
            return {"success": True, "output": {"task_id": task_id}}
        else:
            response.status_code = 404
            return {"success": False, "error": "Task not found or update failed"}

    except Exception as e:
        logger.error(f"Error updating VideoTask {task_id}: {e}")
        response.status_code = 500
        return {"success": False, "error": str(e)}


@router.get("/{task_id}")
async def get_task(task_id: str, response: Response):
    """
    Get VideoTask details by task_id.

    Path Parameters:
        task_id: Task identifier

    Returns:
        JSON response with task metadata
    """
    try:
        repo = get_video_task_repository()
        task = await repo.get_task(task_id)

        if task is None:
            logger.warning(f"VideoTask {task_id} not found")
            response.status_code = 404
            return {"success": False, "error": "Task not found"}

        return {"success": True, "output": task}

    except Exception as e:
        logger.error(f"Error retrieving VideoTask {task_id}: {e}")
        response.status_code = 500
        return {"success": False, "error": str(e)}


@router.post("/{task_id}/link-video")
async def link_video_to_task(
    task_id: str, request: LinkVideoRequest, response: Response
):
    """
    Link a video_id to a VideoTask.

    Path Parameters:
        task_id: Task identifier

    Request Body:
        {
            "video_id": str (required) - UUID string
        }

    Returns:
        JSON response with success status
    """
    try:
        repo = get_video_task_repository()
        success = await repo.link_video_to_task(task_id, request.video_id)

        if success:
            logger.info(
                f"Successfully linked video {request.video_id} to task {task_id}"
            )
            return {
                "success": True,
                "output": {"task_id": task_id, "video_id": request.video_id},
            }
        else:
            response.status_code = 404
            return {"success": False, "error": "Task not found or link failed"}

    except Exception as e:
        logger.error(f"Error linking video to task {task_id}: {e}")
        response.status_code = 500
        return {"success": False, "error": str(e)}
