import logging
from typing import Any, Dict, Optional

from sqlalchemy import select

from db import get_session
from models import VideoTask

logger = logging.getLogger(__name__)


def get_video_task_status_impl(task_id: str) -> Dict[str, Any]:
    """Get the status of a video generation task.

    Args:
        task_id: The unique identifier of the video task.

    Returns:
        A dict with keys:
        - success: Whether the query was successful.
        - data: Task information dict when successful, containing:
            - id: Database record ID
            - task_id: Unique task identifier
            - draft_id: Associated draft ID
            - video_name: Name of the video
            - render_status: Current render status
            - progress: Progress percentage (0-100)
            - message: Status message or error details
            - draft_url: URL to the draft (if available)
            - extra: Additional metadata
            - created_at: Task creation timestamp
            - updated_at: Task last update timestamp
        - error: Error message string when unsuccessful.
    """
    result: Dict[str, Any] = {"success": False, "data": None, "error": ""}

    if not task_id:
        result["error"] = "The required parameter 'task_id' is missing. Please add it and try again."
        logger.warning("get_video_task_status_impl called without task_id")
        return result

    try:
        with get_session() as session:
            task = session.execute(
                select(VideoTask).where(VideoTask.task_id == task_id)
            ).scalar_one_or_none()

            if not task:
                result["error"] = f"VideoTask with task_id '{task_id}' not found."
                logger.warning(f"VideoTask not found: {task_id}")
                return result

            # Convert the SQLAlchemy object to a dictionary
            task_data = {
                "id": task.id,
                "task_id": task.task_id,
                "draft_id": task.draft_id,
                "video_name": task.video_name,
                "render_status": task.render_status.value if task.render_status else None,
                "progress": task.progress,
                "message": task.message,
                "draft_url": task.draft_url,
                "extra": task.extra,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }

            result["success"] = True
            result["data"] = task_data
            logger.info(f"Successfully retrieved status for task_id: {task_id}, status: {task_data.get('render_status')}")
            return result

    except Exception as e:
        result["error"] = f"Error occurred while retrieving video task status: {e!s}"
        logger.error(f"Error retrieving video task status for {task_id}: {e}", exc_info=True)
        return result

