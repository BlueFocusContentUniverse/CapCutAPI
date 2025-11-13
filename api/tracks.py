"""
API endpoints for track management in drafts
"""
import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.track_management import delete_track, get_track_details, get_tracks

logger = logging.getLogger(__name__)
bp = Blueprint("tracks", __name__)


@bp.route("/get_tracks", methods=["POST"])
@api_endpoint_logger
def get_tracks_api():
    """
    Get all tracks from a draft

    Request body:
    {
        "draft_id": str (required)
    }

    Response:
    {
        "success": bool,
        "output": {
            "tracks": [...],
            "imported_tracks": [...],
            "total_tracks": int
        },
        "error": str
    }
    """
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
        tracks_info = get_tracks(draft_id)

        result["success"] = True
        result["output"] = tracks_info
        return jsonify(result)

    except ValueError as e:
        result["error"] = str(e)
        return jsonify(result)
    except Exception as e:
        result["error"] = f"Error occurred while getting tracks: {e!s}"
        return jsonify(result)


@bp.route("/delete_track", methods=["POST"])
@api_endpoint_logger
def delete_track_api():
    """
    Delete a track from a draft by name

    Request body:
    {
        "draft_id": str (required),
        "track_name": str (required)
    }

    Response:
    {
        "success": bool,
        "output": {
            "deleted_track": str,
            "remaining_tracks": int,
            "new_duration": int
        },
        "error": str
    }
    """
    data = request.get_json()
    draft_id = data.get("draft_id")
    track_name = data.get("track_name")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    if not track_name:
        result["error"] = "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        return jsonify(result)

    try:
        deletion_result = delete_track(draft_id, track_name)

        result["success"] = True
        result["output"] = deletion_result
        return jsonify(result)

    except ValueError as e:
        result["error"] = str(e)
        return jsonify(result)
    except Exception as e:
        result["error"] = f"Error occurred while deleting track: {e!s}"
        return jsonify(result)


@bp.route("/get_track_details", methods=["POST"])
@api_endpoint_logger
def get_track_details_api():
    """
    Get detailed information about a specific track

    Request body:
    {
        "draft_id": str (required),
        "track_name": str (required)
    }

    Response:
    {
        "success": bool,
        "output": {
            "name": str,
            "type": str,
            "render_index": int,
            "mute": bool,
            "segment_count": int,
            "end_time": int,
            "segments": [...]
        },
        "error": str
    }
    """
    data = request.get_json()
    draft_id = data.get("draft_id")
    track_name = data.get("track_name")

    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return jsonify(result)

    if not track_name:
        result["error"] = "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        return jsonify(result)

    try:
        track_details = get_track_details(draft_id, track_name)

        result["success"] = True
        result["output"] = track_details
        return jsonify(result)

    except ValueError as e:
        result["error"] = str(e)
        return jsonify(result)
    except Exception as e:
        result["error"] = f"Error occurred while getting track details: {e!s}"
        return jsonify(result)

