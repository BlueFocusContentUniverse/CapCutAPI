"""
PostgreSQL-backed storage for DraftArchive records.
Manages draft archival tracking and download URLs.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from db import get_async_session
from models import DraftArchive as DraftArchiveModel

logger = logging.getLogger(__name__)


class PostgresDraftArchiveStorage:
    def __init__(self) -> None:
        # Tables are initialized during app startup via init_db_async
        pass

    async def create_archive(
        self,
        draft_id: str,
        draft_version: Optional[int] = None,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        archive_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new draft archive record.

        Args:
            draft_id: The draft identifier
            draft_version: The version of the draft (optional)
            user_id: User ID who initiated the archive
            user_name: User name who initiated the archive
            archive_name: Custom name for the archive (optional)

        Returns:
            The archive_id (UUID as string) if created successfully, None otherwise
        """
        try:
            async with get_async_session() as session:
                archive_id = uuid.uuid4()
                archive = DraftArchiveModel(
                    archive_id=archive_id,
                    draft_id=draft_id,
                    draft_version=draft_version,
                    user_id=user_id,
                    user_name=user_name,
                    archive_name=archive_name,
                    progress=0.0,
                    total_files=0,
                    downloaded_files=0,
                )
                session.add(archive)
                logger.info(
                    f"Created draft archive {archive_id} for draft {draft_id} version {draft_version} with archive_name={archive_name}"
                )
                return str(archive_id)
        except SQLAlchemyError as e:
            logger.error(f"Database error creating draft archive for {draft_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create draft archive for {draft_id}: {e}")
            return None

    async def get_archive_by_draft(
        self, draft_id: str, draft_version: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get archive record by draft_id and optional draft_version.

        Args:
            draft_id: The draft identifier
            draft_version: The version of the draft (optional)

        Returns:
            Dictionary with archive details or None if not found
        """
        try:
            async with get_async_session() as session:
                query = select(DraftArchiveModel).where(
                    DraftArchiveModel.draft_id == draft_id
                )

                if draft_version is not None:
                    query = query.where(
                        DraftArchiveModel.draft_version == draft_version
                    )
                else:
                    query = query.where(DraftArchiveModel.draft_version.is_(None))

                q = await session.execute(query)
                row = q.scalar_one_or_none()

                if row is None:
                    logger.debug(
                        f"Archive not found for draft {draft_id} version {draft_version}"
                    )
                    return None

                return {
                    "archive_id": str(row.archive_id),
                    "draft_id": row.draft_id,
                    "draft_version": row.draft_version,
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "archive_name": row.archive_name,
                    "download_url": row.download_url,
                    "total_files": row.total_files,
                    "progress": row.progress,
                    "downloaded_files": row.downloaded_files,
                    "message": row.message,
                    "created_at": int(row.created_at.timestamp()),
                    "updated_at": int(row.updated_at.timestamp()),
                }
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving archive for draft {draft_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve archive for draft {draft_id}: {e}")
            return None

    async def get_archive_by_id(self, archive_id: str) -> Optional[Dict[str, Any]]:
        """
        Get archive record by archive_id.

        Args:
            archive_id: The archive identifier (UUID)

        Returns:
            Dictionary with archive details or None if not found
        """
        try:
            async with get_async_session() as session:
                q = await session.execute(
                    select(DraftArchiveModel).where(
                        DraftArchiveModel.archive_id == uuid.UUID(archive_id)
                    )
                )
                row = q.scalar_one_or_none()

                if row is None:
                    logger.warning(f"Archive {archive_id} not found")
                    return None

                return {
                    "archive_id": str(row.archive_id),
                    "draft_id": row.draft_id,
                    "draft_version": row.draft_version,
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "archive_name": row.archive_name,
                    "download_url": row.download_url,
                    "total_files": row.total_files,
                    "progress": row.progress,
                    "downloaded_files": row.downloaded_files,
                    "message": row.message,
                    "created_at": int(row.created_at.timestamp()),
                    "updated_at": int(row.updated_at.timestamp()),
                }
        except ValueError as e:
            logger.error(f"Invalid UUID format for archive_id {archive_id}: {e}")
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving archive {archive_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve archive {archive_id}: {e}")
            return None

    async def update_archive(
        self,
        archive_id: str,
        download_url: Optional[str] = None,
        total_files: Optional[int] = None,
        progress: Optional[float] = None,
        downloaded_files: Optional[int] = None,
        message: Optional[str] = None,
        draft_version: Optional[int] = None,
    ) -> bool:
        """
        Update archive record fields.

        Args:
            archive_id: The archive identifier (UUID)
            download_url: Download URL for the archived draft (optional)
            total_files: Total number of files to download (optional)
            progress: Progress percentage (0-100) (optional)
            downloaded_files: Number of files downloaded (optional)
            message: Status message (optional)
            draft_version: Draft version number (optional)

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            async with get_async_session() as session:
                q = await session.execute(
                    select(DraftArchiveModel)
                    .where(DraftArchiveModel.archive_id == uuid.UUID(archive_id))
                    .with_for_update()
                )
                row = q.scalar_one_or_none()

                if row is None:
                    logger.warning(f"Archive {archive_id} not found for update")
                    return False

                # Update allowed fields
                if download_url is not None:
                    row.download_url = download_url
                if total_files is not None:
                    row.total_files = total_files
                if progress is not None:
                    row.progress = progress
                if downloaded_files is not None:
                    row.downloaded_files = downloaded_files
                if message is not None:
                    row.message = message
                if draft_version is not None:
                    row.draft_version = draft_version
                row.updated_at = datetime.now(timezone.utc)
                logger.info(f"Updated archive {archive_id}")
                return True
        except ValueError as e:
            logger.error(f"Invalid UUID format for archive_id {archive_id}: {e}")
            return False
        except SQLAlchemyError as e:
            logger.error(f"Database error updating archive {archive_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to update archive {archive_id}: {e}")
            return False

    async def list_archives(
        self,
        draft_id: Optional[str] = None,
        user_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """
        List draft archives with optional filtering and pagination.

        Args:
            draft_id: Filter by draft_id (optional)
            user_id: Filter by user_id (optional)
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Dict containing archives, pagination info, and total count
        """
        try:
            page = max(1, page)
            page_size = min(max(1, page_size), 1000)
            offset = (page - 1) * page_size

            async with get_async_session() as session:
                # Build query
                query = select(DraftArchiveModel)

                if draft_id:
                    query = query.where(DraftArchiveModel.draft_id == draft_id)
                if user_id:
                    query = query.where(DraftArchiveModel.user_id == user_id)

                # Get total count
                from sqlalchemy import func

                count_query = select(func.count(DraftArchiveModel.id))
                if draft_id:
                    count_query = count_query.where(
                        DraftArchiveModel.draft_id == draft_id
                    )
                if user_id:
                    count_query = count_query.where(
                        DraftArchiveModel.user_id == user_id
                    )

                count_q = await session.execute(count_query)
                total_count = count_q.scalar() or 0

                # Get paginated results
                query = (
                    query.order_by(DraftArchiveModel.created_at.desc())
                    .limit(page_size)
                    .offset(offset)
                )
                q = await session.execute(query)
                rows = q.scalars().all()

                results = []
                for row in rows:
                    results.append(
                        {
                            "archive_id": str(row.archive_id),
                            "draft_id": row.draft_id,
                            "draft_version": row.draft_version,
                            "user_id": row.user_id,
                            "user_name": row.user_name,
                            "archive_name": row.archive_name,
                            "download_url": row.download_url,
                            "total_files": row.total_files,
                            "progress": row.progress,
                            "downloaded_files": row.downloaded_files,
                            "message": row.message,
                            "created_at": int(row.created_at.timestamp()),
                            "updated_at": int(row.updated_at.timestamp()),
                        }
                    )

                total_pages = (
                    (total_count + page_size - 1) // page_size if page_size > 0 else 0
                )

                logger.info(
                    f"Listed archives: page={page}, page_size={page_size}, total={total_count}"
                )

                return {
                    "archives": results,
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_prev": page > 1,
                    },
                }
        except Exception as e:
            logger.error(f"Failed to list archives: {e}")
            return {
                "archives": [],
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }

    async def delete_archive(self, archive_id: str) -> bool:
        """
        Delete an archive record.

        Args:
            archive_id: The archive identifier (UUID)

        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            async with get_async_session() as session:
                q = await session.execute(
                    select(DraftArchiveModel).where(
                        DraftArchiveModel.archive_id == uuid.UUID(archive_id)
                    )
                )
                row = q.scalar_one_or_none()

                if row is None:
                    logger.warning(f"Archive {archive_id} not found for deletion")
                    return False

                await session.delete(row)
                logger.info(f"Deleted archive {archive_id}")
                return True
        except ValueError as e:
            logger.error(f"Invalid UUID format for archive_id {archive_id}: {e}")
            return False
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting archive {archive_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete archive {archive_id}: {e}")
            return False


# Global instance for easy import
pg_archive_storage: Optional[PostgresDraftArchiveStorage] = None


def get_postgres_archive_storage() -> PostgresDraftArchiveStorage:
    global pg_archive_storage
    if pg_archive_storage is None:
        pg_archive_storage = PostgresDraftArchiveStorage()
    return pg_archive_storage
