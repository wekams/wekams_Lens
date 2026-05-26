"""audit_events table

Append-only log of security-relevant actions. Empty in Community builds
(no subscriber writes to it). Pro / Enterprise builds populate it via
the ee.audit module.

Revision ID: a8e431d6f205
Revises: f37c2d9e1a4b
Create Date: 2026-05-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8e431d6f205"
down_revision: Union[str, Sequence[str], None] = "f37c2d9e1a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            index=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        # Actor email / user-id once multi-user lands; currently null in
        # single-user mode. Free-text so it can be filled later without a
        # schema change.
        sa.Column("actor", sa.String(255), nullable=True),
        # Free-form JSON payload — kept as text for portability and because
        # the catalog DB may be SQLite in dev.
        sa.Column("payload_json", sa.Text, nullable=False, default="{}"),
        # Outcome at a glance — "ok", "denied", "error", etc.
        sa.Column("outcome", sa.String(32), nullable=False, default="ok"),
        # Optional pointers for filtering.
        sa.Column("source_name", sa.String(255), nullable=True, index=True),
        sa.Column("license_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_audit_type_time",
        "audit_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_type_time", table_name="audit_events")
    op.drop_table("audit_events")
