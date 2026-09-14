"""Planning domain types, dataclasses, and lifecycle constants (FR43-FR53).

Plain dataclasses and immutable constants. No ORM models or database I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

# Plan lifecycle statuses (FR43, D18)
PLAN_STATUS_DRAFT: Final = "draft"
PLAN_STATUS_ACTIVE: Final = "active"
PLAN_STATUS_COMPLETED: Final = "completed"
PLAN_STATUS_ARCHIVED: Final = "archived"
PLAN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        PLAN_STATUS_DRAFT,
        PLAN_STATUS_ACTIVE,
        PLAN_STATUS_COMPLETED,
        PLAN_STATUS_ARCHIVED,
    }
)

# Task lifecycle statuses (FR44, FR47, D18, D20)
TASK_STATUS_PENDING: Final = "pending"
TASK_STATUS_READY: Final = "ready"
TASK_STATUS_CLAIMED: Final = "claimed"
TASK_STATUS_IN_PROGRESS: Final = "in_progress"
TASK_STATUS_BLOCKED: Final = "blocked"
TASK_STATUS_IN_REVIEW: Final = "in_review"
TASK_STATUS_COMPLETED: Final = "completed"
TASK_STATUS_CANCELLED: Final = "cancelled"
TASK_STATUSES: Final[frozenset[str]] = frozenset(
    {
        TASK_STATUS_PENDING,
        TASK_STATUS_READY,
        TASK_STATUS_CLAIMED,
        TASK_STATUS_IN_PROGRESS,
        TASK_STATUS_BLOCKED,
        TASK_STATUS_IN_REVIEW,
        TASK_STATUS_COMPLETED,
        TASK_STATUS_CANCELLED,
    }
)
TERMINAL_TASK_STATUSES: Final[frozenset[str]] = frozenset(
    {TASK_STATUS_COMPLETED, TASK_STATUS_CANCELLED}
)

# 10 discrete task event types (FR48, D21, INV-PLAN-4)
EVENT_CREATED: Final = "created"
EVENT_UPDATED: Final = "updated"
EVENT_DEPENDENCY_ADDED: Final = "dependency_added"
EVENT_CLAIMED: Final = "claimed"
EVENT_RECLAIMED: Final = "reclaimed"
EVENT_HEARTBEAT: Final = "heartbeat"
EVENT_RELEASED: Final = "released"
EVENT_STATUS_CHANGED: Final = "status_changed"
EVENT_COMPLETED: Final = "completed"
EVENT_CANCELLED: Final = "cancelled"
TASK_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        EVENT_CREATED,
        EVENT_UPDATED,
        EVENT_DEPENDENCY_ADDED,
        EVENT_CLAIMED,
        EVENT_RECLAIMED,
        EVENT_HEARTBEAT,
        EVENT_RELEASED,
        EVENT_STATUS_CHANGED,
        EVENT_COMPLETED,
        EVENT_CANCELLED,
    }
)

# Field limits and defaults
TITLE_MAX_CHARS: Final = 160
GOAL_MAX_CHARS: Final = 8000
OBJECTIVE_MAX_CHARS: Final = 8000
LOCAL_TASK_ID_MAX_CHARS: Final = 32
DEFAULT_LEASE_SECONDS: Final = 1800
MIN_LEASE_SECONDS: Final = 30
MAX_LEASE_SECONDS: Final = 86400
MAX_REASON_CHARS: Final = 200


@dataclass(frozen=True)
class PlanTaskView:
    """Public immutable snapshot of a plan task (FR44, INV-PLAN-1).

    Never exposes raw claim token or token hash (NFR6, FR47).
    """

    id: str
    plan_id: str
    project_id: str
    local_task_id: str
    title: str
    objective: str
    acceptance_criteria: list[str]
    linked_files: list[str]
    priority: int
    status: str
    claimed_by: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    dependencies: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict with ISO timestamps."""
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "project_id": self.project_id,
            "local_task_id": self.local_task_id,
            "title": self.title,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "linked_files": list(self.linked_files),
            "priority": self.priority,
            "status": self.status,
            "claimed_by": self.claimed_by,
            "lease_expires_at": (
                self.lease_expires_at.isoformat() if self.lease_expires_at else None
            ),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "dependencies": list(self.dependencies),
            "requirement_ids": list(self.requirement_ids),
        }


@dataclass(frozen=True)
class PlanView:
    """Public immutable snapshot of a plan (FR43, INV-PLAN-1)."""

    id: str
    project_id: str
    title: str
    goal: str
    status: str
    author: str
    created_at: datetime
    updated_at: datetime
    tasks: list[PlanTaskView] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict with ISO timestamps."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "goal": self.goal,
            "status": self.status,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tasks": [t.as_dict() for t in self.tasks],
        }


@dataclass(frozen=True)
class ClaimResult:
    """Result of an atomic task claim, containing the ephemeral token once (FR47, INV-PLAN-3)."""

    task: PlanTaskView
    claim_token: str

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict with the ephemeral one-time claim token."""
        return {
            "task": self.task.as_dict(),
            "claim_token": self.claim_token,
        }


@dataclass(frozen=True)
class TaskEventView:
    """Immutable audit record of a task mutation (FR48, D21, INV-PLAN-4)."""

    id: str
    project_id: str
    plan_id: str
    task_id: str
    event_type: str
    actor: str
    old_status: str | None
    new_status: str | None
    payload: dict[str, Any]
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        """JSON-ready dict with ISO timestamps."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "payload": dict(self.payload),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class TaskSpec:
    """Specification for creating a task within a plan."""

    local_task_id: str
    title: str
    objective: str
    acceptance_criteria: list[str] = field(default_factory=list)
    linked_files: list[str] = field(default_factory=list)
    requirement_ids: list[str] = field(default_factory=list)
    priority: int = 0


@dataclass(frozen=True)
class DependencySpec:
    """Specification of a prerequisite dependency between tasks in a plan."""

    task_local_id: str
    depends_on_local_id: str
