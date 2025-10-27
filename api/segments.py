"""
API endpoints for segment management in tracks
"""
import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from services.segment_management import delete_segment, get_segment_details

logger = logging.getLogger(__name__)
bp = Blueprint("segments", __name__)


@bp.route("/get_segment_details", methods=["POST"])
@api_endpoint_logger
def get_segment_details_api():
    """
    Get detailed information about a specific segment

    Request body:
    {
        "draft_id": str (required),
        "track_name": str (required),
        "segment_id": str (required)
    }

    Response:
    {
        "success": bool,
        "output": {
            "id": str,
            "material_id": str,
            "type": str,
            "target_timerange": {...},
            "start": int,
            "end": int,
            "duration": int,
            ... (all segment properties)
        },
        "error": str
    }
    """
    data = request.get_json()
    draft_id = data.get("draft_id")
    track_name = data.get("track_name")
    segment_id = data.get("segment_id")

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

    if not segment_id:
        result["error"] = "Hi, the required parameter 'segment_id' is missing. Please add it and try again."
        return jsonify(result)

    try:
        segment_details = get_segment_details(draft_id, track_name, segment_id)

        result["success"] = True
        result["output"] = segment_details
        return jsonify(result)

    except ValueError as e:
        result["error"] = str(e)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error getting segment details: {e}", exc_info=True)
        result["error"] = f"Error occurred while getting segment details: {e!s}"
        return jsonify(result)


@bp.route("/delete_segment", methods=["POST"])
@api_endpoint_logger
def delete_segment_api():
    """
    Delete a segment from a track by index or ID

    Request body:
    {
        "draft_id": str (required),
        "track_name": str (required),
        "segment_index": int (optional) - Index of the segment (0-based),
        "segment_id": str (optional) - ID of the segment
        Note: Must provide exactly one of segment_index or segment_id
    }

    Response:
    {
        "success": bool,
        "output": {
            "message": str,
            "draft_id": str,
            "track_name": str,
            "deleted_segment_id": str,
            "deleted_segment_index": int,
            "remaining_segments_count": int,
            "draft_duration": int
        },
        "error": str
    }
    """
    data = request.get_json()
    draft_id = data.get("draft_id")
    track_name = data.get("track_name")
    segment_index = data.get("segment_index")
    segment_id = data.get("segment_id")

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

    if (segment_index is None and segment_id is None):
        result["error"] = "Hi, you must provide either 'segment_index' or 'segment_id'. Please add one and try again."
        return jsonify(result)

    if (segment_index is not None and segment_id is not None):
        result["error"] = "Hi, you can only provide one of 'segment_index' or 'segment_id', not both. Please remove one and try again."
        return jsonify(result)

    try:
        delete_result = delete_segment(draft_id, track_name, segment_index=segment_index, segment_id=segment_id)

        result["success"] = True
        result["output"] = delete_result
        return jsonify(result)

    except ValueError as e:
        result["error"] = str(e)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error deleting segment: {e}", exc_info=True)
        result["error"] = f"Error occurred while deleting segment: {e!s}"
        return jsonify(result)

