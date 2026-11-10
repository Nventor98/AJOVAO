"""Add dispatch leases and retry scheduling to outbox events.

Revision ID: 20261109050000
Revises: 7494726cd613
"""

from alembic import op
import sqlalchemy as sa


revision = "20261109050000"
down_revision = "7494726cd613"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("event_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("lock_token", sa.String(length=36), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE outbox_events "
            "SET event_id = id, next_attempt_at = created_at "
            "WHERE event_id IS NULL OR next_attempt_at IS NULL"
        )
    )
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.alter_column(
            "event_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.alter_column(
            "next_attempt_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index("ux_outbox_events_event_id", "outbox_events", ["event_id"], unique=True)
    op.create_index(
        "ix_outbox_events_dispatch",
        "outbox_events",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_outbox_events_next_attempt_at",
        "outbox_events",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_next_attempt_at", table_name="outbox_events")
    op.drop_index("ix_outbox_events_dispatch", table_name="outbox_events")
    op.drop_index("ux_outbox_events_event_id", table_name="outbox_events")
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.drop_column("lock_token")
        batch_op.drop_column("locked_until")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("event_id")
