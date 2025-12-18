"""
API endpoints for track management in drafts
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from services.track_management import delete_track, get_track_details, get_tracks

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tracks"])


class GetTracksRequest(BaseModel):
    draft_id: str


@router.post("/get_tracks")
async def get_tracks_api(request: GetTracksRequest):
    """
    Get all tracks from a draft
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    try:
        tracks_info = await get_tracks(request.draft_id)

        result["success"] = True
        result["output"] = tracks_info
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"Error occurred while getting tracks: {e!s}"
        return result


class DeleteTrackRequest(BaseModel):
    draft_id: str
    track_name: str


@router.post("/delete_track")
async def delete_track_api(request: DeleteTrackRequest):
    """
    Delete a track from a draft by name
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    if not request.track_name:
        result["error"] = (
            "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        )
        return result

    try:
        deletion_result = await delete_track(request.draft_id, request.track_name)

        result["success"] = True
        result["output"] = deletion_result
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"Error occurred while deleting track: {e!s}"
        return result


class GetTrackDetailsRequest(BaseModel):
    draft_id: str
    track_name: str


@router.post("/get_track_details")
async def get_track_details_api(request: GetTrackDetailsRequest):
    """
    Get detailed information about a specific track
    """
    result = {"success": False, "output": "", "error": ""}

    if not request.draft_id:
        result["error"] = (
            "Hi, the required parameter 'draft_id' is missing. Please add it and try again."
        )
        return result

    if not request.track_name:
        result["error"] = (
            "Hi, the required parameter 'track_name' is missing. Please add it and try again."
        )
        return result

    try:
        track_details = await get_track_details(request.draft_id, request.track_name)

        result["success"] = True
        result["output"] = track_details
        return result

    except ValueError as e:
        result["error"] = str(e)
        return result
    except Exception as e:
        result["error"] = f"Error occurred while getting track details: {e!s}"
        return result
