"""ORM models for the curated context store (FR1-FR4, FR3a, FR3b, FR9g, FR11, D5).

``projects`` holds per-project budgets and expiry policy. ``context_entries`` is
the verbatim store (never replaced by a summary). ``context_entry_revisions`` is
the immutable audit log — nothing is hard-deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pcs.db.base import Base

__all__ = ["Base", "ContextEntry", "ContextEntryRevision", "Project"]


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
