"""ORM models for the walking skeleton (FR1, FR3, FR4).

Deliberately minimal: a ``projects`` row and a flat ``context_entries`` table
with just enough columns to prove the vertical slice. T01 owns the real context
schema (``headline``/``detail`` split rules, priority, audit-log revisions,
per-section constraints) and will migrate this forward.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pcs.db.base import Base

__all__ = ["Base", "ContextEntry", "Project"]

# T00 uses only these two sections; T01 introduces the full set.
SECTION_OVERVIEW = "overview"
SECTION_FOCUS = "focus"

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"


def _new_id() -> str:
    return str(uuid.uuid4())


class Project(Base):
    """A registered project context, selected explicitly by name or id (D3, FR1)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    root_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entries: Mapped[list[ContextEntry]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContextEntry(Base):
    """One piece of curated context. Flat for T00; T01 replaces this (FR2, FR3b)."""

    __tablename__ = "context_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(32), index=True)
    headline: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=STATUS_OPEN)
    author: Mapped[str] = mapped_column(String(120), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="entries")
