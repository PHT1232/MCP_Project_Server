"""T20: encrypted global AI provider settings and index compatibility state.

Revision ID: 0020_ai_provider_settings
Revises: 0019_evidence_quality
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_ai_provider_settings"
down_revision: str | None = "0019_evidence_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("embedding_backend", sa.String(32), nullable=False),
        sa.Column("embedding_base_url", sa.String(2048), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_batch_size", sa.Integer(), nullable=False),
        sa.Column("embedding_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("embedding_api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("summary_backend", sa.String(32), nullable=False),
        sa.Column("summary_base_url", sa.String(2048), nullable=False),
        sa.Column("summary_model", sa.String(200), nullable=False),
        sa.Column("summary_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("summary_api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("reindex_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_ai_provider_settings_singleton"),
        sa.CheckConstraint(
            "length(embedding_backend) BETWEEN 0 AND 32 "
            "AND length(embedding_base_url) BETWEEN 1 AND 2048 "
            "AND length(embedding_model) BETWEEN 1 AND 200 "
            "AND length(summary_backend) BETWEEN 0 AND 32 "
            "AND length(summary_base_url) BETWEEN 1 AND 2048 "
            "AND length(summary_model) BETWEEN 1 AND 200",
            name="ck_ai_provider_settings_text_lengths",
        ),
        sa.CheckConstraint(
            "embedding_api_key_encrypted IS NULL "
            "OR octet_length(embedding_api_key_encrypted) <= 12000",
            name="ck_ai_provider_settings_embedding_secret_size",
        ),
        sa.CheckConstraint(
            "summary_api_key_encrypted IS NULL OR octet_length(summary_api_key_encrypted) <= 12000",
            name="ck_ai_provider_settings_summary_secret_size",
        ),
        sa.CheckConstraint(
            "embedding_dimensions BETWEEN 1 AND 65536 "
            "AND embedding_batch_size BETWEEN 1 AND 2048 "
            "AND embedding_timeout_seconds > 0 AND embedding_timeout_seconds <= 300",
            name="ck_ai_provider_settings_embedding_positive",
        ),
        sa.CheckConstraint(
            "summary_timeout_seconds > 0 AND summary_timeout_seconds <= 300",
            name="ck_ai_provider_settings_summary_positive",
        ),
    )
    op.add_column(
        "status", sa.Column("semantic_provider", sa.String(32), nullable=True), schema="code_index"
    )
    op.add_column(
        "status", sa.Column("semantic_dimensions", sa.Integer(), nullable=True), schema="code_index"
    )
    op.add_column(
        "status", sa.Column("semantic_base_url", sa.Text(), nullable=True), schema="code_index"
    )
    op.add_column(
        "status",
        sa.Column("reindex_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="code_index",
    )


def downgrade() -> None:
    # The index schema can self-heal independently of Alembic (AC15), so a
    # downgrade must tolerate compatibility columns already being absent.
    op.execute("ALTER TABLE code_index.status DROP COLUMN IF EXISTS reindex_required")
    op.execute("ALTER TABLE code_index.status DROP COLUMN IF EXISTS semantic_base_url")
    op.execute("ALTER TABLE code_index.status DROP COLUMN IF EXISTS semantic_dimensions")
    op.execute("ALTER TABLE code_index.status DROP COLUMN IF EXISTS semantic_provider")
    op.execute("DROP TABLE IF EXISTS ai_provider_settings")
