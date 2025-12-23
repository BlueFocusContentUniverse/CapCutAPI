"""add framerate and resolution to video_tasks

Revision ID: 0016
Revises: 0015
Create Date: 2025-12-23 00:00:01

"""

import logging

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    logger.info("Adding framerate and resolution columns to video_tasks table")
    
    # Add framerate column
    op.add_column(
        "video_tasks",
        sa.Column("framerate", sa.String(32), nullable=True),
    )
    
    # Add resolution column
    op.add_column(
        "video_tasks",
        sa.Column("resolution", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    logger.info("Removing framerate and resolution columns from video_tasks table")
    
    # Remove framerate column
    op.drop_column("video_tasks", "framerate")
    
    # Remove resolution column
    op.drop_column("video_tasks", "resolution")
