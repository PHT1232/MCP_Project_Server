"""ORM models for Plan & Task Orchestration (FR43-FR48, D18-D21, INV-PLAN-1..4).

Defines plans, plan_tasks, task_dependencies, plan_task_requirements, and
plan_task_events. Composite foreign keys enforce strict database-level project
and plan isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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

__all__ = [
    "Plan",
    "PlanTask",
    "PlanTaskEvent",
    "PlanTaskRequirement",
    "TaskDependency",
]


def _new_id() -> str:
    return str(uuid.uuid4())


class Plan(Base):
    """A deterministic milestone execution plan (FR43, D18)."""

    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'archived')",
            name="ck_plans_status",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 160",
            name="ck_plans_title_len",
        ),
        CheckConstraint(
            "char_length(goal) BETWEEN 1 AND 8000",
            name="ck_plans_goal_len",
        ),
        UniqueConstraint("id", "project_id", name="uq_plans_id_project"),
        Index("ix_plans_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    author: Mapped[str] = mapped_column(
        String(120), nullable=False, default="agent", server_default="agent"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tasks: Mapped[list[PlanTask]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PlanTask(Base):
    """An individual ordered task within a plan (FR44, D18, D20)."""

    __tablename__ = "plan_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ready', 'claimed', 'in_progress', 'blocked', "
            "'in_review', 'completed', 'cancelled')",
            name="ck_plan_tasks_status",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 160",
            name="ck_plan_tasks_title_len",
        ),
        CheckConstraint(
            "char_length(objective) BETWEEN 1 AND 8000",
            name="ck_plan_tasks_objective_len",
        ),
        CheckConstraint(
            "char_length(local_task_id) BETWEEN 1 AND 32",
            name="ck_plan_tasks_local_task_id_len",
        ),
        ForeignKeyConstraint(
            ["plan_id", "project_id"],
            ["plans.id", "plans.project_id"],
            ondelete="CASCADE",
            name="fk_plan_tasks_plan",
        ),
        UniqueConstraint("id", "plan_id", "project_id", name="uq_plan_tasks_id_plan_project"),
        UniqueConstraint("id", "project_id", name="uq_plan_tasks_id_project"),
        UniqueConstraint("plan_id", "local_task_id", name="uq_plan_tasks_plan_local_id"),
        Index("ix_plan_tasks_project_status", "project_id", "status"),
        Index("ix_plan_tasks_plan_status", "plan_id", "status"),
        Index("ix_plan_tasks_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    local_task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    linked_files: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    # Claim lease fields (FR47, D20)
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plan: Mapped[Plan] = relationship(back_populates="tasks")
    events: Mapped[list[PlanTaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TaskDependency(Base):
    """Directed dependency edge between two tasks in the same plan and project.

    Enforces INV-PLAN-1 and FR45.
    """

    __tablename__ = "task_dependencies"
    __table_args__ = (
        CheckConstraint("task_id != depends_on_task_id", name="ck_task_dependencies_no_self_dep"),
        ForeignKeyConstraint(
            ["task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_deps_task",
        ),
        ForeignKeyConstraint(
            ["depends_on_task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_task_deps_depends_on",
        ),
        Index("ix_task_dependencies_depends_on", "depends_on_task_id"),
        Index("ix_task_dependencies_plan_id", "plan_id"),
    )

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    depends_on_task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PlanTaskRequirement(Base):
    """Link between a task and a requirement entry in the curated context store (INV-PLAN-1)."""

    __tablename__ = "plan_task_requirements"
    __table_args__ = (
        CheckConstraint(
            "requirement_section = 'requirements'",
            name="ck_plan_task_requirements_section",
        ),
        ForeignKeyConstraint(
            ["plan_task_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_task",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "project_id"],
            ["context_entries.id", "context_entries.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_req_project",
        ),
        ForeignKeyConstraint(
            ["requirement_id", "requirement_section"],
            ["context_entries.id", "context_entries.section"],
            ondelete="CASCADE",
            name="fk_plan_task_reqs_req_section",
        ),
        Index("ix_plan_task_requirements_project_req", "project_id", "requirement_id"),
        Index("ix_plan_task_requirements_task_id", "plan_task_id"),
    )

    plan_task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requirement_section: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="requirements"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PlanTaskEvent(Base):
    """Append-only audit row recording one task mutation (FR48, D21, INV-PLAN-4)."""

    __tablename__ = "plan_task_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'dependency_added', 'claimed', "
            "'reclaimed', 'heartbeat', 'released', 'status_changed', 'completed', 'cancelled')",
            name="ck_plan_task_events_event_type",
        ),
        ForeignKeyConstraint(
            ["task_id", "plan_id", "project_id"],
            ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"],
            ondelete="CASCADE",
            name="fk_plan_task_events_task_plan_project",
        ),
        Index("ix_plan_task_events_task_created", "task_id", "created_at"),
        Index("ix_plan_task_events_plan_created", "plan_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task: Mapped[PlanTask] = relationship(back_populates="events")
