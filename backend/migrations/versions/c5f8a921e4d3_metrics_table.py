"""metrics table

Stores the customer's business-metric definitions (Pro tier semantic
layer). Empty in Community installs — only ee.semantic writes rows.

Revision ID: c5f8a921e4d3
Revises: a8e431d6f205
Create Date: 2026-05-26
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f8a921e4d3"
down_revision: Union[str, Sequence[str], None] = "a8e431d6f205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, default=""),
        # SQL expression / template the LLM composes into a final query.
        # Stored as text; validated at registration time on the Pro path.
        sa.Column("sql_template", sa.Text, nullable=False),
        # Optional source binding. NULL means "applies anywhere" but most
        # metrics will name a single source so the LLM uses the right syntax.
        sa.Column("source_name", sa.String(255), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("metrics")
