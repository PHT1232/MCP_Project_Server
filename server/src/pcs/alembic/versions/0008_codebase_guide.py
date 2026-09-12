"""T15: durable path-keyed Codebase Guide notes (INV-GUIDE-3, INV-GUIDE-7).

Revision ID: 0008_codebase_guide
Revises: 0007_requirement_evidence
Create Date: 2026-09-12

``code_index.file_notes`` is keyed by ``(project_id, path)``, never ``files.id``,
so a full reindex that rebuilds index file rows cannot discard agent prose.
Downgrade drops only this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_codebase_guide"
down_revision: str | None = "0007_requirement_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_notes",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "path"),
        schema="code_index",
    )
    op.create_index(
        "ix_code_index_file_notes_project_id",
        "file_notes",
        ["project_id"],
        schema="code_index",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_code_index_file_notes_project_id",
        table_name="file_notes",
        schema="code_index",
    )
    op.drop_table("file_notes", schema="code_index")
