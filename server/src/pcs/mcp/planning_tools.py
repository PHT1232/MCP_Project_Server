"""MCP tools for Plan & Task Orchestration (T24, AC-PLAN-7, FR43-FR48).

Thin wrappers: resolve caller → session_scope → ``pcs.planning.service`` →
``log_tool_call`` (NFR6). No SQL or business logic lives here. Audit outcomes
are categories only — never claim tokens or request payloads (INV-PLAN-3, NFR6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from pydantic.experimental.missing_sentinel import MISSING
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service as context_service
from pcs.db.base import session_scope
from pcs.logging import log_tool_call
from pcs.mcp.support import caller
from pcs.planning import generator
from pcs.planning import service as planning
from pcs.planning.errors import (
    ClaimConflictError,
    DependencyCycleError,
    InvalidStateTransitionError,
    PlanningValidationError,
    PlanNotActiveError,
    PlanNotFoundError,
    StaleClaimTokenError,
    TaskNotFoundError,
)
from pcs.planning.types import DEFAULT_LEASE_SECONDS, DependencySpec, TaskSpec

EMPTY_MUTATION = "empty mutation; omit fields to keep them, or supply at least one change"
EXPLICIT_NULL = "explicit null is rejected; omit the field to leave it unchanged"
UNKNOWN_FIELDS = "request contains unknown fields"

_TASK_SPEC_FIELDS = frozenset(
    {
        "local_task_id",
        "title",
        "objective",
        "acceptance_criteria",
        "linked_files",
        "requirement_ids",
        "priority",
    }
)
_DEPENDENCY_SPEC_FIELDS = frozenset({"task_local_id", "depends_on_local_id"})


def _patch_value(value: object) -> object | None:
    """Map omitted MCP fields to service omission and reject explicit null in-tool."""
    if value is MISSING:
        return None
    if value is None:
        raise PlanningValidationError(EXPLICIT_NULL)
    return value


def _patch_str(value: object, *, field: str) -> str | None:
    value = _patch_value(value)
    if value is not None and not isinstance(value, str):
        raise PlanningValidationError(f"{field} must be a string")
    return value


def _patch_int(value: object, *, field: str) -> int | None:
    value = _patch_value(value)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise PlanningValidationError(f"{field} must be an integer")
    return value


def _patch_str_list(value: object, *, field: str) -> list[str] | None:
    value = _patch_value(value)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PlanningValidationError(f"{field} must be a list of strings")
    return [str(item) for item in value]


def _require_update(*values: object) -> None:
    """Reject a merge-update that supplied no fields."""
    if all(value is None for value in values):
        raise PlanningValidationError(EMPTY_MUTATION)


def task_specs_from_payload(raw: object) -> list[TaskSpec]:
    """Convert a raw ``tasks`` payload into :class:`TaskSpec` (FR44, INV-PLAN-1)."""
    if not isinstance(raw, list) or not raw:
        raise PlanningValidationError("tasks must be a non-empty list of objects.")
    specs: list[TaskSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlanningValidationError("Each task must be an object.")
        typed = {str(key): value for key, value in item.items()}
        if any(name not in _TASK_SPEC_FIELDS for name in typed):
            raise PlanningValidationError(UNKNOWN_FIELDS)
        for required in ("local_task_id", "title", "objective"):
            value = typed.get(required)
            if not isinstance(value, str) or not value.strip():
                raise PlanningValidationError(
                    f"Task field {required!r} must be a non-empty string."
                )
        acceptance_criteria = typed.get("acceptance_criteria", [])
        linked_files = typed.get("linked_files", [])
        requirement_ids = typed.get("requirement_ids", [])
        priority = typed.get("priority", 0)
        if not isinstance(acceptance_criteria, list) or any(
            not isinstance(v, str) for v in acceptance_criteria
        ):
            raise PlanningValidationError("acceptance_criteria must be a list of strings.")
        if not isinstance(linked_files, list) or any(not isinstance(v, str) for v in linked_files):
            raise PlanningValidationError("linked_files must be a list of strings.")
        if not isinstance(requirement_ids, list) or any(
            not isinstance(v, str) for v in requirement_ids
        ):
            raise PlanningValidationError("requirement_ids must be a list of strings.")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise PlanningValidationError("priority must be an integer.")
        specs.append(
            TaskSpec(
                local_task_id=str(typed["local_task_id"]),
                title=str(typed["title"]),
                objective=str(typed["objective"]),
                acceptance_criteria=[str(v) for v in acceptance_criteria],
                linked_files=[str(v) for v in linked_files],
                requirement_ids=[str(v) for v in requirement_ids],
                priority=priority,
            )
        )
    return specs


def dependency_specs_from_payload(raw: object) -> list[DependencySpec]:
    """Convert a raw ``dependencies`` payload into :class:`DependencySpec` (FR45)."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlanningValidationError("dependencies must be a list of objects.")
    specs: list[DependencySpec] = []
    for item in raw:
        if not isinstance(item, dict):
            raise PlanningValidationError("Each dependency must be an object.")
        typed = {str(key): value for key, value in item.items()}
        if any(name not in _DEPENDENCY_SPEC_FIELDS for name in typed):
            raise PlanningValidationError(UNKNOWN_FIELDS)
        task_local_id = typed.get("task_local_id")
        depends_on_local_id = typed.get("depends_on_local_id")
        if not isinstance(task_local_id, str) or not isinstance(depends_on_local_id, str):
            raise PlanningValidationError(
                "dependency fields 'task_local_id' and 'depends_on_local_id' must be strings."
            )
        specs.append(
            DependencySpec(task_local_id=task_local_id, depends_on_local_id=depends_on_local_id)
        )
    return specs


