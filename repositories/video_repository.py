"""
Repository for Video model operations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from db import get_session
from models import Video
from util.cos_client import get_cos_client

logger = logging.getLogger(__name__)


class VideoRepository:
    """Repository for managing Video records and associated OSS objects."""

    def create_video(
        self,
        draft_id: str,
        oss_url: str,
        video_name: Optional[str] = None,
        resolution: Optional[str] = None,
        framerate: Optional[str] = None,
        duration: Optional[float] = None,
        file_size: Optional[int] = None,
        thumbnail_url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create a new video record with auto-generated UUID video_id.

        Args:
            draft_id: Associated draft identifier
            oss_url: Object storage URL for the video file
            video_name: Optional video name
            resolution: Optional resolution (e.g., "1920x1080", "1080p")
            framerate: Optional framerate (e.g., "30", "60")
            duration: Optional duration in seconds
            file_size: Optional file size in bytes
            thumbnail_url: Optional thumbnail/preview URL
            extra: Optional additional metadata as JSONB

        Returns:
            The generated video_id (UUID string) if creation succeeded, None otherwise
        """
        try:
            with get_session() as session:
                # Generate UUID for video_id
                video_id = str(uuid.uuid4())

                video = Video(
                    video_id=video_id,
                    draft_id=draft_id,
                    video_name=video_name,
                    resolution=resolution,
                    framerate=framerate,
                    duration=duration,
                    file_size=file_size,
                    oss_url=oss_url,
                    thumbnail_url=thumbnail_url,
                    extra=extra,
                )
                session.add(video)

                logger.info(
                    f"Created video record: video_id={video_id} for draft {draft_id}"
                )
                return video_id

        except SQLAlchemyError as e:
            logger.error(f"Database error creating video for draft {draft_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create video for draft {draft_id}: {e}")
            return None

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a video by video_id (UUID string).

        Args:
            video_id: Video identifier (UUID string)

        Returns:
            Dict with video metadata or None if not found
        """
        try:
            with get_session() as session:
                video = session.execute(
                    select(Video).where(Video.video_id == video_id)
                ).scalar_one_or_none()

                if video is None:
                    logger.warning(f"Video {video_id} not found")
                    return None

                return {
                    "video_id": video.video_id,
                    "draft_id": video.draft_id,
                    "video_name": video.video_name,
                    "resolution": video.resolution,
                    "framerate": video.framerate,
                    "duration": video.duration,
                    "file_size": video.file_size,
                    "oss_url": video.oss_url,
                    "thumbnail_url": video.thumbnail_url,
                    "extra": video.extra,
                    "created_at": int(video.created_at.timestamp()),
                    "updated_at": int(video.updated_at.timestamp()),
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving video {video_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve video {video_id}: {e}")
            return None

    def get_videos_by_draft(self, draft_id: str) -> List[Dict[str, Any]]:
        """
        Get all videos associated with a draft_id.

        Args:
            draft_id: Draft identifier

        Returns:
            List of video metadata dicts
        """
        try:
            with get_session() as session:
                videos = (
                    session.execute(
                        select(Video)
                        .where(Video.draft_id == draft_id)
                        .order_by(Video.created_at.desc())
                    )
                    .scalars()
                    .all()
                )

                results = []
                for video in videos:
                    results.append(
                        {
                            "video_id": video.video_id,
                            "draft_id": video.draft_id,
                            "video_name": video.video_name,
                            "resolution": video.resolution,
                            "framerate": video.framerate,
                            "duration": video.duration,
                            "file_size": video.file_size,
                            "oss_url": video.oss_url,
                            "thumbnail_url": video.thumbnail_url,
                            "extra": video.extra,
                            "created_at": int(video.created_at.timestamp()),
                            "updated_at": int(video.updated_at.timestamp()),
                        }
                    )

                logger.info(f"Retrieved {len(results)} videos for draft {draft_id}")
                return results

        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving videos for draft {draft_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to retrieve videos for draft {draft_id}: {e}")
            return []

    def update_video(
        self,
        video_id: str,
        video_name: Optional[str] = None,
        resolution: Optional[str] = None,
        framerate: Optional[str] = None,
        duration: Optional[float] = None,
        file_size: Optional[int] = None,
        oss_url: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update video metadata.

        Args:
            video_id: Video identifier (UUID string)
            video_name: Optional new video name
            resolution: Optional new resolution
            framerate: Optional new framerate
            duration: Optional new duration
            file_size: Optional new file size
            oss_url: Optional new OSS URL
            thumbnail_url: Optional new thumbnail URL
            extra: Optional new extra metadata

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            with get_session() as session:
                video = session.execute(
                    select(Video).where(Video.video_id == video_id)
                ).scalar_one_or_none()

                if video is None:
                    logger.warning(f"Video {video_id} not found for update")
                    return False

                # Update only provided fields
                if video_name is not None:
                    video.video_name = video_name
                if resolution is not None:
                    video.resolution = resolution
                if framerate is not None:
                    video.framerate = framerate
                if duration is not None:
                    video.duration = duration
                if file_size is not None:
                    video.file_size = file_size
                if oss_url is not None:
                    video.oss_url = oss_url
                if thumbnail_url is not None:
                    video.thumbnail_url = thumbnail_url
                if extra is not None:
                    video.extra = extra

                video.updated_at = datetime.now(timezone.utc)

                logger.info(f"Updated video {video_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error updating video {video_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to update video {video_id}: {e}")
            return False

    def delete_video(self, video_id: str, delete_oss: bool = True) -> bool:
        """
        Delete a video record and optionally its remote OSS object.

        Args:
            video_id: Video identifier (UUID string)
            delete_oss: If True, also delete the remote OSS object

        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            with get_session() as session:
                video = session.execute(
                    select(Video).where(Video.video_id == video_id)
                ).scalar_one_or_none()

                if video is None:
                    logger.warning(f"Video {video_id} not found for deletion")
                    return False

                oss_url = video.oss_url

                # Delete from database
                session.delete(video)
                logger.info(f"Deleted video record {video_id} from database")

            # Delete from OSS if requested and URL exists
            if delete_oss and oss_url:
                cos_client = get_cos_client()
                if cos_client.is_available():
                    oss_deleted = cos_client.delete_object_from_url(oss_url)
                    if oss_deleted:
                        logger.info(f"Deleted OSS object for video {video_id}")
                    else:
                        logger.warning(
                            f"Failed to delete OSS object for video {video_id}"
                        )
                else:
                    logger.warning(
                        f"COS client not available, skipping OSS deletion for video {video_id}"
                    )

            return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting video {video_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete video {video_id}: {e}")
            return False

    def list_videos(
        self, page: int = 1, page_size: int = 100, draft_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List videos with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            draft_id: Optional filter by draft_id

        Returns:
            Dict with videos list and pagination metadata
        """
        try:
            # Ensure valid pagination parameters
            page = max(1, page)
            page_size = min(max(1, page_size), 1000)
            offset = (page - 1) * page_size

            with get_session() as session:
                # Build query
                query = select(Video)
                if draft_id:
                    query = query.where(Video.draft_id == draft_id)

                # Get total count
                count_query = select(func.count(Video.id))
                if draft_id:
                    count_query = count_query.where(Video.draft_id == draft_id)
                total_count = session.execute(count_query).scalar() or 0

                # Get paginated results
                videos = (
                    session.execute(
                        query.order_by(Video.created_at.desc())
                        .limit(page_size)
                        .offset(offset)
                    )
                    .scalars()
                    .all()
                )

                results = []
                for video in videos:
                    results.append(
                        {
                            "video_id": video.video_id,
                            "draft_id": video.draft_id,
                            "video_name": video.video_name,
                            "resolution": video.resolution,
                            "framerate": video.framerate,
                            "duration": video.duration,
                            "file_size": video.file_size,
                            "oss_url": video.oss_url,
                            "thumbnail_url": video.thumbnail_url,
                            "extra": video.extra,
                            "created_at": int(video.created_at.timestamp()),
                            "updated_at": int(video.updated_at.timestamp()),
                        }
                    )

                total_pages = (
                    (total_count + page_size - 1) // page_size if page_size > 0 else 0
                )

                logger.info(
                    f"Listed videos: page={page}, page_size={page_size}, total={total_count}"
                )

                return {
                    "videos": results,
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
            logger.error(f"Database error listing videos: {e}")
            return {
                "videos": [],
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
            logger.error(f"Failed to list videos: {e}")
            return {
                "videos": [],
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
_video_repository: Optional[VideoRepository] = None


def get_video_repository() -> VideoRepository:
    """Get or create the global VideoRepository instance."""
    global _video_repository
    if _video_repository is None:
        _video_repository = VideoRepository()
    return _video_repository
