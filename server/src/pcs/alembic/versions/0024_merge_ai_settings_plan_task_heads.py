"""Merge the T20 and T23 Alembic migration heads.

Revision ID: 0024_merge_t20_t23
Revises: 0020_ai_provider_settings, 0023_plan_task_orchestration

This merge revision preserves both independently deployed migration paths
after T20/T21 and T23 are integrated on main. It intentionally changes no
schema objects.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0024_merge_t20_t23"
down_revision: str | Sequence[str] | None = (
    "0020_ai_provider_settings",
    "0023_plan_task_orchestration",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the T20 and T23 revision branches without schema changes."""


def downgrade() -> None:
    """Split the revision branches without schema changes."""
