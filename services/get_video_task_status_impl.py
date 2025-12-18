import logging
from datetime import datetime
from typing import Any, Dict

from repositories.video_task_repository import VideoTaskRepository

logger = logging.getLogger(__name__)


async def get_video_task_status_impl(task_id: str) -> Dict[str, Any]:
    """Get the status of a video generation task using the repository pattern."""

    result: Dict[str, Any] = {"success": False, "data": None, "error": ""}

    if not task_id:
        result["error"] = (
            "The required parameter 'task_id' is missing. Please add it and try again."
        )
        logger.warning("get_video_task_status_impl called without task_id")
        return result

    try:
        repository = VideoTaskRepository()
        task = await repository.get_task(task_id)

        if not task:
            result["error"] = f"VideoTask with task_id '{task_id}' not found."
            logger.warning(f"VideoTask not found: {task_id}")
            return result

        created_at = (
            datetime.fromtimestamp(task["created_at"]).isoformat()
            if task.get("created_at") is not None
            else None
        )
        updated_at = (
            datetime.fromtimestamp(task["updated_at"]).isoformat()
            if task.get("updated_at") is not None
            else None
        )

        task_data = {
            "id": task.get("id"),
            "task_id": task.get("task_id"),
            "draft_id": task.get("draft_id"),
            "video_id": task.get("video_id"),
            "video_name": task.get("video_name"),
            "status": task.get("status"),
            "render_status": task.get("render_status"),
            "progress": task.get("progress"),
            "message": task.get("message"),
            "oss_url": task.get("oss_url"),
            "extra": task.get("extra"),
            "created_at": created_at,
            "updated_at": updated_at,
        }

        result["success"] = True
        result["data"] = task_data
        logger.info(
            f"Successfully retrieved status for task_id: {task_id}, status: {task_data.get('render_status')}"
        )
        return result

    except Exception as e:
        result["error"] = f"Error occurred while retrieving video task status: {e!s}"
        logger.error(
            f"Error retrieving video task status for {task_id}: {e}", exc_info=True
        )
        return result
