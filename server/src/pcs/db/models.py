"""ORM models for the curated context store (FR1-FR4, FR3a, FR3b, FR9g, FR11, D5).

``projects`` holds per-project budgets and expiry policy. ``context_entries`` is
the verbatim store (never replaced by a summary). ``context_entry_revisions`` is
the immutable audit log — nothing is hard-deleted.

T10 adds ``requirement_invariants``, ``acceptance_criteria``, and append-only
``requirement_contract_revisions``. T12 adds append-only ``requirement_evidence``
and ``requirement_violations``. Contract and evidence rows are store-owned and
are not written to ``.project-context/requirements.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pcs.db.base import Base
from pcs.planning.models import (
    Plan,
    PlanTask,
    PlanTaskEvent,
    PlanTaskRequirement,
    TaskDependency,
)
from pcs.token_savings.models import TokenSavingsLogEntry

__all__ = [
    "AcceptanceCriterion",
    "Base",
    "ContextEntry",
    "ContextEntryRevision",
    "Plan",
    "PlanTask",
    "PlanTaskEvent",
    "PlanTaskRequirement",
    "Project",
    "RequirementContractRevision",
    "RequirementEvidence",
    "RequirementInvariant",
    "RequirementViolation",
    "TaskDependency",
    "TokenSavingsLogEntry",
]


def _new_id() -> str:
    return str(uuid.uuid4())


class Project(Base):
    """A registered project context, selected explicitly by name or id (D3, FR1)."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "briefing_token_budget >= 500 AND briefing_token_budget <= 4000",
            name="ck_projects_briefing_budget",
        ),
        CheckConstraint(
            "prepare_task_token_budget >= 1000 AND prepare_task_token_budget <= 16000",
            name="ck_projects_prepare_task_budget",
        ),
        CheckConstraint(
            "expiry_policy IN ('off', 'age')",
            name="ck_projects_expiry_policy",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    root_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # FR3a — configurable per-project expiry; default off.
    expiry_policy: Mapped[str] = mapped_column(String(16), default="off", server_default="off")
    expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # FR9g / D13 — per-project budgets.
    briefing_token_budget: Mapped[int] = mapped_column(Integer, default=1500, server_default="1500")
    prepare_task_token_budget: Mapped[int] = mapped_column(
        Integer, default=4000, server_default="4000"
    )
    headline_max_chars: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    detail_max_chars: Mapped[int] = mapped_column(Integer, default=8000, server_default="8000")

    entries: Mapped[list[ContextEntry]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContextEntry(Base):
    """One curated context item stored verbatim (FR3, FR3b, FR4, FR9a)."""

    __tablename__ = "context_entries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'deleted', 'archived')",
            name="ck_context_entries_status",
        ),
        # FR16a: requirement key R-NNN is unique per project when set. Requirements
        # created store-first (add_requirement) get their key on the next sync.
        Index(
            "uq_context_entries_project_req_key",
            "project_id",
            "req_key",
            unique=True,
            postgresql_where=text("req_key IS NOT NULL"),
        ),
        # T10 composite FKs: contract rows must share the parent entry's project
        # and (for invariants) the requirements section.
        UniqueConstraint("id", "project_id", name="uq_context_entries_id_project"),
        UniqueConstraint("id", "section", name="uq_context_entries_id_section"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(32), index=True)
    # FR16a — stable, server-assigned R-NNN identity for requirements; never reused.
    req_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    headline: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    author: Mapped[str] = mapped_column(String(120), default="agent")
    requirement_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    linked_files: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    related_entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="entries")
    revisions: Mapped[list[ContextEntryRevision]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContextEntryRevision(Base):
    """Immutable audit-log row for one create/update/resolve/delete (FR11, D5)."""

    __tablename__ = "context_entry_revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("context_entries.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    requirement_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    linked_files: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    related_entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entry: Mapped[ContextEntry] = relationship(back_populates="revisions")


class RequirementInvariant(Base):
    """One non-negotiable invariant on a requirement (T10). Soft-deleted, never hard-deleted."""

    __tablename__ = "requirement_invariants"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('behavior', 'architecture', 'data-boundary', "
            "'forbidden-path', 'integration', 'manual')",
            name="ck_requirement_invariants_kind",
        ),
        CheckConstraint(
            "risk IN ('low', 'medium', 'high')",
            name="ck_requirement_invariants_risk",
        ),
        CheckConstraint(
            "status IN ('open', 'deleted')",
            name="ck_requirement_invariants_status",
        ),
        CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_invariants_section",
        ),
        CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 2000",
            name="ck_requirement_invariants_statement_len",
        ),
        CheckConstraint(
            "char_length(key) BETWEEN 1 AND 64",
            name="ck_requirement_invariants_key_len",
        ),
        UniqueConstraint("id", "project_id", name="uq_requirement_invariants_id_project"),
        UniqueConstraint("id", "requirement_id", name="uq_requirement_invariants_id_requirement"),
        UniqueConstraint("requirement_id", "key", name="uq_requirement_invariants_requirement_key"),
        ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="CASCADE",
            name="fk_requirement_invariants_requirement_project",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="CASCADE",
            name="fk_requirement_invariants_requirement_section",
        ),
        Index("ix_requirement_invariants_project_id", "project_id"),
        Index("ix_requirement_invariants_requirement_id", "requirement_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_section: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="requirements"
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    author: Mapped[str] = mapped_column(String(120), nullable=False, server_default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AcceptanceCriterion(Base):
    """One acceptance criterion linked to an invariant (T10). Soft-deleted, never hard-deleted."""

    __tablename__ = "acceptance_criteria"
    __table_args__ = (
        CheckConstraint(
            "evidence_kind IN ('test', 'command', 'review', 'manual', 'file')",
            name="ck_acceptance_criteria_evidence_kind",
        ),
        CheckConstraint(
            "independent_review IN ('not-required', 'required')",
            name="ck_acceptance_criteria_independent_review",
        ),
        CheckConstraint(
            "status IN ('open', 'deleted')",
            name="ck_acceptance_criteria_status",
        ),
        CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 2000",
            name="ck_acceptance_criteria_statement_len",
        ),
        CheckConstraint(
            "char_length(key) BETWEEN 1 AND 64",
            name="ck_acceptance_criteria_key_len",
        ),
        UniqueConstraint("invariant_id", "key", name="uq_acceptance_criteria_invariant_key"),
        UniqueConstraint("id", "project_id", name="uq_acceptance_criteria_id_project"),
        ForeignKeyConstraint(
            ["invariant_id", "project_id"],
            ["requirement_invariants.id", "requirement_invariants.project_id"],
            ondelete="CASCADE",
            name="fk_acceptance_criteria_invariant_project",
        ),
        Index("ix_acceptance_criteria_project_id", "project_id"),
        Index("ix_acceptance_criteria_invariant_id", "invariant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    invariant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    independent_review: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="not-required"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    author: Mapped[str] = mapped_column(String(120), nullable=False, server_default="agent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequirementContractRevision(Base):
    """Append-only audit row for one contract create/update/delete (T10).

    Retention: rows outlive soft-delete of the parent requirement. Hard-delete of
    that requirement is RESTRICTed while history exists. Project teardown may
    CASCADE via ``project_id``. PostgreSQL rejects UPDATE and DELETE (append-only trigger).
    """

    __tablename__ = "requirement_contract_revisions"
    __table_args__ = (
        CheckConstraint(
            "entity_kind IN ('invariant', 'criterion')",
            name="ck_requirement_contract_revisions_entity_kind",
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'delete')",
            name="ck_requirement_contract_revisions_action",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_contract_revisions_requirement_project",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="RESTRICT",
            name="fk_requirement_contract_revisions_requirement_section",
        ),
        CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_contract_revisions_section",
        ),
        UniqueConstraint(
            "id", "requirement_id", name="uq_requirement_contract_revisions_id_requirement"
        ),
        UniqueConstraint("id", "entity_id", name="uq_requirement_contract_revisions_id_entity"),
        Index(
            "ix_requirement_contract_revisions_requirement_created",
            "requirement_id",
            "created_at",
        ),
        Index("ix_requirement_contract_revisions_project_id", "project_id"),
        Index("ix_requirement_contract_revisions_entity_id", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_section: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="requirements"
    )
    entity_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequirementEvidence(Base):
    """Append-only compact evidence row bound to one contract revision (T12, D4)."""

    __tablename__ = "requirement_evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_kind IN ('test', 'command', 'review', 'manual', 'file')",
            name="ck_requirement_evidence_kind",
        ),
        CheckConstraint(
            "result IN ('passed', 'failed', 'manual-pending')",
            name="ck_requirement_evidence_result",
        ),
        CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_evidence_section",
        ),
        CheckConstraint(
            "char_length(source_commit) = 40",
            name="ck_requirement_evidence_commit_len",
        ),
        CheckConstraint(
            "recording_state IN ('provisional', 'verified-at-commit')",
            name="ck_requirement_evidence_recording_state",
        ),
        CheckConstraint(
            "claim_ref IS NULL OR char_length(claim_ref) BETWEEN 1 AND 160",
            name="ck_requirement_evidence_claim_ref_len",
        ),
        CheckConstraint(
            (
                "review_ref IS NULL OR review_ref ~ '^(criterion|invariant):[0-9a-f]{8}-"
                "[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'"
            ),
            name="ck_requirement_evidence_review_ref",
        ),
        UniqueConstraint("id", "project_id", name="uq_requirement_evidence_id_project"),
        ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_requirement_project",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_requirement_section",
        ),
        ForeignKeyConstraint(
            ["criterion_id", "project_id"],
            ["acceptance_criteria.id", "acceptance_criteria.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_criterion_project",
        ),
        ForeignKeyConstraint(
            ["contract_revision_id", "requirement_id"],
            [
                "requirement_contract_revisions.id",
                "requirement_contract_revisions.requirement_id",
            ],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_revision_requirement",
        ),
        ForeignKeyConstraint(
            ["contract_revision_id", "criterion_id"],
            ["requirement_contract_revisions.id", "requirement_contract_revisions.entity_id"],
            ondelete="RESTRICT",
            name="fk_requirement_evidence_revision_criterion",
        ),
        Index("ix_requirement_evidence_project_id", "project_id"),
        Index("ix_requirement_evidence_criterion_created", "criterion_id", "seq"),
        Index("ix_requirement_evidence_requirement_id", "requirement_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_section: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="requirements"
    )
    criterion_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contract_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    command_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    test_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    worktree_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    claim_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    review_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recording_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="provisional"
    )
    source_commit_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    file_ref_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    test_ref_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )


