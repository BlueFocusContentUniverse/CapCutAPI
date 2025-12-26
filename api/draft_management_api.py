"""
API endpoints for managing drafts stored in PostgreSQL.
Add these endpoints to your Flask application.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from draft_cache import get_cache_stats, remove_from_cache, REDIS_CACHE_AVAILABLE, get_from_cache
from repositories.draft_repository import get_postgres_storage
from repositories.redis_draft_cache import get_redis_draft_cache

logger = logging.getLogger(__name__)

# Create a router for draft management
router = APIRouter(
    prefix="/api/drafts",
    tags=["draft_management"],
)


def _format_draft_content(script_obj) -> dict:
    """将 ScriptFile 对象格式化为 JSON 字典"""
    if script_obj is None:
        return {}
    try:
        draft_content = json.loads(script_obj.dumps())
    except Exception as decode_err:
        logger.warning(f"Failed to decode draft to JSON object: {decode_err}")
        draft_content = script_obj.dumps()
    return draft_content


@router.get("/list")
async def list_drafts(
    page: int = Query(1, description="Page number (1-indexed)"),
    page_size: int = Query(100, description="Number of items per page"),
    limit: Optional[int] = Query(
        None, description="Deprecated - use page_size instead"
    ),
):
    """
    List all stored drafts with pagination support
    """
    try:
        # Backward compatibility: support old 'limit' parameter
        if limit is not None:
            page_size = limit
            page = 1  # Reset to first page when using limit

        pg_storage = get_postgres_storage()
        result = await pg_storage.list_drafts(page=page, page_size=page_size)

        logger.info(
            f"List drafts request: page={page}, page_size={page_size}, returned {len(result['drafts'])} drafts"
        )

        return {
            "success": True,
            "drafts": result["drafts"],
            "pagination": result["pagination"],
        }
    except Exception as e:
        logger.error(f"Failed to list drafts: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/stats")
async def get_storage_stats():
    """Get storage statistics"""
    try:
        stats = await get_cache_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.error(f"Failed to get storage stats: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}")
async def get_draft_info(draft_id: str):
    """Get draft metadata without loading the full object"""
    try:
        pg_storage = get_postgres_storage()
        metadata = await pg_storage.get_metadata(draft_id)

        if metadata is None:
            return JSONResponse(
                status_code=404, content={"success": False, "error": "Draft not found"}
            )

        return {"success": True, "draft": metadata}
    except Exception as e:
        logger.error(f"Failed to get draft {draft_id}: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}/content")
async def get_draft_content(draft_id: str):
    """
    Fetch full draft content JSON.
    """
    try:
        # 1. 优先从 Redis 读
        logger.debug(f"get_draft_content: 尝试从草稿缓存中读取草稿 {draft_id}")
        script_obj = await get_from_cache(draft_id)
        if script_obj is not None:
            logger.info(f"get_draft_content: 从缓存成功读取草稿 {draft_id}")
            draft_content = _format_draft_content(script_obj)
            return {"success": True, "draft_id": draft_id, "content": draft_content}
        
        # 2. Redis 未命中，处理脏数据/同步逻辑
        logger.debug(f"get_draft_content: 缓存未命中，检查脏数据标记 {draft_id}")
        # 2. Redis 未命中，处理脏数据/同步逻辑
        if REDIS_CACHE_AVAILABLE:
            try:
                redis_cache = get_redis_draft_cache()
                if redis_cache:
                    # sync_if_dirty 内部实现：检查 dirty -> 竞争锁 -> 同步 -> 写入 Redis
                    synced = await redis_cache.sync_if_dirty(draft_id)
                    
                    if synced:
                        # 同步成功或正在同步中，尝试再次从缓存读
                        script_obj = await get_from_cache(draft_id)
                        if script_obj is not None:
                            logger.info(f"get_draft_content: 同步后从缓存成功读取草稿 {draft_id}")
                            draft_content = _format_draft_content(script_obj)
                            return {"success": True, "draft_id": draft_id, "content": draft_content}
            except Exception as e:
                logger.warning(f"检查脏数据标记或同步失败: {e}，降级到 PostgreSQL")
        
        # 3. 从 PostgreSQL 读（没有脏数据或同步失败）
        logger.info(f"get_draft_content: 从 PostgreSQL 读取草稿 {draft_id}")
        pg_storage = get_postgres_storage()
        script_obj = await pg_storage.get_draft(draft_id)
        
        if script_obj is None:
            logger.warning(f"get_draft_content: 草稿 {draft_id} 在 PostgreSQL 中不存在")
            return JSONResponse(
                status_code=404, content={"success": False, "error": "Draft not found"}
            )

        draft_content = _format_draft_content(script_obj)
        return {"success": True, "draft_id": draft_id, "content": draft_content}
    except Exception as e:
        logger.error(f"Failed to get draft content for {draft_id}: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.delete("/{draft_id}")
async def delete_draft(draft_id: str):
    """Delete a draft from cache and soft-delete from database"""
    try:
        cache_removed = await remove_from_cache(draft_id)

        pg_storage = get_postgres_storage()
        db_deleted = await pg_storage.delete_draft(draft_id)

        if cache_removed or db_deleted:
            return {
                "success": True,
                "message": f"Draft {draft_id} deleted (cache_removed={cache_removed}, db_deleted={db_deleted})",
            }
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "Draft not found or could not be deleted",
                },
            )

    except Exception as e:
        logger.error(f"Failed to delete draft {draft_id}: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}/exists")
async def check_draft_exists(draft_id: str):
    """Check if a draft exists in storage"""
    try:
        pg_storage = get_postgres_storage()
        exists = await pg_storage.exists(draft_id)

        return {"success": True, "exists": exists, "draft_id": draft_id}
    except Exception as e:
        logger.error(f"Failed to check if draft {draft_id} exists: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}/versions")
async def list_draft_versions(draft_id: str):
    """List all versions of a draft"""
    try:
        pg_storage = get_postgres_storage()
        versions = await pg_storage.list_draft_versions(draft_id)

        return {
            "success": True,
            "draft_id": draft_id,
            "versions": versions,
            "count": len(versions),
        }
    except Exception as e:
        logger.error(f"Failed to list versions for draft {draft_id}: {e}")
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}/versions/{version}")
async def get_draft_version_content(draft_id: str, version: int):
    """Get full draft content for a specific version"""
    try:
        pg_storage = get_postgres_storage()
        script_obj = await pg_storage.get_draft_version(draft_id, version)

        if script_obj is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Version {version} not found for draft {draft_id}",
                },
            )

        draft_content = _format_draft_content(script_obj)
        return {
            "success": True,
            "draft_id": draft_id,
            "version": version,
            "content": draft_content,
        }
    except Exception as e:
        logger.error(
            f"Failed to get draft version content for {draft_id} version {version}: {e}"
        )
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )


@router.get("/{draft_id}/versions/{version}/metadata")
async def get_draft_version_metadata(draft_id: str, version: int):
    """Get metadata for a specific version of a draft"""
    try:
        pg_storage = get_postgres_storage()
        metadata = await pg_storage.get_draft_version_metadata(draft_id, version)

        if metadata is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Version {version} not found for draft {draft_id}",
                },
            )

        return {
            "success": True,
            "draft_id": draft_id,
            "version": version,
            "metadata": metadata,
        }
    except Exception as e:
        logger.error(
            f"Failed to get metadata for draft {draft_id} version {version}: {e}"
        )
        return JSONResponse(
            status_code=500, content={"success": False, "error": str(e)}
        )