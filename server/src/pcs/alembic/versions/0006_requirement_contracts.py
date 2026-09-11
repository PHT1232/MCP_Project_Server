"""T10: requirement contract model — invariants, criteria, immutable history.

Revision ID: 0006_requirement_contracts
Revises: 0005_index_semantic
Create Date: 2026-09-11

Adds store-owned contract tables without altering ``projects`` or
``context_entries`` (existing requirement rows keep their data). Contract
records are not synced into ``.project-context/requirements.md``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0006_requirement_contracts"
down_revision: str | None = "0005_index_semantic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requirement_invariants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["requirement_id"], ["context_entries.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('behavior', 'architecture', 'data-boundary', "
            "'forbidden-path', 'integration', 'manual')",
            name="ck_requirement_invariants_kind",
        ),
        sa.CheckConstraint(
            "risk IN ('low', 'medium', 'high')",
            name="ck_requirement_invariants_risk",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'deleted')",
            name="ck_requirement_invariants_status",
        ),
    )
    op.create_index(
        "uq_requirement_invariants_requirement_key",
        "requirement_invariants",
        ["requirement_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_requirement_invariants_project_id",
        "requirement_invariants",
        ["project_id"],
    )
    op.create_index(
        "ix_requirement_invariants_requirement_id",
        "requirement_invariants",
        ["requirement_id"],
    )

    op.create_table(
        "acceptance_criteria",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("invariant_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "independent_review",
            sa.String(length=16),
            nullable=False,
            server_default="not-required",
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(
            ["invariant_id"], ["requirement_invariants.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('test', 'command', 'review', 'manual', 'file')",
            name="ck_acceptance_criteria_evidence_kind",
        ),
        sa.CheckConstraint(
            "independent_review IN ('not-required', 'required')",
            name="ck_acceptance_criteria_independent_review",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'deleted')",
            name="ck_acceptance_criteria_status",
        ),
    )
    op.create_index(
        "uq_acceptance_criteria_invariant_key",
        "acceptance_criteria",
        ["invariant_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_acceptance_criteria_project_id",
        "acceptance_criteria",
        ["project_id"],
    )
    op.create_index(
        "ix_acceptance_criteria_invariant_id",
        "acceptance_criteria",
        ["invariant_id"],
    )

    op.create_table(
        "requirement_contract_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("entity_kind", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "snapshot",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["context_entries.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "entity_kind IN ('invariant', 'criterion')",
            name="ck_requirement_contract_revisions_entity_kind",
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'delete')",
            name="ck_requirement_contract_revisions_action",
        ),
    )
    op.create_index(
        "ix_requirement_contract_revisions_requirement_created",
        "requirement_contract_revisions",
        ["requirement_id", "created_at"],
    )
    op.create_index(
        "ix_requirement_contract_revisions_project_id",
        "requirement_contract_revisions",
        ["project_id"],
    )
    op.create_index(
        "ix_requirement_contract_revisions_entity_id",
        "requirement_contract_revisions",
        ["entity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_requirement_contract_revisions_entity_id",
        table_name="requirement_contract_revisions",
    )
    op.drop_index(
        "ix_requirement_contract_revisions_project_id",
        table_name="requirement_contract_revisions",
    )
    op.drop_index(
        "ix_requirement_contract_revisions_requirement_created",
        table_name="requirement_contract_revisions",
    )
    op.drop_table("requirement_contract_revisions")
    op.drop_index("ix_acceptance_criteria_invariant_id", table_name="acceptance_criteria")
    op.drop_index("ix_acceptance_criteria_project_id", table_name="acceptance_criteria")
    op.drop_index("uq_acceptance_criteria_invariant_key", table_name="acceptance_criteria")
    op.drop_table("acceptance_criteria")
    op.drop_index("ix_requirement_invariants_requirement_id", table_name="requirement_invariants")
    op.drop_index("ix_requirement_invariants_project_id", table_name="requirement_invariants")
    op.drop_index("uq_requirement_invariants_requirement_key", table_name="requirement_invariants")
    op.drop_table("requirement_invariants")
