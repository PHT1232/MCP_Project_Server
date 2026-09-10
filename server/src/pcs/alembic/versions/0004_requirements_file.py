"""T02: requirements template file sync (FR16a, D12, D15).

Revision ID: 0004_requirements_file
Revises: 0003_code_index
Create Date: 2026-09-10

Adds the server-assigned ``R-NNN`` key to ``context_entries`` (nullable — the
UUID id is not overloaded), a fourth lifecycle status ``archived`` for
requirements whose block was removed from the file (history kept, never
resurrected — AC22), and the per-project ``requirements_sync_state`` snapshot the
3-way merge diffs against.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_requirements_file"
down_revision: str | None = "0003_code_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "context_entries",
        sa.Column("req_key", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "uq_context_entries_project_req_key",
        "context_entries",
        ["project_id", "req_key"],
        unique=True,
        postgresql_where=sa.text("req_key IS NOT NULL"),
    )
    op.drop_constraint("ck_context_entries_status", "context_entries", type_="check")
    op.create_check_constraint(
        "ck_context_entries_status",
        "context_entries",
        "status IN ('open', 'resolved', 'deleted', 'archived')",
    )

    op.create_table(
        "requirements_sync_state",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("next_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "snapshot",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("requirements_sync_state")
    op.drop_constraint("ck_context_entries_status", "context_entries", type_="check")
    op.create_check_constraint(
        "ck_context_entries_status",
        "context_entries",
        "status IN ('open', 'resolved', 'deleted')",
    )
    op.drop_index("uq_context_entries_project_req_key", table_name="context_entries")
    op.drop_column("context_entries", "req_key")
