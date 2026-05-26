"""licenses table

Single-row table holding the currently-activated Pro / Enterprise license.
Lives in the public Community schema because Community can run without
a license — the table just stays empty. Pro / Enterprise builds populate
and read from it via the ee.license module.

Revision ID: f37c2d9e1a4b
Revises: 5201c04abb5d
Create Date: 2026-05-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f37c2d9e1a4b"
down_revision: Union[str, Sequence[str], None] = "5201c04abb5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "licenses",
        # Synthetic primary key. There is at most one ACTIVE license at any time;
        # we still use a PK so historical rows can be retained when superseded.
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("license_id", sa.String(64), nullable=False, unique=True),
        sa.Column("customer", sa.String(255), nullable=False),
        sa.Column("customer_email", sa.String(320), nullable=False),
        sa.Column("edition", sa.String(64), nullable=False),
        sa.Column("seats", sa.Integer, nullable=False, default=0),
        sa.Column("workspaces", sa.Integer, nullable=False, default=0),
        sa.Column("features_json", sa.String, nullable=False, default="[]"),
        sa.Column("issued_at", sa.String(64), nullable=False),
        sa.Column("not_before", sa.String(64), nullable=False),
        sa.Column("not_after", sa.String(64), nullable=False),
        sa.Column("signed_token", sa.String, nullable=False),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
    )
    op.create_index(
        "ix_licenses_active",
        "licenses",
        ["is_active"],
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("ix_licenses_active", table_name="licenses")
    op.drop_table("licenses")
