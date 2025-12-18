"""
Repository for VideoTask model operations.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from db import get_async_session
from models import Video, VideoTask, VideoTaskStatus
from util.helpers import sign_cdn_type_d

logger = logging.getLogger(__name__)


class VideoTaskRepository:
    """Repository for managing VideoTask records."""

    async def update_task_status(
        self,
        task_id: str,
        status: Optional[str] = None,
        render_status: Optional[VideoTaskStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        video_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update VideoTask status and related fields.

        Args:
            task_id: Task identifier
            status: Optional status string (e.g., "initialized", "pending", "processing", "completed", "failed")
            render_status: Optional VideoTaskStatus enum value
            progress: Optional progress value (0.0 - 100.0)
            message: Optional status message
            video_id: Optional video_id (UUID string) to link to the task
            extra: Optional additional metadata

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            async with get_async_session() as session:
                task = (
                    await session.execute(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                ).scalar_one_or_none()

                if task is None:
                    logger.warning(f"VideoTask {task_id} not found for update")
                    return False

                # Update only provided fields
                if status is not None:
                    task.status = status
                if render_status is not None:
                    task.render_status = render_status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if video_id is not None:
                    task.video_id = video_id
                if extra is not None:
                    # Merge with existing extra data if it exists
                    if task.extra:
                        merged_extra = dict(task.extra)
                        merged_extra.update(extra)
                        task.extra = merged_extra
                    else:
                        task.extra = extra

                task.updated_at = datetime.now(timezone.utc)

                logger.info(
                    f"Updated VideoTask {task_id}: status={status}, render_status={render_status}, progress={progress}"
                )
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error updating VideoTask {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to update VideoTask {task_id}: {e}")
            return False

    async def link_video_to_task(self, task_id: str, video_id: str) -> bool:
        """
        Link a video_id to a VideoTask.

        Args:
            task_id: Task identifier
            video_id: Video identifier (UUID string) to link

        Returns:
            True if link succeeded, False otherwise
        """
        try:
            async with get_async_session() as session:
                task = (
                    await session.execute(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                ).scalar_one_or_none()

                if task is None:
                    logger.warning(f"VideoTask {task_id} not found for linking video")
                    return False

                task.video_id = video_id
                task.updated_at = datetime.now(timezone.utc)

                logger.info(f"Linked video {video_id} to VideoTask {task_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error linking video to VideoTask {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to link video to VideoTask {task_id}: {e}")
            return False

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a VideoTask by task_id.

        Args:
            task_id: Task identifier

        Returns:
            Dict with task metadata or None if not found
        """
        try:
            async with get_async_session() as session:
                row = (
                    await session.execute(
                        select(VideoTask, Video.oss_url.label("oss_url"))
                        .join(Video, VideoTask.video_id == Video.video_id, isouter=True)
                        .where(VideoTask.task_id == task_id)
                    )
                ).one_or_none()

                if row is None:
                    logger.warning(f"VideoTask {task_id} not found")
                    return None

                task, oss_url = row
                signed_oss_url = sign_cdn_type_d(oss_url) if oss_url else None

                return {
                    "id": task.id,
                    "task_id": task.task_id,
                    "draft_id": task.draft_id,
                    "video_id": task.video_id,
                    "video_name": task.video_name,
                    "status": task.status,
                    "render_status": task.render_status.value
                    if task.render_status
                    else None,
                    "progress": task.progress,
                    "message": task.message,
                    "extra": task.extra,
                    "oss_url": signed_oss_url,
                    "created_at": int(task.created_at.timestamp()),
                    "updated_at": int(task.updated_at.timestamp()),
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving VideoTask {task_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve VideoTask {task_id}: {e}")
            return None

    async def create_task(
        self,
        task_id: str,
        draft_id: str,
        video_name: Optional[str] = None,
        status: str = "initialized",
        render_status: VideoTaskStatus = VideoTaskStatus.INITIALIZED,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Create a new VideoTask record.

        Args:
            task_id: Unique task identifier
            draft_id: Associated draft identifier
            video_name: Optional video name
            status: Initial status (default: "initialized")
            render_status: Initial render status (default: INITIALIZED)
            extra: Optional additional metadata

        Returns:
            True if creation succeeded, False otherwise
        """
        try:
            async with get_async_session() as session:
                # Check if task_id already exists
                existing = (
                    await session.execute(
                        select(VideoTask).where(VideoTask.task_id == task_id)
                    )
                ).scalar_one_or_none()

                if existing:
                    logger.warning(f"VideoTask {task_id} already exists")
                    return False

                task = VideoTask(
                    task_id=task_id,
                    draft_id=draft_id,
                    video_name=video_name,
                    status=status,
                    render_status=render_status,
                    extra=extra,
                )
                session.add(task)

                logger.info(f"Created VideoTask {task_id} for draft {draft_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error creating VideoTask {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to create VideoTask {task_id}: {e}")
            return False

    async def list_tasks(
        self,
        page: int = 1,
        page_size: int = 50,
        draft_id: Optional[str] = None,
        render_status: Optional[VideoTaskStatus] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        List VideoTasks with optional filters and include related Video.oss_url.

        Returns camelCase keys to match Node.js consumers.
        """
        try:
            page = max(1, page)
            page_size = min(max(1, page_size), 500)
            offset = (page - 1) * page_size

            async with get_async_session() as session:
                base_query = select(VideoTask, Video.oss_url.label("oss_url")).join(
                    Video, VideoTask.video_id == Video.video_id, isouter=True
                )

                count_query = select(func.count(VideoTask.id))

                if draft_id:
                    base_query = base_query.where(VideoTask.draft_id == draft_id)
                    count_query = count_query.where(VideoTask.draft_id == draft_id)

                if render_status:
                    base_query = base_query.where(
                        VideoTask.render_status == render_status
                    )
                    count_query = count_query.where(
                        VideoTask.render_status == render_status
                    )

                if start_date:
                    base_query = base_query.where(VideoTask.created_at >= start_date)
                    count_query = count_query.where(VideoTask.created_at >= start_date)

                if end_date:
                    base_query = base_query.where(VideoTask.created_at <= end_date)
                    count_query = count_query.where(VideoTask.created_at <= end_date)

                total_count = (await session.execute(count_query)).scalar() or 0

                rows = (
                    await session.execute(
                        base_query.order_by(VideoTask.created_at.desc())
                        .limit(page_size)
                        .offset(offset)
                    )
                ).all()

                items: list[dict[str, Any]] = []
                for video_task, oss_url in rows:
                    items.append(
                        {
                            "id": video_task.id,
                            "taskId": video_task.task_id,
                            "draftId": video_task.draft_id,
                            "videoId": video_task.video_id,
                            "videoName": video_task.video_name,
                            "renderStatus": video_task.render_status.value
                            if video_task.render_status
                            else None,
                            "progress": video_task.progress,
                            "message": video_task.message,
                            "extra": video_task.extra,
                            "createdAt": int(video_task.created_at.timestamp())
                            if video_task.created_at
                            else None,
                            "updatedAt": int(video_task.updated_at.timestamp())
                            if video_task.updated_at
                            else None,
                            "ossUrl": sign_cdn_type_d(oss_url) if oss_url else None,
                        }
                    )

                total_pages = (
                    (total_count + page_size - 1) // page_size if page_size else 0
                )

                return {
                    "items": items,
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_prev": page > 1,
                    },
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error listing VideoTasks: {e}")
            return {
                "items": [],
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }
        except Exception as e:
            logger.error(f"Failed to list VideoTasks: {e}")
            return {
                "items": [],
                "pagination": {
                    "page": 1,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0,
                    "has_next": False,
                    "has_prev": False,
                },
            }


# Global repository instance
_video_task_repository: Optional[VideoTaskRepository] = None


def get_video_task_repository() -> VideoTaskRepository:
    """Get or create the global VideoTaskRepository instance."""
    global _video_task_repository
    if _video_task_repository is None:
        _video_task_repository = VideoTaskRepository()
    return _video_task_repository