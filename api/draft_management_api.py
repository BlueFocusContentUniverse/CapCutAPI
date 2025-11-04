"""
API endpoints for managing drafts stored in PostgreSQL.
Add these endpoints to your Flask application.
"""

import json
import logging

from flask import Blueprint, jsonify, request

from draft_cache import get_cache_stats, remove_from_cache
from logging_utils import api_endpoint_logger
from repositories.draft_repository import get_postgres_storage
from util.auth import require_authentication

logger = logging.getLogger(__name__)

# Create a blueprint for draft management
draft_bp = Blueprint("draft_management", __name__, url_prefix="/api/drafts")


@draft_bp.before_request
def _require_authentication():
    """Protect all draft management endpoints with token authentication.

    Configure one of the following env vars for valid tokens:
      - DRAFT_API_TOKEN (single token)
      - DRAFT_API_TOKENS (comma-separated list)
    Fallbacks supported: API_TOKEN, AUTH_TOKEN

    Client should send the token via:
      - Authorization: Bearer <token>
      - X-API-Token: <token> (or X-Auth-Token / X-Token)
      - ?api_token=<token> (query param, not recommended)
    """
    return require_authentication(request, "Draft management API")

@draft_bp.route("/list", methods=["GET"])
@api_endpoint_logger
def list_drafts():
    """
    List all stored drafts with pagination support

    Query Parameters:
        page (int): Page number (1-indexed, default: 1)
        page_size (int): Number of items per page (default: 100, max: 1000)
        limit (int): Deprecated - use page_size instead

    Returns:
        JSON response with drafts array and pagination metadata
    """
    try:
        # Get pagination parameters
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 100, type=int)

        # Backward compatibility: support old 'limit' parameter
        limit = request.args.get("limit", type=int)
        if limit is not None:
            page_size = limit
            page = 1  # Reset to first page when using limit

        pg_storage = get_postgres_storage()
        result = pg_storage.list_drafts(page=page, page_size=page_size)

        logger.info(f"List drafts request: page={page}, page_size={page_size}, returned {len(result['drafts'])} drafts")

        return jsonify({
            "success": True,
            "drafts": result["drafts"],
            "pagination": result["pagination"],
        })
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>", methods=["GET"])
@api_endpoint_logger
def get_draft_info(draft_id):
    """Get draft metadata without loading the full object"""
    try:
        pg_storage = get_postgres_storage()
        metadata = pg_storage.get_metadata(draft_id)

        if metadata is None:
            return jsonify({
                "success": False,
                "error": "Draft not found"
            }), 404

        return jsonify({
            "success": True,
            "draft": metadata
        })
    except Exception as e:
        logger.error(f"Failed to get draft {draft_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@draft_bp.route("/<draft_id>/content", methods=["GET"])
@api_endpoint_logger
def get_draft_content(draft_id):
    """Fetch full draft content JSON stored in Postgres."""
    try:
        pg_storage = get_postgres_storage()
        script_obj = pg_storage.get_draft(draft_id)

        if script_obj is None:
            return jsonify({
                "success": False,
                "error": "Draft not found"
            }), 404

        try:
            draft_content = json.loads(script_obj.dumps())
        except Exception as decode_err:
            logger.warning(f"Failed to decode draft {draft_id} to JSON object: {decode_err}")
            draft_content = script_obj.dumps()

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "content": draft_content
        })
    except Exception as e:
        logger.error(f"Failed to get draft content for {draft_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>", methods=["DELETE"])
@api_endpoint_logger
def delete_draft(draft_id):
    """Delete a draft from cache and soft-delete from database"""
    try:
        cache_removed = remove_from_cache(draft_id)

        pg_storage = get_postgres_storage()
        db_deleted = pg_storage.delete_draft(draft_id)

        if cache_removed or db_deleted:
            return jsonify({
                "success": True,
                "message": f"Draft {draft_id} deleted (cache_removed={cache_removed}, db_deleted={db_deleted})"
            })
        else:
            return jsonify({
                "success": False,
                "error": "Draft not found or could not be deleted"
            }), 404

    except Exception as e:
        logger.error(f"Failed to delete draft {draft_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>/exists", methods=["GET"])
