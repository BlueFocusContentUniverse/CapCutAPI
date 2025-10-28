"""
PostgreSQL-backed storage for CapCut draft objects.
Retains a compatible interface with redis_draft_storage.RedisDraftStorage where practical.
"""

import logging
import pickle
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import pyJianYingDraft as draft
from db import get_session, init_db
from models import Draft as DraftModel
from models import DraftVersion as DraftVersionModel

logger = logging.getLogger(__name__)


class PostgresDraftStorage:
    def __init__(self) -> None:
        # Ensure tables exist
        try:
            init_db()
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def save_draft(self, draft_id: str, script_obj: draft.ScriptFile) -> bool:
        try:
            serialized_data = pickle.dumps(script_obj)

            with get_session() as session:
                # Find any existing row regardless of deletion status
                q = session.execute(select(DraftModel).where(DraftModel.draft_id == draft_id))
                existing = q.scalar_one_or_none()

                if existing is None:
                    row = DraftModel(
                        draft_id=draft_id,
                        data=serialized_data,
                        width=getattr(script_obj, "width", None),
                        height=getattr(script_obj, "height", None),
                        duration=getattr(script_obj, "duration", None),
                        fps=getattr(script_obj, "fps", None),
                        version=getattr(script_obj, "version", "1.0"),
                        size_bytes=len(serialized_data),
                        draft_name=getattr(script_obj, "name", None),
                        resource=getattr(script_obj, "resource", None),
                        current_version=1,
                        accessed_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                else:
                    # Persist previous version into history table before updating
                    previous_version = existing.current_version or 1
                    history = DraftVersionModel(
                        draft_id=existing.draft_id,
                        version=previous_version,
                        data=existing.data,
                        width=existing.width,
                        height=existing.height,
                        duration=existing.duration,
                        fps=existing.fps,
                        script_version=existing.version,
                        size_bytes=existing.size_bytes,
                        draft_name=existing.draft_name,
                        resource=existing.resource,
                    )
                    session.add(history)

                    # Update in place; if previously soft-deleted, resurrect it
                    existing.data = serialized_data
                    existing.width = getattr(script_obj, "width", None)
                    existing.height = getattr(script_obj, "height", None)
                    existing.duration = getattr(script_obj, "duration", None)
                    existing.fps = getattr(script_obj, "fps", None)
                    existing.version = getattr(script_obj, "version", "1.0")
                    existing.size_bytes = len(serialized_data)
                    existing.draft_name = getattr(script_obj, "name", None)
                    existing.resource = getattr(script_obj, "resource", None)
                    existing.is_deleted = False
                    existing.current_version = previous_version + 1
                    existing.accessed_at = datetime.now(timezone.utc)

            logger.info(f"Successfully saved draft {draft_id} to Postgres (size: {len(serialized_data)} bytes)")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Database error saving draft {draft_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to save draft {draft_id}: {e}")
            return False

    def get_draft(self, draft_id: str) -> Optional[draft.ScriptFile]:
        try:
            with get_session() as session:
                q = session.execute(select(DraftModel).where(DraftModel.draft_id == draft_id, DraftModel.is_deleted.is_(False)))
                row = q.scalar_one_or_none()
                if row is None:
                    logger.warning(f"Draft {draft_id} not found in Postgres")
                    return None
                script_obj = pickle.loads(row.data)
                row.accessed_at = datetime.now(timezone.utc)
                return script_obj
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving draft {draft_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve draft {draft_id}: {e}")
            return None

    def get_draft_version(self, draft_id: str, version: int) -> Optional[draft.ScriptFile]:
        try:
            with get_session() as session:
                # First try to fetch from history table
                q = session.execute(
                    select(DraftVersionModel)
                    .where(
                        DraftVersionModel.draft_id == draft_id,
                        DraftVersionModel.version == version,
                    )
                )
                row = q.scalar_one_or_none()

                if row is None:
                    # If version equals current_version we can read from main table
                    current = session.execute(
                        select(DraftModel).where(
                            DraftModel.draft_id == draft_id,
                            DraftModel.is_deleted.is_(False),
                        )
                    ).scalar_one_or_none()
                    if current is None:
                        logger.warning(f"Draft {draft_id} not found when requesting version {version}")
                        return None
                    if (current.current_version or 1) != version:
                        logger.warning(
                            f"Draft {draft_id} version {version} not found in history and does not match current version"
                        )
                        return None
                    script_obj = pickle.loads(current.data)
                    current.accessed_at = datetime.now(timezone.utc)
                    return script_obj

                script_obj = pickle.loads(row.data)
                return script_obj
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving draft {draft_id} version {version}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve draft {draft_id} version {version}: {e}")
            return None

    def exists(self, draft_id: str) -> bool:
        try:
            with get_session() as session:
                q = session.execute(select(DraftModel.id).where(DraftModel.draft_id == draft_id, DraftModel.is_deleted.is_(False)))
                return q.scalar_one_or_none() is not None
        except Exception as e:
            logger.error(f"Failed to check existence of draft {draft_id}: {e}")
            return False

    def delete_draft(self, draft_id: str) -> bool:
        try:
            with get_session() as session:
                q = session.execute(select(DraftModel).where(DraftModel.draft_id == draft_id))
                row = q.scalar_one_or_none()
                if row is None:
                    return False
                row.is_deleted = True
                row.updated_at = datetime.now(timezone.utc)
                return True
        except Exception as e:
            logger.error(f"Failed to delete draft {draft_id}: {e}")
            return False

    def get_metadata(self, draft_id: str) -> Optional[Dict[str, Any]]:
        try:
            with get_session() as session:
                q = session.execute(select(DraftModel).where(DraftModel.draft_id == draft_id, DraftModel.is_deleted.is_(False)))
                row = q.scalar_one_or_none()
                if row is None:
                    return None
                return {
                    "draft_id": row.draft_id,
                    "draft_name": row.draft_name,
                    "resource": row.resource,
                    "width": row.width,
                    "height": row.height,
                    "duration": row.duration,
                    "fps": row.fps,
                    "created_at": int(row.created_at.timestamp()),
                    "updated_at": int(row.updated_at.timestamp()),
                    "version": row.version,
                    "current_version": row.current_version,
                    "size_bytes": row.size_bytes,
                    "accessed_at": int(row.accessed_at.timestamp()) if row.accessed_at else None,
                }
        except Exception as e:
            logger.error(f"Failed to get metadata for draft {draft_id}: {e}")
            return None

    def list_drafts(self, page: int = 1, page_size: int = 100, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        List drafts with pagination support

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            limit: Deprecated - kept for backward compatibility

        Returns:
            Dict containing drafts, pagination info, and total count
        """
        try:
            # Backward compatibility: if limit is provided, use old behavior
            if limit is not None:
                page_size = limit

            # Ensure valid pagination parameters
            page = max(1, page)
            page_size = min(max(1, page_size), 1000)  # Cap at 1000 items per page
            offset = (page - 1) * page_size

            with get_session() as session:
                # Get total count
                from sqlalchemy import func
                count_q = session.execute(
                    select(func.count(DraftModel.id)).where(DraftModel.is_deleted.is_(False))
                )
                total_count = count_q.scalar() or 0

                # Get paginated results
                q = session.execute(
                    select(DraftModel)
                    .where(DraftModel.is_deleted.is_(False))
                    .order_by(DraftModel.updated_at.desc())
                    .limit(page_size)
                    .offset(offset)
                )
                rows = q.scalars().all()

                results = []
                for row in rows:
                    results.append({
                        "draft_id": row.draft_id,
                        "draft_name": row.draft_name,
                        "resource": row.resource,
                        "width": row.width,
                        "height": row.height,
                        "duration": row.duration,
                        "fps": row.fps,
                        "created_at": int(row.created_at.timestamp()),
                        "updated_at": int(row.updated_at.timestamp()),
                        "version": row.version,
                        "current_version": row.current_version,
                        "size_bytes": row.size_bytes,
                    })

                total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

                logger.info(f"Listed drafts: page={page}, page_size={page_size}, total={total_count}")

                return {
                    "drafts": results,
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_prev": page > 1
                    }
                }
        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            return {
                "drafts": [],
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False
                }
            }

    def cleanup_expired(self) -> int:
        # TTL semantics are not supported here; return 0 for compatibility
        return 0

    def list_draft_versions(self, draft_id: str) -> list:
        """List all versions of a draft"""
        try:
            with get_session() as session:
                # Get current version from main table
                current_q = session.execute(
                    select(DraftModel).where(
                        DraftModel.draft_id == draft_id,
                        DraftModel.is_deleted.is_(False)
                    )
                )
                current_row = current_q.scalar_one_or_none()

                versions = []

                # Add current version if exists
                if current_row:
                    versions.append({
                        "version": current_row.current_version or 1,
                        "is_current": True,
                        "created_at": int(current_row.created_at.timestamp()),
                        "updated_at": int(current_row.updated_at.timestamp()),
                        "draft_name": current_row.draft_name,
                        "width": current_row.width,
                        "height": current_row.height,
                        "duration": current_row.duration,
                        "fps": current_row.fps,
                        "size_bytes": current_row.size_bytes,
                    })

                # Get historical versions
                history_q = session.execute(
                    select(DraftVersionModel).where(
                        DraftVersionModel.draft_id == draft_id
                    ).order_by(DraftVersionModel.version.desc())
                )
                history_rows = history_q.scalars().all()

                for row in history_rows:
                    # Skip if this version is already in current (shouldn't happen, but safety check)
                    if any(v["version"] == row.version for v in versions):
                        continue

                    versions.append({
                        "version": row.version,
                        "is_current": False,
                        "created_at": int(row.created_at.timestamp()),
                        "updated_at": int(row.created_at.timestamp()),
                        "draft_name": row.draft_name,
                        "width": row.width,
                        "height": row.height,
                        "duration": row.duration,
                        "fps": row.fps,
                        "size_bytes": row.size_bytes,
                    })

                # Sort by version number descending
                versions.sort(key=lambda x: x["version"], reverse=True)
                return versions

        except Exception as e:
            logger.error(f"Failed to list versions for draft {draft_id}: {e}")
            return []

    def get_draft_version_metadata(self, draft_id: str, version: int) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific version of a draft"""
        try:
            with get_session() as session:
                # Check if this is the current version first
                current_q = session.execute(
                    select(DraftModel).where(
                        DraftModel.draft_id == draft_id,
                        DraftModel.is_deleted.is_(False)
                    )
                )
                current_row = current_q.scalar_one_or_none()

                if current_row and (current_row.current_version or 1) == version:
                    return {
                        "draft_id": current_row.draft_id,
                        "version": version,
                        "is_current": True,
                        "draft_name": current_row.draft_name,
                        "resource": current_row.resource,
                        "width": current_row.width,
                        "height": current_row.height,
                        "duration": current_row.duration,
                        "fps": current_row.fps,
                        "created_at": int(current_row.created_at.timestamp()),
                        "updated_at": int(current_row.updated_at.timestamp()),
                        "size_bytes": current_row.size_bytes,
                    }

                # Check historical versions
                history_q = session.execute(
                    select(DraftVersionModel).where(
                        DraftVersionModel.draft_id == draft_id,
                        DraftVersionModel.version == version
                    )
                )
                history_row = history_q.scalar_one_or_none()

                if history_row:
                    return {
                        "draft_id": history_row.draft_id,
                        "version": history_row.version,
                        "is_current": False,
                        "draft_name": history_row.draft_name,
                        "resource": history_row.resource,
                        "width": history_row.width,
                        "height": history_row.height,
                        "duration": history_row.duration,
                        "fps": history_row.fps,
                        "created_at": int(history_row.created_at.timestamp()),
                        "size_bytes": history_row.size_bytes,
                    }

                return None

        except Exception as e:
            logger.error(f"Failed to get metadata for draft {draft_id} version {version}: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        try:
            with get_session() as session:
                total = session.execute(select(DraftModel.id)).scalars().all()
                return {
                    "total_drafts": len(total),
                    "backend": "postgresql"
                }
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {}


# Global instance for easy import
pg_storage: Optional[PostgresDraftStorage] = None


def get_postgres_storage() -> PostgresDraftStorage:
    global pg_storage
    if pg_storage is None:
        pg_storage = PostgresDraftStorage()
    return pg_storage


