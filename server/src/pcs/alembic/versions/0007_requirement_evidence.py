"""T12: compact evidence ledger and review violations.

Revision ID: 0007_requirement_evidence
Revises: 0006_requirement_contracts
Create Date: 2026-09-11

Append-only evidence bound to a contract revision, plus resolvable violations.
Composite FKs keep requirement, criterion, and revision ownership aligned.
Does not alter existing requirement or contract *data*. Evidence never infers
requirement status (D4).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_requirement_evidence"
down_revision: str | None = "0006_requirement_contracts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_acceptance_criteria_id_project",
        "acceptance_criteria",
        ["id", "project_id"],
    )
    op.create_unique_constraint(
        "uq_requirement_invariants_id_requirement",
        "requirement_invariants",
        ["id", "requirement_id"],
    )
    op.create_unique_constraint(
        "uq_requirement_contract_revisions_id_requirement",
        "requirement_contract_revisions",
        ["id", "requirement_id"],
    )
    op.create_unique_constraint(
        "uq_requirement_contract_revisions_id_entity",
        "requirement_contract_revisions",
        ["id", "entity_id"],
    )

    op.create_table(
        "requirement_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column(
            "requirement_section",
            sa.String(length=32),
            nullable=False,
            server_default="requirements",
        ),
        sa.Column("criterion_id", sa.String(length=36), nullable=False),
        sa.Column("contract_revision_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_kind", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("command_ref", sa.String(length=200), nullable=True),
        sa.Column("test_ref", sa.String(length=200), nullable=True),
        sa.Column("file_ref", sa.String(length=240), nullable=True),
        sa.Column("source_commit", sa.String(length=64), nullable=False),
        sa.Column("worktree_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("artifact_ref", sa.String(length=500), nullable=True),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_requirement_project",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_requirement_section",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id", "project_id"],
            ["acceptance_criteria.id", "acceptance_criteria.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_criterion_project",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id", "requirement_id"],
            [
                "requirement_contract_revisions.id",
                "requirement_contract_revisions.requirement_id",
            ],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_revision_requirement",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id", "criterion_id"],
            ["requirement_contract_revisions.id", "requirement_contract_revisions.entity_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_revision_criterion",
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('test', 'command', 'review', 'manual', 'file')",
            name="ck_requirement_evidence_kind",
        ),
        sa.CheckConstraint(
            "result IN ('passed', 'failed', 'manual-pending')",
            name="ck_requirement_evidence_result",
        ),
        sa.CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_evidence_section",
        ),
        sa.CheckConstraint(
            "char_length(source_commit) = 40",
            name="ck_requirement_evidence_commit_len",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_requirement_evidence_id_project"),
    )
    op.create_index("ix_requirement_evidence_project_id", "requirement_evidence", ["project_id"])
    op.create_index(
        "ix_requirement_evidence_criterion_created",
        "requirement_evidence",
        ["criterion_id", "seq"],
    )
    op.create_index(
        "ix_requirement_evidence_requirement_id",
        "requirement_evidence",
        ["requirement_id"],
    )

    op.create_table(
        "requirement_violations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column(
            "requirement_section",
            sa.String(length=32),
            nullable=False,
            server_default="requirements",
        ),
        sa.Column("invariant_id", sa.String(length=36), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=False),
        sa.Column("file_ref", sa.String(length=240), nullable=True),
        sa.Column("line_no", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("author", sa.String(length=120), nullable=False),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_requirement_project",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_requirement_section",
        ),
        sa.ForeignKeyConstraint(
            ["invariant_id", "project_id"],
            ["requirement_invariants.id", "requirement_invariants.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_invariant_project",
        ),
        sa.ForeignKeyConstraint(
            ["invariant_id", "requirement_id"],
            ["requirement_invariants.id", "requirement_invariants.requirement_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_invariant_requirement",
        ),
        sa.CheckConstraint(
            "severity IN ('blocking', 'warning')",
            name="ck_requirement_violations_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_requirement_violations_status",
        ),
        sa.CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_violations_section",
        ),
        sa.CheckConstraint(
            "char_length(summary) BETWEEN 1 AND 200",
            name="ck_requirement_violations_summary_len",
        ),
        sa.CheckConstraint(
            "line_no IS NULL OR line_no >= 1",
            name="ck_requirement_violations_line_no",
        ),
        sa.UniqueConstraint("id", "project_id", name="uq_requirement_violations_id_project"),
    )
    op.create_index(
        "ix_requirement_violations_project_id", "requirement_violations", ["project_id"]
    )
    op.create_index(
        "ix_requirement_violations_invariant_id", "requirement_violations", ["invariant_id"]
    )
    op.create_index(
        "ix_requirement_violations_requirement_id",
        "requirement_violations",
        ["requirement_id"],
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION pcs_reject_evidence_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION
                'requirement evidence is append-only; mutation rejected';
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_requirement_evidence_immutable
            BEFORE UPDATE OR DELETE ON requirement_evidence
            FOR EACH ROW
            EXECUTE FUNCTION pcs_reject_evidence_mutation()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DROP TRIGGER IF EXISTS trg_requirement_evidence_immutable ON requirement_evidence")
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS pcs_reject_evidence_mutation()"))
    op.drop_index("ix_requirement_violations_requirement_id", table_name="requirement_violations")
    op.drop_index("ix_requirement_violations_invariant_id", table_name="requirement_violations")
    op.drop_index("ix_requirement_violations_project_id", table_name="requirement_violations")
    op.drop_table("requirement_violations")
    op.drop_index("ix_requirement_evidence_requirement_id", table_name="requirement_evidence")
    op.drop_index("ix_requirement_evidence_criterion_created", table_name="requirement_evidence")
    op.drop_index("ix_requirement_evidence_project_id", table_name="requirement_evidence")
    op.drop_table("requirement_evidence")
    op.drop_constraint(
        "uq_requirement_contract_revisions_id_entity",
        "requirement_contract_revisions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_requirement_contract_revisions_id_requirement",
        "requirement_contract_revisions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_requirement_invariants_id_requirement",
        "requirement_invariants",
        type_="unique",
    )
    op.drop_constraint("uq_acceptance_criteria_id_project", "acceptance_criteria", type_="unique")
