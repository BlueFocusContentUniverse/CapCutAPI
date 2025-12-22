"""revert video_task_status enum to uppercase values

Revision ID: 0014
Revises: 0013
Create Date: 2025-12-22 00:00:01

"""

import logging

import sqlalchemy as sa

from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    logger.info(
        "Reverting video_task_status enum to uppercase values as in migration 0008"
    )

    new_enum = sa.Enum(
        "INITIALIZED",
        "PENDING",
        "PROCESSING",
        "COMPLETED",
        "FAILED",
        name="video_task_status_new",
    )
    new_enum.create(bind, checkfirst=True)

    op.execute("ALTER TABLE video_tasks ALTER COLUMN render_status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE video_tasks
        ALTER COLUMN render_status
        TYPE video_task_status_new
        USING upper(render_status::text)::video_task_status_new
        """
    )
    op.execute(
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'COMPLETED'"
    )
    op.execute("ALTER TYPE video_task_status RENAME TO video_task_status_old")
    op.execute("ALTER TYPE video_task_status_new RENAME TO video_task_status")
    op.execute("DROP TYPE video_task_status_old")


def downgrade() -> None:
    bind = op.get_bind()
    logger.info("Downgrading video_task_status enum back to lowercase values")

    lower_enum = sa.Enum(
        "initialized",
        "pending",
        "processing",
        "completed",
        "failed",
        name="video_task_status_new",
    )
    lower_enum.create(bind, checkfirst=True)

    op.execute("ALTER TABLE video_tasks ALTER COLUMN render_status DROP DEFAULT")
    op.execute(
        """
        ALTER TABLE video_tasks
        ALTER COLUMN render_status
        TYPE video_task_status_new
        USING lower(render_status::text)::video_task_status_new
        """
    )
    op.execute(
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'completed'"
    )
    op.execute("ALTER TYPE video_task_status RENAME TO video_task_status_old")
    op.execute("ALTER TYPE video_task_status_new RENAME TO video_task_status")
    op.execute("DROP TYPE video_task_status_old")
