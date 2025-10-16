"""
ORM models for Draft and VideoTask.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB

from db import Base


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String(255), unique=True, index=True, nullable=False)
    current_version = Column(Integer, nullable=False, default=1)

    # Serialized Script_file object (pickle bytes)
    data = Column(LargeBinary, nullable=False)

    # Quick access metadata
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)  # microseconds
    fps = Column(Float, nullable=True)
    version = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    draft_name = Column(String(255), nullable=True)
    # Resource origin of the draft: 'api' or 'mcp'
    resource = Column(SAEnum("api", "mcp", name="draft_resource"), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    accessed_at = Column(DateTime(timezone=True), nullable=True)

    # Soft delete flag
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)


class DraftVersion(Base):
    __tablename__ = "draft_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String(255), index=True, nullable=False)
    version = Column(Integer, nullable=False)

    data = Column(LargeBinary, nullable=False)

    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration = Column(Integer, nullable=True)
    fps = Column(Float, nullable=True)
    script_version = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    draft_name = Column(String(255), nullable=True)
    resource = Column(SAEnum("api", "mcp", name="draft_resource"), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("draft_id", "version", name="uq_draft_versions_draft_id_version"),
    )


class VideoTaskStatus(Enum):
    INITIALIZED = "initialized"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class VideoTask(Base):
    __tablename__ = "video_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(255), unique=True, index=True, nullable=False)
    draft_id = Column(String(255), index=True, nullable=False)
    # Name of the video/draft at the time of task creation
    video_name = Column(String(255), nullable=True)

    # status: initialized, processing, completed, failed
    status = Column(String(64), index=True, nullable=False, default="initialized")
    render_status = Column(SAEnum(VideoTaskStatus, name="video_task_status"), index=True, nullable=False, default=VideoTaskStatus.INITIALIZED)
    progress = Column(Integer, nullable=True)
    message = Column(Text, nullable=True)
    draft_url = Column(Text, nullable=True)

    # arbitrary extra data (e.g., Celery IDs, etc.)
    extra = Column(JSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


