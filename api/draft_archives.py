"""
API endpoints for managing draft archives stored in PostgreSQL.
"""

import logging

from flask import Blueprint, jsonify, request

from logging_utils import api_endpoint_logger
from repositories.draft_archive_repository import get_postgres_archive_storage
from util.auth import require_authentication
from util.cos_client import get_cos_client

logger = logging.getLogger(__name__)

# Create a blueprint for draft archive management
archive_bp = Blueprint("draft_archives", __name__, url_prefix="/api/draft_archives")


@archive_bp.before_request
def _require_authentication():
    """Protect all draft archive endpoints with token authentication.

    Configure one of the following env vars for valid tokens:
      - DRAFT_API_TOKEN (single token)
      - DRAFT_API_TOKENS (comma-separated list)
    Fallbacks supported: API_TOKEN, AUTH_TOKEN

    Client should send the token via:
      - Authorization: Bearer <token>
      - X-API-Token: <token> (or X-Auth-Token / X-Token)
      - ?api_token=<token> (query param, not recommended)
    """
    return require_authentication(request, "Draft archives API")


@archive_bp.route("/list", methods=["GET"])
@api_endpoint_logger
def list_archives():
    """
    List draft archives with optional filtering and pagination

    Query Parameters:
        draft_id (str, optional): Filter by draft_id
        user_id (str, optional): Filter by user_id
        page (int): Page number (1-indexed, default: 1)
        page_size (int): Number of items per page (default: 100, max: 1000)

    Returns:
        JSON response with archives array and pagination metadata
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        # Get query parameters
        draft_id = request.args.get("draft_id")
        user_id = request.args.get("user_id")
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 100))

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
        return jsonify(result)

    except ValueError as e:
        result["error"] = f"Invalid parameter value: {e!s}"
        return jsonify(result), 400
    except Exception as e:
        result["error"] = f"Failed to list archives: {e!s}"
        logger.error(f"Error listing archives: {e!s}", exc_info=True)
        return jsonify(result), 500


@archive_bp.route("/get/<archive_id>", methods=["GET"])
@api_endpoint_logger
def get_archive(archive_id: str):
    """
    Get a specific archive by archive_id

    Path Parameters:
        archive_id (str): The UUID of the archive

    Returns:
        JSON response with archive details
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
            return jsonify(result), 404

        result["success"] = True
        result["output"] = archive
        logger.info(f"Retrieved archive {archive_id}")
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Failed to get archive: {e!s}"
        logger.error(f"Error getting archive {archive_id}: {e!s}", exc_info=True)
        return jsonify(result), 500


@archive_bp.route("/get_by_draft", methods=["GET"])
@api_endpoint_logger
def get_archive_by_draft():
    """
    Get archive by draft_id and optional draft_version

    Query Parameters:
        draft_id (str, required): The draft ID
        draft_version (int, optional): The draft version

    Returns:
        JSON response with archive details
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_id = request.args.get("draft_id")
        if not draft_id:
            result["error"] = "Parameter 'draft_id' is required"
            return jsonify(result), 400

        draft_version = request.args.get("draft_version")
        if draft_version is not None:
            try:
                draft_version = int(draft_version)
            except ValueError:
                result["error"] = "Parameter 'draft_version' must be an integer"
                return jsonify(result), 400

        storage = get_postgres_archive_storage()
        archive = storage.get_archive_by_draft(draft_id, draft_version)

        if archive is None:
            result["error"] = f"Archive not found for draft {draft_id} version {draft_version}"
            return jsonify(result), 404

        result["success"] = True
        result["output"] = archive
        logger.info(f"Retrieved archive for draft {draft_id} version {draft_version}")
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Failed to get archive: {e!s}"
        logger.error(f"Error getting archive by draft: {e!s}", exc_info=True)
        return jsonify(result), 500


@archive_bp.route("/update/<archive_id>", methods=["PUT", "PATCH"])
@api_endpoint_logger
def update_archive(archive_id: str):
    """
    Update archive fields

    Path Parameters:
        archive_id (str): The UUID of the archive

    Request Body (JSON):
        download_url (str, optional): Download URL
        total_files (int, optional): Total number of files
        progress (float, optional): Progress percentage (0-100)
        downloaded_files (int, optional): Number of downloaded files
        message (str, optional): Status or error message

    Returns:
        JSON response indicating success or failure
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        data = request.get_json()
        if not data:
            result["error"] = "Request body is required"
            return jsonify(result), 400

        # Extract allowed fields
        allowed_fields = ["download_url", "total_files", "progress", "downloaded_files", "message"]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}

        if not update_data:
            result["error"] = f"No valid fields to update. Allowed fields: {', '.join(allowed_fields)}"
            return jsonify(result), 400

        storage = get_postgres_archive_storage()
        success = storage.update_archive(archive_id, **update_data)

        if not success:
            result["error"] = f"Failed to update archive {archive_id}. Archive may not exist."
            return jsonify(result), 404

        result["success"] = True
        result["output"] = {"message": "Archive updated successfully", "archive_id": archive_id}
        logger.info(f"Updated archive {archive_id} with fields: {list(update_data.keys())}")
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Failed to update archive: {e!s}"
        logger.error(f"Error updating archive {archive_id}: {e!s}", exc_info=True)
        return jsonify(result), 500


@archive_bp.route("/delete/<archive_id>", methods=["DELETE"])
@api_endpoint_logger
def delete_archive(archive_id: str):
    """
    Delete an archive

    Path Parameters:
        archive_id (str): The UUID of the archive

    Returns:
        JSON response indicating success or failure
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
            return jsonify(result), 404

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
            return jsonify(result), 500

        result["success"] = True
        result["output"] = {"message": "Archive deleted successfully", "archive_id": archive_id}
        logger.info(f"Deleted archive {archive_id} from database")
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Failed to delete archive: {e!s}"
        logger.error(f"Error deleting archive {archive_id}: {e!s}", exc_info=True)
        return jsonify(result), 500


@archive_bp.route("/stats", methods=["GET"])
@api_endpoint_logger
def get_stats():
    """
    Get statistics about archives

    Query Parameters:
        draft_id (str, optional): Get stats for a specific draft
        user_id (str, optional): Get stats for a specific user

    Returns:
        JSON response with statistics
    """
    result = {
        "success": False,
        "output": "",
        "error": ""
    }

    try:
        draft_id = request.args.get("draft_id")
        user_id = request.args.get("user_id")

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
        return jsonify(result)

    except Exception as e:
        result["error"] = f"Failed to get stats: {e!s}"
        logger.error(f"Error getting archive stats: {e!s}", exc_info=True)
        return jsonify(result), 500

