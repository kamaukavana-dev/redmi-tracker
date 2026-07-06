"""alert spam fix: health_alert_states + notification_log

Adds per-alert-type cooldown/edge state and the Telegram deduplication log
introduced by the alert-spam post-mortem.

Revision ID: b2c9a1f4e7d8
Revises: 114f0df6a8da
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c9a1f4e7d8"
down_revision: Union[str, None] = "114f0df6a8da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_alert_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(length=40), nullable=False),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("health_alert_states", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_health_alert_states_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_health_alert_states_alert_type"), ["alert_type"], unique=True
        )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notification_log_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_notification_log_message_hash"), ["message_hash"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_notification_log_sent_at"), ["sent_at"], unique=False)
        batch_op.create_index(
            "ix_notification_log_hash_sent_at", ["message_hash", sa.text("sent_at DESC")], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_log", schema=None) as batch_op:
        batch_op.drop_index("ix_notification_log_hash_sent_at")
        batch_op.drop_index(batch_op.f("ix_notification_log_sent_at"))
        batch_op.drop_index(batch_op.f("ix_notification_log_message_hash"))
        batch_op.drop_index(batch_op.f("ix_notification_log_id"))
    op.drop_table("notification_log")

    with op.batch_alter_table("health_alert_states", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_health_alert_states_alert_type"))
        batch_op.drop_index(batch_op.f("ix_health_alert_states_id"))
    op.drop_table("health_alert_states")
