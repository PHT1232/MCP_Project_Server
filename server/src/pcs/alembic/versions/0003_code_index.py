"""T03: code index schema (pg_trgm, FTS, trigram) — drop-and-rebuild safe (NFR12, AC15).

Revision ID: 0003_code_index
Revises: 0002_context_store
Create Date: 2026-09-10

Index tables live in schema ``code_index`` so dropping them cannot touch
curated context. Each chunk records path, line range, language, and the git
blob/commit it came from (FR21, FR25).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_code_index"
down_revision: str | None = "0002_context_store"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS code_index"))

    op.create_table(
        "files",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("git_blob", sa.String(length=64), nullable=True),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "path", name="uq_code_index_files_project_path"),
        schema="code_index",
    )
    op.create_index("ix_code_index_files_project_id", "files", ["project_id"], schema="code_index")

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("git_blob", sa.String(length=64), nullable=True),
        sa.Column("git_commit", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["code_index.files.id"], ondelete="CASCADE"),
        schema="code_index",
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE code_index.chunks
            ADD COLUMN tsv tsvector
            GENERATED ALWAYS AS (
                to_tsvector('simple', coalesce(symbol, '') || ' ' || content)
            ) STORED
            """
        )
    )
    op.create_index(
        "ix_code_index_chunks_project_id", "chunks", ["project_id"], schema="code_index"
    )
    op.create_index("ix_code_index_chunks_file_id", "chunks", ["file_id"], schema="code_index")
    op.execute(
        sa.text("CREATE INDEX ix_code_index_chunks_tsv ON code_index.chunks USING GIN (tsv)")
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_code_index_chunks_content_trgm "
            "ON code_index.chunks USING GIN (content gin_trgm_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_code_index_chunks_symbol_trgm "
            "ON code_index.chunks USING GIN (symbol gin_trgm_ops)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_code_index_chunks_path_trgm "
            "ON code_index.chunks USING GIN (path gin_trgm_ops)"
        )
    )

    op.create_table(
        "status",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("last_full_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_incremental_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_commit", sa.String(length=64), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="idle"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        schema="code_index",
    )


def downgrade() -> None:
    op.execute(sa.text("DROP SCHEMA IF EXISTS code_index CASCADE"))
