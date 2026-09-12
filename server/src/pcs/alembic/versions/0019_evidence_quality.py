"""T19: evidence provenance, effective lifecycle inputs, and review scope.

Revision ID: 0019_evidence_quality
Revises: 0007_requirement_evidence
Create Date: 2026-09-12

The 0019 identifier avoids T15's reserved 0008. Integration must rebase the
parent onto the eventual post-T15-T18 migration head when one exists.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_evidence_quality"
down_revision: str | None = "0007_requirement_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add conservative provenance fields; legacy rows remain provisional."""
    op.add_column(
        "requirement_evidence",
        sa.Column("recording_state", sa.String(24), nullable=False, server_default="provisional"),
    )
    op.add_column("requirement_evidence", sa.Column("claim_ref", sa.String(160), nullable=True))
    op.add_column("requirement_evidence", sa.Column("review_ref", sa.String(80), nullable=True))
    op.add_column(
        "requirement_evidence",
        sa.Column(
            "source_commit_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "requirement_evidence", sa.Column("file_ref_verified", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "requirement_evidence", sa.Column("test_ref_verified", sa.Boolean(), nullable=True)
    )
    op.create_check_constraint(
        "ck_requirement_evidence_recording_state",
        "requirement_evidence",
        "recording_state IN ('provisional', 'verified-at-commit')",
    )
    op.create_check_constraint(
        "ck_requirement_evidence_claim_ref_len",
        "requirement_evidence",
        "claim_ref IS NULL OR char_length(claim_ref) BETWEEN 1 AND 160",
    )
    op.create_check_constraint(
        "ck_requirement_evidence_review_ref",
        "requirement_evidence",
        (
            "review_ref IS NULL OR review_ref ~ '^(criterion|invariant):[0-9a-f]{8}-"
            "[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
        ),
    )


def downgrade() -> None:
    """Remove T19 evidence-quality columns and constraints."""
    op.drop_constraint("ck_requirement_evidence_review_ref", "requirement_evidence", type_="check")
    op.drop_constraint(
        "ck_requirement_evidence_claim_ref_len", "requirement_evidence", type_="check"
    )
    op.drop_constraint(
        "ck_requirement_evidence_recording_state", "requirement_evidence", type_="check"
    )
    for column in (
        "test_ref_verified",
        "file_ref_verified",
        "source_commit_verified",
        "review_ref",
        "claim_ref",
        "recording_state",
    ):
        op.drop_column("requirement_evidence", column)
