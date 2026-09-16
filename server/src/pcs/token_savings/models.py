"""ORM model for the token-savings log.

One append-only row per recorded call to retrieve_context, search_code,
prepare_task, or get_project_briefing, capturing both the tokens actually
returned and a baseline of what returning the full untruncated content
would have cost — the delta is the savings PCS's budget-bounded retrieval
provides over reading whole files/sections directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from pcs.db.base import Base

__all__ = ["TokenSavingsLogEntry"]

OPERATIONS = ("retrieve_context", "search_code", "prepare_task", "get_project_briefing")


def _new_id() -> str:
    return str(uuid.uuid4())


class TokenSavingsLogEntry(Base):
    """One recorded actual-vs-baseline token comparison (append-only)."""

    __tablename__ = "token_savings_log"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('retrieve_context', 'search_code', 'prepare_task', "
            "'get_project_briefing')",
            name="ck_token_savings_log_operation",
        ),
        CheckConstraint("actual_tokens >= 0", name="ck_token_savings_log_actual_nonneg"),
        CheckConstraint("baseline_tokens >= 0", name="ck_token_savings_log_baseline_nonneg"),
        CheckConstraint("saved_tokens >= 0", name="ck_token_savings_log_saved_nonneg"),
        Index("ix_token_savings_log_project_created", "project_id", "created_at"),
        Index("ix_token_savings_log_project_operation", "project_id", "operation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    caller: Mapped[str] = mapped_column(String(120), nullable=False)
    actual_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    saved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