@api_endpoint_logger
def check_draft_exists(draft_id):
    """Check if a draft exists in storage"""
    try:
        pg_storage = get_postgres_storage()
        exists = pg_storage.exists(draft_id)

        return jsonify({
            "success": True,
            "exists": exists,
            "draft_id": draft_id
        })
    except Exception as e:
        logger.error(f"Failed to check if draft {draft_id} exists: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/stats", methods=["GET"])
@api_endpoint_logger
def get_storage_stats():
    """Get storage statistics"""
    try:
        stats = get_cache_stats()
        return jsonify({
            "success": True,
            "stats": stats
        })
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/cleanup", methods=["POST"])
@api_endpoint_logger
def cleanup_expired():
    """Clean up expired or orphaned drafts"""
    try:
        pg_storage = get_postgres_storage()
        cleanup_count = pg_storage.cleanup_expired()

        return jsonify({
            "success": True,
            "message": f"Cleaned up {cleanup_count} expired drafts",
            "cleanup_count": cleanup_count
        })
    except Exception as e:
        logger.error(f"Failed to cleanup expired drafts: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>/versions", methods=["GET"])
@api_endpoint_logger
def list_draft_versions(draft_id):
    """List all versions of a draft"""
    try:
        pg_storage = get_postgres_storage()
        versions = pg_storage.list_draft_versions(draft_id)

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "versions": versions,
            "count": len(versions)
        })
    except Exception as e:
        logger.error(f"Failed to list versions for draft {draft_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>/versions/<int:version>", methods=["GET"])
@api_endpoint_logger
def get_draft_version_content(draft_id, version):
    """Get full draft content for a specific version"""
    try:
        pg_storage = get_postgres_storage()
        script_obj = pg_storage.get_draft_version(draft_id, version)

        if script_obj is None:
            return jsonify({
                "success": False,
                "error": f"Version {version} not found for draft {draft_id}"
            }), 404

        try:
            draft_content = json.loads(script_obj.dumps())
        except Exception as decode_err:
            logger.warning(f"Failed to decode draft {draft_id} version {version} to JSON object: {decode_err}")
            draft_content = script_obj.dumps()

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "version": version,
            "content": draft_content
        })
    except Exception as e:
        logger.error(f"Failed to get draft version content for {draft_id} version {version}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@draft_bp.route("/<draft_id>/versions/<int:version>/metadata", methods=["GET"])
@api_endpoint_logger
def get_draft_version_metadata(draft_id, version):
    """Get metadata for a specific version of a draft"""
    try:
        pg_storage = get_postgres_storage()
        metadata = pg_storage.get_draft_version_metadata(draft_id, version)

        if metadata is None:
            return jsonify({
                "success": False,
                "error": f"Version {version} not found for draft {draft_id}"
            }), 404

        return jsonify({
            "success": True,
            "draft_id": draft_id,
            "version": version,
            "metadata": metadata
        })
    except Exception as e:
        logger.error(f"Failed to get metadata for draft {draft_id} version {version}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# Usage example for integrating with your Flask app:
"""
To add these endpoints to your Flask app (capcut_server.py), add:

from draft_management_api import draft_bp
app.register_blueprint(draft_bp)

Then you can use these endpoints:
- GET /api/drafts/list - List all drafts
- GET /api/drafts/<draft_id> - Get draft metadata
- GET /api/drafts/<draft_id>/content - Get draft content
- DELETE /api/drafts/<draft_id> - Delete a draft
- GET /api/drafts/<draft_id>/exists - Check if draft exists
- GET /api/drafts/stats - Get storage statistics
- POST /api/drafts/cleanup - Clean up expired drafts
- GET /api/drafts/search?width=1080&height=1920 - Search drafts
- GET /api/drafts/<draft_id>/versions - List all versions of a draft
- GET /api/drafts/<draft_id>/versions/<version> - Get specific version content
- GET /api/drafts/<draft_id>/versions/<version>/metadata - Get metadata for a specific version
"""
