import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.create_draft import DraftFramerate, create_draft
from services.save_draft_impl import (
    query_script_impl,
    query_task_status,
    save_draft_impl,
)

# from util.helpers import generate_draft_url as utilgenerate_draft_url


bp = Blueprint("drafts", __name__)
logger = logging.getLogger(__name__)


@bp.route("/create_draft", methods=["POST"])
@api_endpoint_logger
def create_draft_service():
    data = request.get_json()

    width = data.get("width", 1080)
    height = data.get("height", 1920)
    framerate = data.get("framerate", DraftFramerate.FR_30.value)
    name = data.get("name", "draft")
    resource = data.get("resource")  # 'api' or 'mcp'

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        _script, draft_id = create_draft(width=width, height=height, framerate=framerate, name=name, resource=resource)

        result["success"] = True
        result["output"] = {"draft_id": draft_id}
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while creating draft: {e!s}."
        return jsonify(result)


@bp.route("/query_script", methods=["POST"])
@api_endpoint_logger
def query_script():
    data = request.get_json()

    draft_id = data.get("draft_id")
    force_update = data.get("force_update", True)

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        script = query_script_impl(draft_id=draft_id, force_update=force_update)

        if script is None:
            result["error"] = f"Draft {draft_id} does not exist in cache."
            return jsonify(result)

        script_str = script.dumps()

        result["success"] = True
        result["output"] = script_str
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while querying script: {e!s}. "
        return jsonify(result)


@bp.route("/save_draft", methods=["POST"])
@api_endpoint_logger
def save_draft():
    data = request.get_json()

    draft_id = data.get("draft_id")
    draft_folder = data.get("draft_folder")
    draft_version = data.get("draft_version")
    user_id = data.get("user_id")
    user_name = data.get("user_name")
    archive_name = data.get("archive_name")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        draft_result = save_draft_impl(
            draft_id=draft_id,
            draft_folder=draft_folder,
            draft_version=draft_version,
            user_id=user_id,
            user_name=user_name,
            archive_name=archive_name
        )

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while saving draft: {e!s}. "
        return jsonify(result)

@bp.route("/query_draft_status", methods=["POST"])
@api_endpoint_logger
def query_draft_status_api():
    data = request.get_json()

    task_id = data.get("task_id")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not task_id:
        result["error"] = "Hi, the required parameter 'task_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        task_status = query_task_status(task_id)

        if task_status["status"] == "not_found":
            result["error"] = f"Task with ID {task_id} not found. Please check if the task ID is correct."
            return jsonify(result)

        result["success"] = True
        result["output"] = task_status
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while querying task status: {e!s}."
        return jsonify(result)


@bp.route("/generate_draft_url", methods=["POST"])
@api_endpoint_logger
def generate_draft_url():
    from settings.local import DRAFT_DOMAIN, PREVIEW_ROUTER

    data = request.get_json()

    draft_id = data.get("draft_id")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        draft_result = {"draft_url": f"{DRAFT_DOMAIN}{PREVIEW_ROUTER}?={draft_id}"}

        result["success"] = True
        result["output"] = draft_result
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Error occurred while saving draft: {e!s}."
        return jsonify(result)


