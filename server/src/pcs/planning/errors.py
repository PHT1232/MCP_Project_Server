"""Planning domain errors (FR43-FR53, INV-PLAN-1..INV-PLAN-4).

No ORM or I/O — imported by service, MCP, and HTTP layers.
"""

from __future__ import annotations

from pcs.context.types import ValidationError


class PlanningError(Exception):
    """Base exception for planning domain operations."""


class PlanNotFoundError(PlanningError):
    """The requested plan does not exist in the specified project."""

    def __init__(self, plan_id: str, project: str) -> None:
        self.plan_id = plan_id
        self.project = project
        super().__init__(f"No plan {plan_id!r} in project {project!r}.")


class TaskNotFoundError(PlanningError):
    """The requested task does not exist in the specified plan or project."""

    def __init__(
        self,
        task_id: str,
        plan_id: str | None = None,
        project: str | None = None,
    ) -> None:
        self.task_id = task_id
        self.plan_id = plan_id
        self.project = project
        parts = [f"No task {task_id!r}"]
        if plan_id:
            parts.append(f"in plan {plan_id!r}")
        if project:
            parts.append(f"in project {project!r}")
        super().__init__(" ".join(parts) + ".")


class PlanningValidationError(PlanningError, ValidationError):
    """Malformed planning request or constraint violation."""


class DependencyCycleError(PlanningValidationError):
    """Acyclic dependency violation (INV-PLAN-1, FR45)."""


class ClaimConflictError(PlanningError):
    """Task claim collision or unexpired lease conflict (INV-PLAN-3, FR47)."""


class StaleClaimTokenError(PlanningError):
    """Presented token is invalid, revoked, mismatched, or expired (INV-PLAN-3, FR47)."""


class PlanNotActiveError(PlanningError):
    """Operation rejected because plan is not active (draft, completed, or archived)."""


class InvalidStateTransitionError(PlanningValidationError):
    """Disallowed task status transition (FR44, FR47)."""
