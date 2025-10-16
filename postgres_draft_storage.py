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

    def save_draft(self, draft_id: str, script_obj: draft.Script_file) -> bool:
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

    def get_draft(self, draft_id: str) -> Optional[draft.Script_file]:
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

    def get_draft_version(self, draft_id: str, version: int) -> Optional[draft.Script_file]:
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

    def list_drafts(self, limit: int = 100) -> list:
        try:
            with get_session() as session:
                q = session.execute(
                    select(DraftModel).where(DraftModel.is_deleted.is_(False)).order_by(DraftModel.updated_at.desc()).limit(limit)
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
                return results
        except Exception as e:
            logger.error(f"Failed to list drafts: {e}")
            return []

    def cleanup_expired(self) -> int:
        # TTL semantics are not supported here; return 0 for compatibility
        return 0

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


