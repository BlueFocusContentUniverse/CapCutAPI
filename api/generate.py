import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.generate_video_impl import generate_video_impl
from services.get_video_task_status_impl import get_video_task_status_impl

logger = logging.getLogger(__name__)
bp = Blueprint("generate", __name__)


@bp.route("/video_task_status", methods=["GET"])
@api_endpoint_logger
def get_video_task_status():
    """API endpoint to get the status of a video generation task.

    Query Parameters:
        task_id: str (required) - The unique identifier of the video task

    Returns:
        JSON response with task status information
    """
    task_id = request.args.get("task_id")

    logger.info(f"Getting video task status for task_id: {task_id}")

    result = get_video_task_status_impl(task_id)

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


