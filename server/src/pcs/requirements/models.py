"""ORM model for the requirements-file sync state (FR16a, D15).

One row per project records the last successful ``sync_requirements``: the file
path used, its SHA-256, the parsed snapshot the 3-way merge diffs against, and
the monotonic counter that hands out ``R-NNN`` keys (never reused, per FR16a).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pcs.db.base import Base

__all__ = ["RequirementsSyncState"]


class RequirementsSyncState(Base):
    """Last-synced snapshot of a project's requirements template file (FR16a)."""

    __tablename__ = "requirements_sync_state"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    # Resolved absolute path of the file at the last sync (FR16a, configurable).
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the file contents as last written/read by the server.
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Next R-NNN sequence number to assign; only ever increases (never reused).
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Parsed state at the last sync: [{req_key, title, prose_hash, status}, ...].
    snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
