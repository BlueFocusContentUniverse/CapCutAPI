"""align enums and add worker status tables

Revision ID: 0013
Revises: 0012
Create Date: 2025-12-22 00:00:00

"""

import logging

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Update enum to match SQLAlchemy model values (lowercase) and include pending
    logger.info("Updating video_task_status enum to lowercase values")
    new_enum = sa.Enum(
        "initialized",
        "pending",
        "processing",
        "completed",
        "failed",
        name="video_task_status_new",
    )
    new_enum.create(bind, checkfirst=True)

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
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'initialized'"
    )
    op.execute("ALTER TYPE video_task_status RENAME TO video_task_status_old")
    op.execute("ALTER TYPE video_task_status_new RENAME TO video_task_status")
    op.execute("DROP TYPE video_task_status_old")

    logger.info("Creating worker_statuses table")
    op.create_table(
        "worker_statuses",
        sa.Column("worker_name", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_reason", sa.Text(), nullable=True),
        sa.Column("last_failure_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("worker_name"),
    )
    op.create_index(
        op.f("ix_worker_statuses_is_available"),
        "worker_statuses",
        ["is_available"],
        unique=False,
    )

    logger.info("Creating worker_failure_logs table")
    op.create_table(
        "worker_failure_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_name", sa.String(length=255), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_worker_failure_logs_worker_name"),
        "worker_failure_logs",
        ["worker_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_worker_failure_logs_task_id"),
        "worker_failure_logs",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    logger.info("Dropping worker_failure_logs table")
    op.drop_index(
        op.f("ix_worker_failure_logs_task_id"), table_name="worker_failure_logs"
    )
    op.drop_index(
        op.f("ix_worker_failure_logs_worker_name"), table_name="worker_failure_logs"
    )
    op.drop_table("worker_failure_logs")

    logger.info("Dropping worker_statuses table")
    op.drop_index(op.f("ix_worker_statuses_is_available"), table_name="worker_statuses")
    op.drop_table("worker_statuses")

    logger.info("Reverting video_task_status enum to uppercase values")
    op.execute("ALTER TABLE video_tasks ALTER COLUMN render_status DROP DEFAULT")
    op.execute(
        "CREATE TYPE video_task_status_old AS ENUM ('INITIALIZED','PENDING','PROCESSING','COMPLETED','FAILED')"
    )
    op.execute(
        """
        ALTER TABLE video_tasks
        ALTER COLUMN render_status
        TYPE video_task_status_old
        USING upper(render_status::text)::video_task_status_old
        """
    )
    op.execute(
        "ALTER TABLE video_tasks ALTER COLUMN render_status SET DEFAULT 'COMPLETED'"
    )
    op.execute("DROP TYPE video_task_status")
    op.execute("ALTER TYPE video_task_status_old RENAME TO video_task_status")
