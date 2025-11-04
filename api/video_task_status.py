"""
API endpoints for updating VideoTask status (intended for Celery workers).
"""

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from models import VideoTaskStatus
from repositories.video_task_repository import get_video_task_repository
from util.auth import require_authentication

logger = logging.getLogger(__name__)

bp = Blueprint("video_task_status", __name__, url_prefix="/api/video-tasks")


@bp.before_request
def _require_authentication():
    """Protect all video task status endpoints with token authentication.

    Configure one of the following env vars for valid tokens:
      - DRAFT_API_TOKEN (single token)
      - DRAFT_API_TOKENS (comma-separated list)
    Fallbacks supported: API_TOKEN, AUTH_TOKEN

    Client should send the token via:
      - Authorization: Bearer <token>
      - X-API-Token: <token> (or X-Auth-Token / X-Token)
      - ?api_token=<token> (query param, not recommended)
    """
    return require_authentication(request, "Video task status API")


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
        raise ValueError(f"Invalid render_status: {status_str}. Valid values: {[s.value for s in VideoTaskStatus]}") from None


@bp.route("/<task_id>/status", methods=["PUT"])
@api_endpoint_logger
def update_task_status(task_id: str):
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
        data: Dict[str, Any] = request.get_json() or {}

        # Extract and validate fields
        status = data.get("status")
        render_status_str = data.get("render_status")
        progress = data.get("progress")
        message = data.get("message")
        video_id = data.get("video_id")
        extra = data.get("extra")

        # Parse render_status if provided
        render_status = None
        if render_status_str:
            try:
                render_status = _parse_render_status(render_status_str)
            except ValueError as e:
                logger.warning(f"Invalid render_status for task {task_id}: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 400

        # Validate progress if provided
        if progress is not None:
            try:
                progress = float(progress)
                if progress < 0.0 or progress > 100.0:
                    logger.warning(f"Invalid progress value for task {task_id}: {progress}")
                    return jsonify({
                        "success": False,
                        "error": "Progress must be between 0.0 and 100.0"
                    }), 400
            except (ValueError, TypeError):
                logger.warning(f"Invalid progress type for task {task_id}: {progress}")
                return jsonify({
                    "success": False,
                    "error": "Progress must be a number"
                }), 400

        # Update task status
        repo = get_video_task_repository()
        success = repo.update_task_status(
            task_id=task_id,
            status=status,
            render_status=render_status,
            progress=progress,
            message=message,
            video_id=video_id,
            extra=extra,
        )

        if success:
            logger.info(f"Successfully updated VideoTask {task_id}")
            return jsonify({
                "success": True,
                "output": {"task_id": task_id}
            })
        else:
            return jsonify({
                "success": False,
                "error": "Task not found or update failed"
            }), 404

    except Exception as e:
        logger.error(f"Error updating VideoTask {task_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/<task_id>", methods=["GET"])
@api_endpoint_logger
def get_task(task_id: str):
    """
    Get VideoTask details by task_id.

    Path Parameters:
        task_id: Task identifier

    Returns:
        JSON response with task metadata
    """
    try:
        repo = get_video_task_repository()
        task = repo.get_task(task_id)

        if task is None:
            logger.warning(f"VideoTask {task_id} not found")
            return jsonify({
                "success": False,
                "error": "Task not found"
            }), 404

        return jsonify({
            "success": True,
            "output": task
        })

    except Exception as e:
        logger.error(f"Error retrieving VideoTask {task_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/<task_id>/link-video", methods=["POST"])
@api_endpoint_logger
def link_video_to_task(task_id: str):
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
        data: Dict[str, Any] = request.get_json() or {}
        video_id = data.get("video_id")

        if not video_id:
            logger.warning("Missing required field: video_id")
            return jsonify({
                "success": False,
                "error": "Missing required field: video_id"
            }), 400

        repo = get_video_task_repository()
        success = repo.link_video_to_task(task_id, video_id)

        if success:
            logger.info(f"Successfully linked video {video_id} to task {task_id}")
            return jsonify({
                "success": True,
                "output": {
                    "task_id": task_id,
                    "video_id": video_id
                }
            })
        else:
            return jsonify({
                "success": False,
                "error": "Task not found or link failed"
            }), 404

    except Exception as e:
        logger.error(f"Error linking video to task {task_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