def audit_outcome(exc: BaseException) -> str:
    """Safe audit outcome: category only, never caller payload (NFR6, INV-PLAN-3)."""
    if isinstance(exc, context_service.ProjectNotFoundError):
        return "error: project-not-found"
    if isinstance(exc, (PlanNotFoundError, TaskNotFoundError)):
        return "error: not-found"
    if isinstance(exc, ClaimConflictError):
        return "error: claim-conflict"
    if isinstance(exc, StaleClaimTokenError):
        return "error: stale-token"
    if isinstance(exc, PlanNotActiveError):
        return "error: plan-not-active"
    if isinstance(exc, InvalidStateTransitionError):
        return "error: invalid-state"
    if isinstance(exc, DependencyCycleError):
        return "error: dependency-cycle"
    if isinstance(exc, (PlanningValidationError, ValueError)):
        return "error: validation"
    return "error: failed"


async def _run_logged[T](
    tool: str,
    project: str | None,
    who: str,
    op: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    """Session helper whose audit errors are categories only (NFR6)."""
    try:
        async with session_scope() as session:
            result = await op(session)
    except Exception as exc:
        log_tool_call(tool=tool, project=project, caller=who, outcome=audit_outcome(exc))
        raise
    log_tool_call(tool=tool, project=project, caller=who, outcome="ok")
    return result


def register_planning_tools(mcp: FastMCP) -> None:
    """Attach the T24 planning tools to ``mcp`` (AC-PLAN-7)."""

    @mcp.tool()
    async def create_plan(
        project: str,
        title: str,
        goal: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Create an empty plan in 'draft' status (FR43, D18)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.create_plan(
                session, project=project or "", title=title, goal=goal, author=who
            )
            return view.as_dict()

        return await _run_logged("create_plan", project, who, op)

    @mcp.tool()
    async def create_plan_with_tasks(
        project: str,
        title: str,
        goal: str,
        tasks: list[dict[str, Any]],
        dependencies: list[dict[str, Any]] | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Atomically create a plan with its task DAG (FR43-FR45, D18, D23)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.create_plan_with_tasks(
                session,
                project=project or "",
                title=title,
                goal=goal,
                tasks=task_specs_from_payload(tasks),
                dependencies=dependency_specs_from_payload(dependencies),
                author=who,
            )
            return view.as_dict()

        return await _run_logged("create_plan_with_tasks", project, who, op)

    @mcp.tool()
    async def list_plans(
        project: str,
        status: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> list[dict[str, object]]:
        """List plans in a project, optionally filtered by status (FR43)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> list[dict[str, object]]:
            views = await planning.list_plans(session, project=project or "", status=status)
            return [view.as_dict() for view in views]

        return await _run_logged("list_plans", project, who, op)

    @mcp.tool()
    async def get_plan(
        project: str,
        plan_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Return one plan with tasks, dependencies, and requirement links (FR43)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.get_plan(session, project=project or "", plan_id=plan_id)
            return view.as_dict()

        return await _run_logged("get_plan", project, who, op)

    @mcp.tool()
    async def update_plan(
        project: str,
        plan_id: str,
        title: object = MISSING,
        goal: object = MISSING,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Merge-update a plan's title and/or goal; empty patch is rejected (FR43)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            values = (_patch_str(title, field="title"), _patch_str(goal, field="goal"))
            _require_update(*values)
            view = await planning.update_plan(
                session,
                project=project or "",
                plan_id=plan_id,
                title=values[0],
                goal=values[1],
            )
            return view.as_dict()

        return await _run_logged("update_plan", project, who, op)

    @mcp.tool()
    async def archive_plan(
        project: str,
        plan_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Archive a plan, atomically revoking all active leases (FR43, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.archive_plan(
                session, project=project or "", plan_id=plan_id, actor=who
            )
            return view.as_dict()

        return await _run_logged("archive_plan", project, who, op)

    @mcp.tool()
    async def activate_plan(
        project: str,
        plan_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Activate a draft plan; zero-dependency tasks become ready (FR43, FR44)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.activate_plan(
                session, project=project or "", plan_id=plan_id, actor=who
            )
            return view.as_dict()

        return await _run_logged("activate_plan", project, who, op)

    @mcp.tool()
    async def add_plan_task(
        project: str,
        plan_id: str,
        local_task_id: str,
        title: str,
        objective: str,
        acceptance_criteria: list[str] | None = None,
        linked_files: list[str] | None = None,
        requirement_ids: list[str] | None = None,
        priority: int = 0,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Add one task to a draft or active plan (FR44)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.add_plan_task(
                session,
                project=project or "",
                plan_id=plan_id,
                local_task_id=local_task_id,
                title=title,
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                linked_files=linked_files,
                requirement_ids=requirement_ids,
                priority=priority,
                actor=who,
            )
            return view.as_dict()

        return await _run_logged("add_plan_task", project, who, op)

    @mcp.tool()
    async def update_plan_task(
        project: str,
        plan_id: str,
        task_id: str,
        title: object = MISSING,
        objective: object = MISSING,
        acceptance_criteria: object = MISSING,
        linked_files: object = MISSING,
        requirement_ids: object = MISSING,
        priority: object = MISSING,
        claim_token: object = MISSING,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Merge-update a task; omitted fields stay (FR44, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            values = (
                _patch_str(title, field="title"),
                _patch_str(objective, field="objective"),
                _patch_str_list(acceptance_criteria, field="acceptance_criteria"),
                _patch_str_list(linked_files, field="linked_files"),
                _patch_str_list(requirement_ids, field="requirement_ids"),
                _patch_int(priority, field="priority"),
            )
            token = _patch_str(claim_token, field="claim_token")
            _require_update(*values)
            view = await planning.update_plan_task(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                title=values[0],
                objective=values[1],
                acceptance_criteria=values[2],
                linked_files=values[3],
                requirement_ids=values[4],
                priority=values[5],
                claim_token=token,
                actor=who,
            )
            return view.as_dict()

        return await _run_logged("update_plan_task", project, who, op)

    @mcp.tool()
    async def add_task_dependency(
        project: str,
        plan_id: str,
        task_id: str,
        depends_on_task_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Add a prerequisite edge between two tasks in the same plan (FR45, INV-PLAN-1)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            await planning.add_task_dependency(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                depends_on_task_id=depends_on_task_id,
                actor=who,
            )
            return {"task_id": task_id, "depends_on_task_id": depends_on_task_id}

        return await _run_logged("add_task_dependency", project, who, op)

    @mcp.tool()
    async def list_ready_tasks(
        project: str,
        plan_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> list[dict[str, object]]:
        """Return ready/reclaimable tasks across active plans or one plan (FR46, D18)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> list[dict[str, object]]:
            views = await planning.list_ready_tasks(session, project=project or "", plan_id=plan_id)
            return [view.as_dict() for view in views]

        return await _run_logged("list_ready_tasks", project, who, op)

    @mcp.tool()
    async def claim_task(
        project: str,
        plan_id: str,
        task_id: str,
        claimed_by: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Atomically claim/reclaim a task; the token is returned exactly once (FR47, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            result = await planning.claim_task(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                claimed_by=claimed_by,
                lease_seconds=lease_seconds,
            )
            return result.as_dict()

        return await _run_logged("claim_task", project, who, op)

    @mcp.tool()
    async def heartbeat_task(
        project: str,
        plan_id: str,
        task_id: str,
        claim_token: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Extend a task lease, strictly preserving its status (FR47, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.heartbeat_task(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                claim_token=claim_token,
                lease_seconds=lease_seconds,
            )
            return view.as_dict()

        return await _run_logged("heartbeat_task", project, who, op)

    @mcp.tool()
    async def release_task(
        project: str,
        plan_id: str,
        task_id: str,
        claim_token: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Release a claimed/in_progress task back to ready (FR47, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.release_task(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                claim_token=claim_token,
            )
            return view.as_dict()

        return await _run_logged("release_task", project, who, op)

    @mcp.tool()
    async def set_task_status(
        project: str,
        plan_id: str,
        task_id: str,
        status: str,
        claim_token: str | None = None,
        reason: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Transition a task's status, enforcing lease rules (FR44, FR47, D20)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.set_task_status(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                status=status,
                claim_token=claim_token,
                reason=reason,
                actor=who,
            )
            return view.as_dict()

        return await _run_logged("set_task_status", project, who, op)

    @mcp.tool()
    async def complete_task(
        project: str,
        plan_id: str,
        task_id: str,
        claim_token: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Complete a task, revoke its lease, and unlock downstream tasks (FR44, FR47, D4)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.complete_task(
                session,
                project=project or "",
                plan_id=plan_id,
                task_id=task_id,
                claim_token=claim_token,
                actor=who,
            )
            return view.as_dict()

        return await _run_logged("complete_task", project, who, op)

    @mcp.tool()
    async def complete_plan(
        project: str,
        plan_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Complete an active plan whose tasks are all terminal (FR43, D4)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await planning.complete_plan(
                session, project=project or "", plan_id=plan_id, actor=who
            )
            return view.as_dict()

        return await _run_logged("complete_plan", project, who, op)

    @mcp.tool()
    async def get_task_history(
        project: str,
        plan_id: str,
        task_id: str,
        ctx: Context[Any, Any] | None = None,
    ) -> list[dict[str, object]]:
        """Return the immutable chronological audit history for a task (FR48, D21)."""
        who = caller(ctx)

        async def op(session: AsyncSession) -> list[dict[str, object]]:
            events = await planning.get_task_history(
                session, project=project or "", plan_id=plan_id, task_id=task_id
            )
            return [event.as_dict() for event in events]

        return await _run_logged("get_task_history", project, who, op)

    @mcp.tool()
    async def generate_plan_draft(
        project: str,
        goal: str,
        constraints: str | None = None,
        max_tasks: int = generator.MAX_TASKS_DEFAULT,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Advisory, read-only AI plan draft; persists nothing (T26, INV-PLAN-6).

        Uses the project's persisted T20 summary provider. Returns ``ok=False``
        with a ``warning`` — never an error — when the provider is unconfigured,
        unreachable, or returns an invalid proposal. Nothing is written to
        ``plans``/``plan_tasks``/etc. until the caller separately calls
        ``create_plan_with_tasks`` with data of their own choosing.
        """
        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            result = await generator.generate_plan_draft(
                session,
                project=project or "",
                goal=goal,
                constraints=constraints,
                max_tasks=max_tasks,
            )
            return result.as_dict()

        return await _run_logged("generate_plan_draft", project, who, op)
