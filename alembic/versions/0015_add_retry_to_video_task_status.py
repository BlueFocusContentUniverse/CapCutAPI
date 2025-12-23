"""add retry to video_task_status enum

Revision ID: 0015
Revises: 0014
Create Date: 2025-12-23 00:00:00

"""

import logging

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    logger.info("Adding RETRY to video_task_status enum")

    new_enum = sa.Enum(
        "INITIALIZED",
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        "RETRY",
        name="video_task_status_new",
    )
    new_enum.create(bind, checkfirst=True)

    op.execute("ALTER TABLE video_tasks ALTER COLUMN render_status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE video_tasks
        ALTER COLUMN render_status
        TYPE video_task_status_new
        USING render_status::text::video_task_status_new
        """
    )
    op.execute(
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'COMPLETED'"
    )
    op.execute("ALTER TYPE video_task_status RENAME TO video_task_status_old")
    op.execute("ALTER TYPE video_task_status_new RENAME TO video_task_status")
    op.execute("DROP TYPE video_task_status_old")

    logger.info("Successfully added RETRY to video_task_status enum")


def downgrade() -> None:
    bind = op.get_bind()
    logger.info("Downgrading: Removing RETRY from video_task_status enum")

    old_enum = sa.Enum(
        "INITIALIZED",
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        name="video_task_status_new",
    )
    old_enum.create(bind, checkfirst=True)

    op.execute("ALTER TABLE video_tasks ALTER COLUMN render_status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE video_tasks
        ALTER COLUMN render_status
        TYPE video_task_status_new
        USING 
            CASE 
                WHEN render_status::text = 'RETRY' THEN 'FAILED'::video_task_status_new
                ELSE render_status::text::video_task_status_new
            END
        """
    )
    op.execute(
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'COMPLETED'"
    )
    op.execute("ALTER TYPE video_task_status RENAME TO video_task_status_old")
    op.execute("ALTER TYPE video_task_status_new RENAME TO video_task_status")
    op.execute("DROP TYPE video_task_status_old")

    logger.info("Successfully removed RETRY from video_task_status enum")
