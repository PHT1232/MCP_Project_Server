"""Token savings log: actual vs. baseline token counts per retrieval call.

Revision ID: 0025_token_savings_log
Revises: 0024_merge_t20_t23

Creates token_savings_log, an append-only table recording, for each call to
retrieve_context, search_code, prepare_task, or get_project_briefing, the
tokens actually returned and a baseline of what returning the full
untruncated content would have cost.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_token_savings_log"
down_revision: str | None = "0024_merge_t20_t23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_savings_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("caller", sa.String(120), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=False),
        sa.Column("baseline_tokens", sa.Integer(), nullable=False),
        sa.Column("saved_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "operation IN ('retrieve_context', 'search_code', 'prepare_task', "
            "'get_project_briefing')",
            name="ck_token_savings_log_operation",
        ),
        sa.CheckConstraint("actual_tokens >= 0", name="ck_token_savings_log_actual_nonneg"),
        sa.CheckConstraint("baseline_tokens >= 0", name="ck_token_savings_log_baseline_nonneg"),
        sa.CheckConstraint("saved_tokens >= 0", name="ck_token_savings_log_saved_nonneg"),
    )
    op.create_index(
        "ix_token_savings_log_project_created",
        "token_savings_log",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_token_savings_log_project_operation",
        "token_savings_log",
        ["project_id", "operation"],
    )


def downgrade() -> None:
    op.drop_index("ix_token_savings_log_project_operation", table_name="token_savings_log")
    op.drop_index("ix_token_savings_log_project_created", table_name="token_savings_log")
    op.drop_table("token_savings_log")
