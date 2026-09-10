"""baseline: projects + minimal context_entries

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-10

Minimal walking-skeleton schema (task T00). T01 owns the real context schema and
will add follow-up revisions (headline/detail rules, priority, audit-log
revisions, per-section tables, expiry).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_projects_name", "projects", ["name"], unique=True)

    op.create_table(
        "context_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("section", sa.String(length=32), nullable=False),
        sa.Column("headline", sa.String(length=120), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("author", sa.String(length=120), nullable=False, server_default="agent"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_context_entries_project_id", "context_entries", ["project_id"])
    op.create_index("ix_context_entries_section", "context_entries", ["section"])


def downgrade() -> None:
    op.drop_index("ix_context_entries_section", table_name="context_entries")
    op.drop_index("ix_context_entries_project_id", table_name="context_entries")
    op.drop_table("context_entries")
    op.drop_index("ix_projects_name", table_name="projects")
    op.drop_table("projects")
