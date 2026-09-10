"""T01: real context-store schema + immutable audit log.

Revision ID: 0002_context_store
Revises: 0001_baseline
Create Date: 2026-09-10

Adds per-project budgets/expiry (FR3a, FR9g), entry metadata (priority,
requirement status, links — FR3, FR2), widens headline to Text so the
per-project cap can exceed the D13 default, and the ``context_entry_revisions``
audit table (FR11, D5). Existing T00 rows keep their data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_context_store"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("expiry_policy", sa.String(length=16), nullable=False, server_default="off"),
    )
    op.add_column("projects", sa.Column("expiry_days", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("briefing_token_budget", sa.Integer(), nullable=False, server_default="1500"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "prepare_task_token_budget",
            sa.Integer(),
            nullable=False,
            server_default="4000",
        ),
    )
    op.add_column(
        "projects",
        sa.Column("headline_max_chars", sa.Integer(), nullable=False, server_default="120"),
    )
    op.add_column(
        "projects",
        sa.Column("detail_max_chars", sa.Integer(), nullable=False, server_default="8000"),
    )
    op.create_check_constraint(
        "ck_projects_briefing_budget",
        "projects",
        "briefing_token_budget >= 500 AND briefing_token_budget <= 4000",
    )
    op.create_check_constraint(
        "ck_projects_prepare_task_budget",
        "projects",
        "prepare_task_token_budget >= 1000 AND prepare_task_token_budget <= 16000",
    )
    op.create_check_constraint(
        "ck_projects_expiry_policy",
        "projects",
        "expiry_policy IN ('off', 'age')",
    )

    op.alter_column(
        "context_entries",
        "headline",
        existing_type=sa.String(length=120),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.add_column(
        "context_entries",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "context_entries",
        sa.Column("requirement_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "context_entries",
        sa.Column(
            "linked_files",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "context_entries",
        sa.Column("related_entry_id", sa.String(length=36), nullable=True),
    )
    op.create_check_constraint(
        "ck_context_entries_status",
        "context_entries",
        "status IN ('open', 'resolved', 'deleted')",
    )

    op.create_table(
        "context_entry_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entry_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("requirement_status", sa.String(length=16), nullable=True),
        sa.Column(
            "linked_files",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("related_entry_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["context_entries.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_context_entry_revisions_entry_id",
        "context_entry_revisions",
        ["entry_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_entry_revisions_entry_id", table_name="context_entry_revisions")
    op.drop_table("context_entry_revisions")
    op.drop_constraint("ck_context_entries_status", "context_entries", type_="check")
    op.drop_column("context_entries", "related_entry_id")
    op.drop_column("context_entries", "linked_files")
    op.drop_column("context_entries", "requirement_status")
    op.drop_column("context_entries", "priority")
    op.alter_column(
        "context_entries",
        "headline",
        existing_type=sa.Text(),
        type_=sa.String(length=120),
        existing_nullable=False,
    )
    op.drop_constraint("ck_projects_expiry_policy", "projects", type_="check")
    op.drop_constraint("ck_projects_prepare_task_budget", "projects", type_="check")
    op.drop_constraint("ck_projects_briefing_budget", "projects", type_="check")
    op.drop_column("projects", "detail_max_chars")
    op.drop_column("projects", "headline_max_chars")
    op.drop_column("projects", "prepare_task_token_budget")
    op.drop_column("projects", "briefing_token_budget")
    op.drop_column("projects", "expiry_days")
    op.drop_column("projects", "expiry_policy")
