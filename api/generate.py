import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from db import get_session
from logging_utils import api_endpoint_logger
from models import Video, VideoTask
from services.generate_video_impl import generate_video_impl

logger = logging.getLogger(__name__)
bp = Blueprint("generate", __name__)


@bp.route("/video_task_status", methods=["GET"])
@api_endpoint_logger
def get_video_task_status():
    task_id = request.args.get("task_id")

    result = {"success": False, "data": None, "error": ""}

    if not task_id:
        result["error"] = "The required parameter 'task_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        with get_session() as session:
            task = session.execute(
                select(VideoTask).where(VideoTask.task_id == task_id)
            ).scalar_one_or_none()

            if not task:
                result["error"] = f"VideoTask with task_id '{task_id}' not found."
                return jsonify(result)

            # Get oss_url from Video model if video_id exists
            oss_url = None
            if task.video_id:
                video = session.execute(
                    select(Video).where(Video.video_id == task.video_id)
                ).scalar_one_or_none()
                if video:
                    oss_url = video.oss_url
                    logger.info(f"Found oss_url for video_id {task.video_id}: {oss_url}")

            # Convert the SQLAlchemy object to a dictionary
            task_data = {
                "id": task.id,
                "task_id": task.task_id,
                "draft_id": task.draft_id,
                "video_name": task.video_name,
                "render_status": task.render_status.value if task.render_status else None,
                "progress": task.progress,
                "message": task.message,
                "oss_url": oss_url,
                "extra": task.extra,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }

            result["success"] = True
            result["data"] = task_data
            return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while retrieving video task status: {e!s}"
        return jsonify(result)


@bp.route("/generate_video", methods=["POST"])
@api_endpoint_logger
def generate_video_api():
    """API endpoint to generate a video from a draft.

    Request Body:
        {
            "draft_id": str (required) - The draft identifier to render,
            "resolution": str (optional) - Target resolution (e.g., "1080p", "720p"),
            "framerate": float (optional) - Target framerate (e.g., 30.0, 60.0),
            "name": str (optional) - Override for the draft/video name
        }

    Returns:
        JSON response with success status and task_id
    """
    data = request.get_json()

    draft_id = data.get("draft_id")
    resolution = data.get("resolution")
    framerate = data.get("framerate")
    override_name = data.get("name")

    logger.info(f"Generating video for draft_id: {draft_id}, resolution: {resolution}, framerate: {framerate}")

    result = generate_video_impl(
        draft_id=draft_id,
        resolution=resolution,
        framerate=framerate,
        name=override_name,
    )

    return jsonify(result)


