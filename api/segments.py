"""
API endpoints for segment management in tracks
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from logging_utils import api_endpoint_logger
from services.segment_management import delete_segment, get_segment_details

logger = logging.getLogger(__name__)
router = APIRouter(tags=["segments"])


class GetSegmentDetailsRequest(BaseModel):
    draft_id: str
    track_name: str
    segment_id: str


@router.post("/get_segment_details")
@api_endpoint_logger
async def get_segment_details_api(request: GetSegmentDetailsRequest):
    """
    Get detailed information about a specific segment
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    if not request.track_name:
        result["error"] = "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        return result

    if not request.segment_id:
        result["error"] = "Hi, the required parameter 'segment_id' is missing. Please add it and try again."
        return result

    try:
        segment_details = get_segment_details(request.draft_id, request.track_name, request.segment_id)

        result["success"] = True
        result["output"] = segment_details
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        logger.error(f"Error getting segment details: {e}", exc_info=True)
        result["error"] = f"Error occurred while getting segment details: {e!s}"
        return result


class DeleteSegmentRequest(BaseModel):
    draft_id: str
    track_name: str
    segment_index: Optional[int] = None
    segment_id: Optional[str] = None


@router.post("/delete_segment")
@api_endpoint_logger
async def delete_segment_api(request: DeleteSegmentRequest):
    """
    Delete a segment from a track by index or ID
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    if not request.draft_id:
        result["error"] = "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        return result

    if not request.track_name:
        result["error"] = "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        return result

    if (request.segment_index is None and request.segment_id is None):
        result["error"] = "Hi, you must provide either 'segment_index' or 'segment_id'. Please add one and try again."
        return result

    if (request.segment_index is not None and request.segment_id is not None):
        result["error"] = "Hi, you can only provide one of 'segment_index' or 'segment_id', not both. Please remove one and try again."
        return result

    try:
        delete_result = delete_segment(
            request.draft_id,
            request.track_name,
            segment_index=request.segment_index,
            segment_id=request.segment_id
        )

        result["success"] = True
        result["output"] = delete_result
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        logger.error(f"Error deleting segment: {e}", exc_info=True)
        result["error"] = f"Error occurred while deleting segment: {e!s}"
        return result

