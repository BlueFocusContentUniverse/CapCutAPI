"""
API endpoints for managing video records and OSS metadata.
"""

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from repositories.video_repository import get_video_repository
from repositories.video_task_repository import get_video_task_repository
from util.auth import require_authentication

logger = logging.getLogger(__name__)

bp = Blueprint("videos", __name__, url_prefix="/api/videos")


@bp.before_request
def _require_authentication():
    """Protect all video management endpoints with token authentication.

    Configure one of the following env vars for valid tokens:
      - DRAFT_API_TOKEN (single token)
      - DRAFT_API_TOKENS (comma-separated list)
    Fallbacks supported: API_TOKEN, AUTH_TOKEN

    Client should send the token via:
      - Authorization: Bearer <token>
      - X-API-Token: <token> (or X-Auth-Token / X-Token)
      - ?api_token=<token> (query param, not recommended)
    """
    return require_authentication(request, "Video management API")


@bp.route("/create", methods=["POST"])
@api_endpoint_logger
def create_video():
    """
    Create a new video record with OSS metadata.

    Request Body:
        {
            "task_id": str (required) - VideoTask identifier to get draft_id from,
            "oss_url": str (required),
            "video_name": str (optional),
            "resolution": str (optional),
            "framerate": str (optional),
            "duration": float (optional),
            "file_size": int (optional),
            "thumbnail_url": str (optional),
            "extra": dict (optional)
        }

    Returns:
        JSON response with success status and video_id
    """
    try:
        data: Dict[str, Any] = request.get_json() or {}

        task_id = data.get("task_id")
        oss_url = data.get("oss_url")

        if not task_id or not oss_url:
            logger.warning("Missing required fields: task_id or oss_url")
            return jsonify({
                "success": False,
                "error": "Missing required fields: task_id and oss_url are required"
            }), 400

        # Get draft_id from VideoTask
        task_repo = get_video_task_repository()
        task = task_repo.get_task(task_id)

        if task is None:
            logger.warning(f"VideoTask {task_id} not found")
            return jsonify({
                "success": False,
                "error": f"VideoTask {task_id} not found"
            }), 404

        draft_id = task["draft_id"]

        # Create video record
        video_repo = get_video_repository()
        video_id = video_repo.create_video(
            draft_id=draft_id,
            oss_url=oss_url,
            video_name=data.get("video_name"),
            resolution=data.get("resolution"),
            framerate=data.get("framerate"),
            duration=data.get("duration"),
            file_size=data.get("file_size"),
            thumbnail_url=data.get("thumbnail_url"),
            extra=data.get("extra"),
        )

        if video_id is not None:
            # Link video_id to the task
            task_repo.link_video_to_task(task_id, video_id)

            logger.info(f"Successfully created video {video_id} for task {task_id}, draft {draft_id}")
            return jsonify({
                "success": True,
                "output": {
                    "video_id": video_id,
                    "draft_id": draft_id,
                    "task_id": task_id
                }
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to create video record"
            }), 500

    except Exception as e:
        logger.error(f"Error creating video: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/<video_id>", methods=["GET"])
@api_endpoint_logger
def get_video(video_id: str):
    """
    Get video details by video_id.

    Path Parameters:
        video_id: Video identifier (UUID string)

    Returns:
        JSON response with video metadata
    """
    try:
        repo = get_video_repository()
        video = repo.get_video(video_id)

        if video is None:
            logger.warning(f"Video {video_id} not found")
            return jsonify({
                "success": False,
                "error": "Video not found"
            }), 404

        return jsonify({
            "success": True,
            "output": video
        })

    except Exception as e:
        logger.error(f"Error retrieving video {video_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/by-draft/<draft_id>", methods=["GET"])
@api_endpoint_logger
def get_videos_by_draft(draft_id: str):
    """
    Get all videos associated with a draft_id.

    Path Parameters:
        draft_id: Draft identifier

    Returns:
        JSON response with list of videos
    """
    try:
        repo = get_video_repository()
        videos = repo.get_videos_by_draft(draft_id)

        return jsonify({
            "success": True,
            "output": {
                "videos": videos,
                "count": len(videos)
            }
        })

    except Exception as e:
        logger.error(f"Error retrieving videos for draft {draft_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/<video_id>", methods=["PUT"])
@api_endpoint_logger
def update_video(video_id: str):
    """
    Update video metadata.

    Path Parameters:
        video_id: Video identifier (UUID string)

    Request Body:
        {
            "video_name": str (optional),
            "resolution": str (optional),
            "framerate": str (optional),
            "duration": float (optional),
            "file_size": int (optional),
            "oss_url": str (optional),
            "thumbnail_url": str (optional),
            "extra": dict (optional)
        }

    Returns:
        JSON response with success status
    """
    try:
        data: Dict[str, Any] = request.get_json() or {}

        repo = get_video_repository()
        success = repo.update_video(
            video_id=video_id,
            video_name=data.get("video_name"),
            resolution=data.get("resolution"),
            framerate=data.get("framerate"),
            duration=data.get("duration"),
            file_size=data.get("file_size"),
            oss_url=data.get("oss_url"),
            thumbnail_url=data.get("thumbnail_url"),
            extra=data.get("extra"),
        )

        if success:
            logger.info(f"Successfully updated video {video_id}")
            return jsonify({
                "success": True,
                "output": {"video_id": video_id}
            })
        else:
            return jsonify({
                "success": False,
                "error": "Video not found or update failed"
            }), 404

    except Exception as e:
        logger.error(f"Error updating video {video_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("/<video_id>", methods=["DELETE"])
@api_endpoint_logger
def delete_video(video_id: str):
    """
    Delete a video record and optionally its remote OSS object.

    Path Parameters:
        video_id: Video identifier (UUID string)

    Query Parameters:
        delete_oss: Boolean (default: true) - whether to delete remote OSS object

    Returns:
        JSON response with success status
    """
    try:
        delete_oss = request.args.get("delete_oss", "true").lower() in ("true", "1", "yes")

        repo = get_video_repository()
        success = repo.delete_video(video_id, delete_oss=delete_oss)

        if success:
            logger.info(f"Successfully deleted video {video_id} (delete_oss={delete_oss})")
            return jsonify({
                "success": True,
                "output": {
                    "video_id": video_id,
                    "deleted_oss": delete_oss
                }
            })
        else:
            return jsonify({
                "success": False,
                "error": "Video not found or deletion failed"
            }), 404

    except Exception as e:
        logger.error(f"Error deleting video {video_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@bp.route("", methods=["GET"])
@api_endpoint_logger
def list_videos():
    """
    List videos with pagination.

    Query Parameters:
        page: int (default: 1) - Page number (1-indexed)
        page_size: int (default: 100) - Number of items per page
        draft_id: str (optional) - Filter by draft_id

    Returns:
        JSON response with videos list and pagination metadata
    """
    try:
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 100, type=int)
        draft_id = request.args.get("draft_id", type=str)

        repo = get_video_repository()
        result = repo.list_videos(page=page, page_size=page_size, draft_id=draft_id)

        return jsonify({
            "success": True,
            "output": {
                "videos": result["videos"],
                "pagination": result["pagination"]
            }
        })

    except Exception as e:
        logger.error(f"Error listing videos: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