class RequirementViolation(Base):
    """Review finding linked to one invariant. Resolve updates status; rows are kept (T12)."""

    __tablename__ = "requirement_violations"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('blocking', 'warning')",
            name="ck_requirement_violations_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="ck_requirement_violations_status",
        ),
        CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_requirement_violations_section",
        ),
        CheckConstraint(
            "char_length(summary) BETWEEN 1 AND 200",
            name="ck_requirement_violations_summary_len",
        ),
        CheckConstraint(
            "line_no IS NULL OR line_no >= 1",
            name="ck_requirement_violations_line_no",
        ),
        UniqueConstraint("id", "project_id", name="uq_requirement_violations_id_project"),
        ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_requirement_project",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_requirement_section",
        ),
        ForeignKeyConstraint(
            ["invariant_id", "project_id"],
            ["requirement_invariants.id", "requirement_invariants.project_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_invariant_project",
        ),
        ForeignKeyConstraint(
            ["invariant_id", "requirement_id"],
            ["requirement_invariants.id", "requirement_invariants.requirement_id"],
            ondelete="RESTRICT",
            name="fk_requirement_violations_invariant_requirement",
        ),
        Index("ix_requirement_violations_project_id", "project_id"),
        Index("ix_requirement_violations_invariant_id", "invariant_id"),
        Index("ix_requirement_violations_requirement_id", "requirement_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_section: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="requirements"
    )
    invariant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    file_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    line_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
