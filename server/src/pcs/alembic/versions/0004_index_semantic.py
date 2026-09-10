"""T04: symbols + semantic retrieval — SCIP-style symbol model + pgvector cache.

Revision ID: 0004_index_semantic
Revises: 0003_code_index
Create Date: 2026-09-10

Adds, all inside schema ``code_index`` so AC15's drop-and-rebuild still holds:
- ``symbols`` / ``symbol_refs`` / ``symbol_edges`` — one normalised SCIP-style
  model for every language, whether produced by a real SCIP indexer or the
  tree-sitter ``tags`` fallback (FR23b, FR23c, D14).
- ``embeddings`` — content-hash-keyed pgvector cache so unchanged chunks are
  never re-embedded (FR28, NFR10). No embedding backend is bundled (D7).
- ``chunks.chunk_hash`` and status bookkeeping columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_index_semantic"
down_revision: str | None = "0003_code_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.add_column(
        "chunks",
        sa.Column("chunk_hash", sa.String(length=64), nullable=True),
        schema="code_index",
    )
    op.create_index(
        "ix_code_index_chunks_chunk_hash", "chunks", ["chunk_hash"], schema="code_index"
    )

    op.add_column(
        "status",
        sa.Column(
            "symbol_modes",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        schema="code_index",
    )
    op.add_column(
        "status",
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        schema="code_index",
    )
    op.add_column(
        "status",
        sa.Column("semantic_model", sa.String(length=128), nullable=True),
        schema="code_index",
    )
    op.add_column(
        "status",
        sa.Column("embedded_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        schema="code_index",
    )

    op.create_table(
        "symbols",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("scip_symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="symbol"),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="fallback"),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["code_index.files.id"], ondelete="CASCADE"),
        schema="code_index",
    )
    op.create_index(
        "ix_code_index_symbols_project_id", "symbols", ["project_id"], schema="code_index"
    )
    op.create_index("ix_code_index_symbols_file_id", "symbols", ["file_id"], schema="code_index")
    op.create_index("ix_code_index_symbols_scip", "symbols", ["scip_symbol"], schema="code_index")

    op.create_table(
        "symbol_refs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("file_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("scip_symbol", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("is_definition", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="fallback"),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["code_index.files.id"], ondelete="CASCADE"),
        schema="code_index",
    )
    op.create_index(
        "ix_code_index_symbol_refs_project_id", "symbol_refs", ["project_id"], schema="code_index"
    )
    op.create_index(
        "ix_code_index_symbol_refs_file_id", "symbol_refs", ["file_id"], schema="code_index"
    )
    op.create_index(
        "ix_code_index_symbol_refs_scip", "symbol_refs", ["scip_symbol"], schema="code_index"
    )

    op.create_table(
        "symbol_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("src_path", sa.Text(), nullable=False),
        sa.Column("dst_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("dst_module", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="import"),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="fallback"),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id",
            "src_path",
            "dst_path",
            "dst_module",
            "kind",
            name="uq_code_index_symbol_edges",
        ),
        schema="code_index",
    )
    op.create_index(
        "ix_code_index_symbol_edges_project_id", "symbol_edges", ["project_id"], schema="code_index"
    )

    op.create_table(
        "embeddings",
        sa.Column("chunk_hash", sa.String(length=64), primary_key=True),
        sa.Column("model", sa.String(length=128), primary_key=True),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="code_index",
    )
    op.execute(sa.text("ALTER TABLE code_index.embeddings ADD COLUMN embedding vector"))


def downgrade() -> None:
    op.drop_table("embeddings", schema="code_index")
    op.drop_table("symbol_edges", schema="code_index")
    op.drop_table("symbol_refs", schema="code_index")
    op.drop_table("symbols", schema="code_index")
    op.drop_column("status", "embedded_chunk_count", schema="code_index")
    op.drop_column("status", "semantic_model", schema="code_index")
    op.drop_column("status", "symbol_count", schema="code_index")
    op.drop_column("status", "symbol_modes", schema="code_index")
    op.drop_index("ix_code_index_chunks_chunk_hash", "chunks", schema="code_index")
    op.drop_column("chunks", "chunk_hash", schema="code_index")
