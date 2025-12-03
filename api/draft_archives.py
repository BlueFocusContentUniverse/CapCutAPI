"""
API endpoints for managing draft archives stored in PostgreSQL.
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from repositories.draft_archive_repository import get_postgres_archive_storage
from util.cos_client import get_cos_client

logger = logging.getLogger(__name__)

# Create a router for draft archive management
router = APIRouter(
    prefix="/api/draft_archives",
    tags=["draft_archives"],
)


@router.get("/list")
async def list_archives(
    draft_id: Optional[str] = Query(None, description="Filter by draft_id"),
    user_id: Optional[str] = Query(None, description="Filter by user_id"),
    page: int = Query(1, description="Page number (1-indexed)"),
    page_size: int = Query(100, description="Number of items per page")
):
    """
    List draft archives with optional filtering and pagination
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        storage = get_postgres_archive_storage()
        archives_data = storage.list_archives(
            draft_id=draft_id,
            user_id=user_id,
            page=page,
            page_size=page_size
        )

        result["success"] = True
        result["output"] = archives_data
        logger.info(f"Listed {len(archives_data['archives'])} archives")
        return result

    except ValueError as e:
        result["error"] = f"Invalid parameter value: {e!s}"
        return JSONResponse(status_code=400, content=result)
    except Exception as e:
        result["error"] = f"Failed to list archives: {e!s}"
        logger.error(f"Error listing archives: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)


@router.get("/get/{archive_id}")
async def get_archive(archive_id: str):
    """
    Get a specific archive by archive_id
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        storage = get_postgres_archive_storage()
        archive = storage.get_archive_by_id(archive_id)

        if archive is None:
            result["error"] = f"Archive {archive_id} not found"
            return JSONResponse(status_code=404, content=result)

        result["success"] = True
        result["output"] = archive
        logger.info(f"Retrieved archive {archive_id}")
        return result

    except Exception as e:
        result["error"] = f"Failed to get archive: {e!s}"
        logger.error(f"Error getting archive {archive_id}: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)


@router.get("/get_by_draft")
async def get_archive_by_draft(
    draft_id: str = Query(..., description="The draft ID"),
    draft_version: Optional[int] = Query(None, description="The draft version")
):
    """
    Get archive by draft_id and optional draft_version
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        storage = get_postgres_archive_storage()
        archive = storage.get_archive_by_draft(draft_id, draft_version)

        if archive is None:
            result["error"] = f"Archive not found for draft {draft_id} version {draft_version}"
            return JSONResponse(status_code=404, content=result)

        result["success"] = True
        result["output"] = archive
        logger.info(f"Retrieved archive for draft {draft_id} version {draft_version}")
        return result

    except Exception as e:
        result["error"] = f"Failed to get archive: {e!s}"
        logger.error(f"Error getting archive by draft: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)


class UpdateArchiveRequest(BaseModel):
    download_url: Optional[str] = None
    total_files: Optional[int] = None
    progress: Optional[float] = None
    downloaded_files: Optional[int] = None
    message: Optional[str] = None


@router.put("/update/{archive_id}")
@router.patch("/update/{archive_id}")
async def update_archive(archive_id: str, request: UpdateArchiveRequest):
    """
    Update archive fields
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        # Extract allowed fields
        update_data = request.dict(exclude_unset=True)

        if not update_data:
            result["error"] = "No valid fields to update."
            return JSONResponse(status_code=400, content=result)

        storage = get_postgres_archive_storage()
        success = storage.update_archive(archive_id, **update_data)

        if not success:
            result["error"] = f"Failed to update archive {archive_id}. Archive may not exist."
            return JSONResponse(status_code=404, content=result)

        result["success"] = True
        result["output"] = {"message": "Archive updated successfully", "archive_id": archive_id}
        logger.info(f"Updated archive {archive_id} with fields: {list(update_data.keys())}")
        return result

    except Exception as e:
        result["error"] = f"Failed to update archive: {e!s}"
        logger.error(f"Error updating archive {archive_id}: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)


@router.delete("/delete/{archive_id}")
async def delete_archive(archive_id: str):
    """
    Delete an archive
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        storage = get_postgres_archive_storage()

        # Get archive details first to retrieve the download_url
        archive = storage.get_archive_by_id(archive_id)

        if not archive:
            result["error"] = f"Archive {archive_id} not found."
            return JSONResponse(status_code=404, content=result)

        # Delete object from COS if download_url exists
        download_url = archive.get("download_url")
        if download_url:
            logger.info(f"Deleting COS object for archive {archive_id}: {download_url}")
            cos_client = get_cos_client()
            if cos_client.is_available():
                cos_deleted = cos_client.delete_object_from_url(download_url)
                if cos_deleted:
                    logger.info(f"Successfully deleted COS object for archive {archive_id}")
                else:
                    logger.warning(f"Failed to delete COS object for archive {archive_id}, but continuing with database deletion")
            else:
                logger.warning(f"COS client not available, skipping object deletion for archive {archive_id}")
        else:
            logger.info(f"Archive {archive_id} has no download_url, skipping COS object deletion")

        # Delete archive record from database
        success = storage.delete_archive(archive_id)

        if not success:
            result["error"] = f"Failed to delete archive {archive_id} from database."
            return JSONResponse(status_code=500, content=result)

        result["success"] = True
        result["output"] = {"message": "Archive deleted successfully", "archive_id": archive_id}
        logger.info(f"Deleted archive {archive_id} from database")
        return result

    except Exception as e:
        result["error"] = f"Failed to delete archive: {e!s}"
        logger.error(f"Error deleting archive {archive_id}: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)


@router.get("/stats")
async def get_stats(
    draft_id: Optional[str] = Query(None, description="Get stats for a specific draft"),
    user_id: Optional[str] = Query(None, description="Get stats for a specific user")
):
    """
    Get statistics about archives
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        storage = get_postgres_archive_storage()
        archives_data = storage.list_archives(
            draft_id=draft_id,
            user_id=user_id,
            page=1,
            page_size=1  # We only need the count
        )

        stats = {
            "total_archives": archives_data["pagination"]["total_count"],
            "filters": {}
        }

        if draft_id:
            stats["filters"]["draft_id"] = draft_id
        if user_id:
            stats["filters"]["user_id"] = user_id

        result["success"] = True
        result["output"] = stats
        logger.info(f"Retrieved archive stats: {stats}")
        return result

    except Exception as e:
        result["error"] = f"Failed to get stats: {e!s}"
        logger.error(f"Error getting archive stats: {e!s}", exc_info=True)
        return JSONResponse(status_code=500, content=result)

