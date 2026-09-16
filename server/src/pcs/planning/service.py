"""Deterministic planning domain service (FR43-FR48, FR53, D18-D21, INV-PLAN-1..4).

Plain async functions over :class:`AsyncSession`. No MCP or HTTP transport imports.
Enforces DAG validation, composite foreign key isolation, atomic claim leases,
immutable event audit logs, and requirement independence (D4).
"""

from __future__ import annotations

import hashlib
import secrets
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from pcs.planning.models import (
    Plan,
    PlanTask,
    PlanTaskEvent,
    PlanTaskRequirement,
    TaskDependency,
)

if TYPE_CHECKING:
    from pcs.db.models import Project
from pcs.planning.types import (
    DEFAULT_LEASE_SECONDS,
    EVENT_CANCELLED,
    EVENT_CLAIMED,
    EVENT_COMPLETED,
    EVENT_CREATED,
    EVENT_DEPENDENCY_ADDED,
    EVENT_HEARTBEAT,
    EVENT_RECLAIMED,
    EVENT_RELEASED,
    EVENT_STATUS_CHANGED,
    EVENT_UPDATED,
    GOAL_MAX_CHARS,
    LOCAL_TASK_ID_MAX_CHARS,
    MAX_LEASE_SECONDS,
    MAX_REASON_CHARS,
    MIN_LEASE_SECONDS,
    OBJECTIVE_MAX_CHARS,
    PLAN_STATUS_ACTIVE,
    PLAN_STATUS_ARCHIVED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUSES,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CLAIMED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_IN_REVIEW,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    TITLE_MAX_CHARS,
    ClaimResult,
    DependencySpec,
    PlanTaskView,
    PlanView,
    TaskEventView,
    TaskSpec,
)

__all__ = [
    "activate_plan",
    "add_plan_task",
    "add_task_dependency",
    "archive_plan",
    "claim_task",
    "complete_plan",
    "complete_task",
    "create_plan",
    "create_plan_with_tasks",
    "get_plan",
    "get_task_history",
    "heartbeat_task",
    "list_plans",
    "list_ready_tasks",
    "release_task",
    "set_task_status",
    "update_plan",
    "update_plan_task",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _resolve_project(session: AsyncSession, project: str) -> Project:
    from pcs.context.service import resolve_project

    return await resolve_project(session, project)


def _validate_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned or len(cleaned) > TITLE_MAX_CHARS:
        raise PlanningValidationError(f"Title must be between 1 and {TITLE_MAX_CHARS} characters.")
    return cleaned


def _validate_goal(goal: str) -> str:
    cleaned = goal.strip()
    if not cleaned or len(cleaned) > GOAL_MAX_CHARS:
        raise PlanningValidationError(f"Goal must be between 1 and {GOAL_MAX_CHARS} characters.")
    return cleaned


def _validate_objective(objective: str) -> str:
    cleaned = objective.strip()
    if not cleaned or len(cleaned) > OBJECTIVE_MAX_CHARS:
        raise PlanningValidationError(
            f"Objective must be between 1 and {OBJECTIVE_MAX_CHARS} characters."
        )
    return cleaned


def _validate_local_task_id(local_id: str) -> str:
    cleaned = local_id.strip()
    if not cleaned or len(cleaned) > LOCAL_TASK_ID_MAX_CHARS:
        raise PlanningValidationError(
            f"local_task_id must be between 1 and {LOCAL_TASK_ID_MAX_CHARS} characters."
        )
    return cleaned


def _as_task_view(
    task: PlanTask,
    dependencies: list[str] | None = None,
    requirement_ids: list[str] | None = None,
) -> PlanTaskView:
    return PlanTaskView(
        id=task.id,
        plan_id=task.plan_id,
        project_id=task.project_id,
        local_task_id=task.local_task_id,
        title=task.title,
        objective=task.objective,
        acceptance_criteria=(
            list(task.acceptance_criteria) if isinstance(task.acceptance_criteria, list) else []
        ),
        linked_files=(list(task.linked_files) if isinstance(task.linked_files, list) else []),
        priority=task.priority,
        status=task.status,
        claimed_by=task.claimed_by,
        lease_expires_at=task.lease_expires_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        dependencies=dependencies or [],
        requirement_ids=requirement_ids or [],
    )


def _as_plan_view(plan: Plan, tasks: list[PlanTaskView] | None = None) -> PlanView:
    return PlanView(
        id=plan.id,
        project_id=plan.project_id,
        title=plan.title,
        goal=plan.goal,
        status=plan.status,
        author=plan.author,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        tasks=tasks or [],
    )


async def _append_task_event(
    session: AsyncSession,
    *,
    project_id: str,
    plan_id: str,
    task_id: str,
    event_type: str,
    actor: str,
    old_status: str | None,
    new_status: str | None,
    payload: dict[str, Any],
) -> PlanTaskEvent:
    # Ensure tokens/secrets are never stored in payload
    safe_payload = {
        k: v for k, v in payload.items() if k not in ("token", "claim_token", "claim_token_hash")
    }
    event = PlanTaskEvent(
        project_id=project_id,
        plan_id=plan_id,
        task_id=task_id,
        event_type=event_type,
        actor=actor,
        old_status=old_status,
        new_status=new_status,
        payload=safe_payload,
        created_at=_now(),
    )
    session.add(event)
    return event


async def _validate_requirement_entries(
    session: AsyncSession, project: Project, req_ids: Sequence[str]
) -> None:
    """Ensure all requirement_ids exist in the project and belong to section 'requirements'."""
    if not req_ids:
        return
    from pcs.db.models import ContextEntry

    unique_ids = list(set(req_ids))
    result = await session.execute(
        select(ContextEntry).where(
            ContextEntry.id.in_(unique_ids),
            ContextEntry.project_id == project.id,
        )
    )
    entries = {e.id: e for e in result.scalars().all()}
    for rid in unique_ids:
        if rid not in entries:
            raise PlanningValidationError(
                f"Requirement {rid!r} not found in project {project.name!r}."
            )
        entry = entries[rid]
        if entry.section != "requirements":
            raise PlanningValidationError(
                f"Entry {rid!r} is in section {entry.section!r}, not 'requirements'."
            )


def _check_acyclic(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> None:
    """Kahn's algorithm: edges are (task_id, depends_on_task_id).

    depends_on_task_id must complete before task_id can run.
    Graph edge: depends_on -> task.
    """
    for task_id, dep_id in edges:
        if task_id == dep_id:
            raise DependencyCycleError(f"Self-dependency detected on task {task_id!r}.")

    adj: dict[str, list[str]] = {node: [] for node in nodes}
    in_degree: dict[str, int] = {node: 0 for node in nodes}

    for task_id, dep_id in edges:
        if task_id in adj and dep_id in adj:
            adj[dep_id].append(task_id)
            in_degree[task_id] += 1

    queue = deque([node for node in nodes if in_degree[node] == 0])
    visited_count = 0

    while queue:
        u = queue.popleft()
        visited_count += 1
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if visited_count < len(nodes):
        raise DependencyCycleError("Dependency cycle detected in plan task graph.")


# ---------------------------------------------------------------------------
# 1. create_plan
# ---------------------------------------------------------------------------
async def create_plan(
    session: AsyncSession,
    project: str,
    title: str,
    goal: str,
    author: str = "agent",
) -> PlanView:
    """Create an empty plan in 'draft' status (FR43, D18)."""
    clean_title = _validate_title(title)
    clean_goal = _validate_goal(goal)
    proj = await _resolve_project(session, project)

    plan = Plan(
        project_id=proj.id,
        title=clean_title,
        goal=clean_goal,
        status=PLAN_STATUS_DRAFT,
        author=author,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(plan)
    await session.flush()
    return _as_plan_view(plan, [])


# ---------------------------------------------------------------------------
# 2. create_plan_with_tasks
# ---------------------------------------------------------------------------
async def create_plan_with_tasks(
    session: AsyncSession,
    project: str,
    title: str,
    goal: str,
    tasks: list[TaskSpec],
    dependencies: list[DependencySpec] | None = None,
    author: str = "agent",
) -> PlanView:
    """Atomically create a plan with tasks, dependencies, and requirements (FR43-FR45, D18, D23)."""
    clean_title = _validate_title(title)
    clean_goal = _validate_goal(goal)
    proj = await _resolve_project(session, project)

    if not tasks:
        raise PlanningValidationError("At least one task is required.")

    # Validate local_task_ids uniqueness
    seen_local_ids: set[str] = set()
    for t in tasks:
        local_id = _validate_local_task_id(t.local_task_id)
        if local_id in seen_local_ids:
            raise PlanningValidationError(f"Duplicate local_task_id {local_id!r} in task list.")
        seen_local_ids.add(local_id)
        _validate_title(t.title)
        _validate_objective(t.objective)

    # Validate dependencies and check for cycles
    dep_specs = dependencies or []
    edges: list[tuple[str, str]] = []
    for d in dep_specs:
        if d.task_local_id not in seen_local_ids:
            raise PlanningValidationError(
                f"Unknown task {d.task_local_id!r} referenced in dependencies."
            )
        if d.depends_on_local_id not in seen_local_ids:
            raise PlanningValidationError(
                f"Unknown prerequisite {d.depends_on_local_id!r} referenced in dependencies."
            )
        edges.append((d.task_local_id, d.depends_on_local_id))

    _check_acyclic(list(seen_local_ids), edges)

    # Validate requirement IDs
    all_req_ids = [rid for t in tasks for rid in t.requirement_ids]
    await _validate_requirement_entries(session, proj, all_req_ids)

    # Create Plan
    now = _now()
    plan = Plan(
        project_id=proj.id,
        title=clean_title,
        goal=clean_goal,
        status=PLAN_STATUS_DRAFT,
        author=author,
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    await session.flush()

    # Create Tasks
    task_rows: dict[str, PlanTask] = {}
    for t in tasks:
        pt = PlanTask(
            plan_id=plan.id,
            project_id=proj.id,
            local_task_id=t.local_task_id.strip(),
            title=t.title.strip(),
            objective=t.objective.strip(),
            acceptance_criteria=list(t.acceptance_criteria),
            linked_files=list(t.linked_files),
            priority=t.priority,
            status=TASK_STATUS_PENDING,
            created_at=now,
            updated_at=now,
        )
        session.add(pt)
        await session.flush()
        task_rows[t.local_task_id.strip()] = pt

        # Audit event
        await _append_task_event(
            session,
            project_id=proj.id,
            plan_id=plan.id,
            task_id=pt.id,
            event_type=EVENT_CREATED,
            actor=author,
            old_status=None,
            new_status=TASK_STATUS_PENDING,
            payload={
                "local_task_id": pt.local_task_id,
                "title": pt.title,
                "priority": pt.priority,
            },
        )

        # Requirement links
        for rid in set(t.requirement_ids):
            ptr = PlanTaskRequirement(
                project_id=proj.id,
                plan_task_id=pt.id,
                requirement_id=rid,
                requirement_section="requirements",
                created_at=now,
            )
            session.add(ptr)

    # Create Dependencies
    task_deps_map: dict[str, list[str]] = {pt.id: [] for pt in task_rows.values()}
    for d in dep_specs:
        t_id = task_rows[d.task_local_id.strip()].id
        dep_id = task_rows[d.depends_on_local_id.strip()].id
        dep_row = TaskDependency(
            project_id=proj.id,
            plan_id=plan.id,
            task_id=t_id,
            depends_on_task_id=dep_id,
            created_at=now,
        )
        session.add(dep_row)
        task_deps_map[t_id].append(dep_id)

        await _append_task_event(
            session,
            project_id=proj.id,
            plan_id=plan.id,
            task_id=t_id,
            event_type=EVENT_DEPENDENCY_ADDED,
            actor=author,
            old_status=TASK_STATUS_PENDING,
            new_status=TASK_STATUS_PENDING,
            payload={
                "depends_on_task_id": dep_id,
                "depends_on_local_id": d.depends_on_local_id.strip(),
            },
        )

    await session.flush()

    task_views = [
        _as_task_view(
            task_rows[t.local_task_id.strip()],
            dependencies=task_deps_map[task_rows[t.local_task_id.strip()].id],
            requirement_ids=t.requirement_ids,
        )
        for t in tasks
    ]
    return _as_plan_view(plan, task_views)


# ---------------------------------------------------------------------------
# 3. get_plan
# ---------------------------------------------------------------------------
async def get_plan(
    session: AsyncSession,
    project: str,
    plan_id: str,
) -> PlanView:
    """Retrieve a plan with all its tasks, dependencies, and requirements (FR43)."""
    proj = await _resolve_project(session, project)
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.project_id == proj.id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    # Load tasks
    tasks_res = await session.execute(
        select(PlanTask)
        .where(PlanTask.plan_id == plan.id, PlanTask.project_id == proj.id)
        .order_by(PlanTask.priority.desc(), PlanTask.created_at.asc())
    )
    tasks = list(tasks_res.scalars().all())

    # Load dependencies
    deps_res = await session.execute(
        select(TaskDependency).where(
            TaskDependency.plan_id == plan.id,
            TaskDependency.project_id == proj.id,
        )
    )
    deps = list(deps_res.scalars().all())
    dep_map: dict[str, list[str]] = {t.id: [] for t in tasks}
    for d in deps:
        if d.task_id in dep_map:
            dep_map[d.task_id].append(d.depends_on_task_id)

    # Load requirements
    req_map: dict[str, list[str]] = {t.id: [] for t in tasks}
    if tasks:
        req_res = await session.execute(
            select(PlanTaskRequirement).where(
                PlanTaskRequirement.project_id == proj.id,
                PlanTaskRequirement.plan_task_id.in_([t.id for t in tasks]),
            )
        )
        for r in req_res.scalars().all():
            if r.plan_task_id in req_map:
                req_map[r.plan_task_id].append(r.requirement_id)

    task_views = [_as_task_view(t, dep_map.get(t.id, []), req_map.get(t.id, [])) for t in tasks]
    return _as_plan_view(plan, task_views)


# ---------------------------------------------------------------------------
# 4. list_plans
# ---------------------------------------------------------------------------
async def list_plans(
    session: AsyncSession,
    project: str,
    status: str | None = None,
) -> list[PlanView]:
    """List plans in a project, optionally filtered by status (FR43)."""
    proj = await _resolve_project(session, project)
    stmt = select(Plan).where(Plan.project_id == proj.id)
    if status is not None:
        if status not in PLAN_STATUSES:
            raise PlanningValidationError(f"Invalid plan status filter {status!r}.")
        stmt = stmt.where(Plan.status == status)
    stmt = stmt.order_by(Plan.created_at.desc())

    result = await session.execute(stmt)
    plans = list(result.scalars().all())

    plan_views: list[PlanView] = []
    for p in plans:
        # Load tasks for each plan
        tasks_res = await session.execute(
            select(PlanTask)
            .where(PlanTask.plan_id == p.id, PlanTask.project_id == proj.id)
            .order_by(PlanTask.priority.desc(), PlanTask.created_at.asc())
        )
        tasks = list(tasks_res.scalars().all())
        task_views = [_as_task_view(t) for t in tasks]
        plan_views.append(_as_plan_view(p, task_views))

    return plan_views


# ---------------------------------------------------------------------------
# 5. update_plan
# ---------------------------------------------------------------------------
async def update_plan(
    session: AsyncSession,
    project: str,
    plan_id: str,
    title: str | None = None,
    goal: str | None = None,
) -> PlanView:
    """Update title and/or goal of an active or draft plan (FR43)."""
    proj = await _resolve_project(session, project)
    result = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot update plan in status '{plan.status}'.")

    if title is None and goal is None:
        raise PlanningValidationError("At least one of title or goal must be provided.")

    if title is not None:
        plan.title = _validate_title(title)
    if goal is not None:
        plan.goal = _validate_goal(goal)

    plan.updated_at = _now()
    await session.flush()
    return await get_plan(session, project, plan_id)


# ---------------------------------------------------------------------------
# 6. archive_plan
# ---------------------------------------------------------------------------
async def archive_plan(
    session: AsyncSession,
    project: str,
    plan_id: str,
    actor: str = "agent",
) -> PlanView:
    """Archive a plan; sole administrative exception revoking all active leases (FR43, D20)."""
    proj = await _resolve_project(session, project)
    result = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status == PLAN_STATUS_ARCHIVED:
        return await get_plan(session, project, plan_id)

    # Load all tasks in plan with row locks
    tasks_res = await session.execute(
        select(PlanTask)
        .where(PlanTask.plan_id == plan.id, PlanTask.project_id == proj.id)
        .with_for_update()
    )
    tasks = list(tasks_res.scalars().all())

    now = _now()
    for t in tasks:
        # Revoke any active lease
        t.claim_token_hash = None
        t.claimed_by = None
        t.lease_expires_at = None

        if t.status != TASK_STATUS_COMPLETED:
            old_status = t.status
            t.status = TASK_STATUS_CANCELLED
            t.updated_at = now
            await _append_task_event(
                session,
                project_id=proj.id,
                plan_id=plan.id,
                task_id=t.id,
                event_type=EVENT_CANCELLED,
                actor=actor,
                old_status=old_status,
                new_status=TASK_STATUS_CANCELLED,
                payload={"reason": "plan_archived"},
            )

    plan.status = PLAN_STATUS_ARCHIVED
    plan.updated_at = now
    await session.flush()
    return await get_plan(session, project, plan_id)


# ---------------------------------------------------------------------------
# 7. activate_plan
# ---------------------------------------------------------------------------
async def activate_plan(
    session: AsyncSession,
    project: str,
    plan_id: str,
    actor: str = "agent",
) -> PlanView:
    """Activate a draft plan; transitions root tasks (zero dependencies) to ready (FR43, FR44)."""
    proj = await _resolve_project(session, project)
    result = await session.execute(
        select(Plan).where(Plan.id == plan_id, Plan.project_id == proj.id).with_for_update()
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot activate plan in terminal status '{plan.status}'.")

    if plan.status == PLAN_STATUS_ACTIVE:
        return await get_plan(session, project, plan_id)

    now = _now()
    plan.status = PLAN_STATUS_ACTIVE
    plan.updated_at = now

    # Load tasks and dependencies
    tasks_res = await session.execute(
        select(PlanTask)
        .where(PlanTask.plan_id == plan.id, PlanTask.project_id == proj.id)
        .with_for_update()
    )
    tasks = list(tasks_res.scalars().all())

    deps_res = await session.execute(
        select(TaskDependency).where(
            TaskDependency.plan_id == plan.id,
            TaskDependency.project_id == proj.id,
        )
    )
    deps = list(deps_res.scalars().all())
    tasks_with_deps = {d.task_id for d in deps}

    for t in tasks:
        if t.id not in tasks_with_deps and t.status == TASK_STATUS_PENDING:
            old_status = t.status
            t.status = TASK_STATUS_READY
            t.updated_at = now
            await _append_task_event(
                session,
                project_id=proj.id,
                plan_id=plan.id,
                task_id=t.id,
                event_type=EVENT_STATUS_CHANGED,
                actor=actor,
                old_status=old_status,
                new_status=TASK_STATUS_READY,
                payload={"reason": "plan_activated"},
            )

    await session.flush()
    return await get_plan(session, project, plan_id)


# ---------------------------------------------------------------------------
# 8. add_plan_task
# ---------------------------------------------------------------------------
async def add_plan_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    local_task_id: str,
    title: str,
    objective: str,
    acceptance_criteria: list[str] | None = None,
    linked_files: list[str] | None = None,
    requirement_ids: list[str] | None = None,
    priority: int = 0,
    actor: str = "agent",
) -> PlanTaskView:
    """Add an individual task to an existing draft or active plan (FR44)."""
    clean_local_id = _validate_local_task_id(local_task_id)
    clean_title = _validate_title(title)
    clean_objective = _validate_objective(objective)
    proj = await _resolve_project(session, project)

    # Serialize mutation with plan lifecycle: acquire row lock and re-check status (FR43, D20)
    lock_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = lock_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot add tasks to plan in status '{plan.status}'.")

    # Check local_task_id uniqueness in plan
    existing_res = await session.execute(
        select(PlanTask).where(
            PlanTask.plan_id == plan.id,
            PlanTask.local_task_id == clean_local_id,
        )
    )
    if existing_res.scalar_one_or_none() is not None:
        raise PlanningValidationError(
            f"Task with local_task_id {clean_local_id!r} already exists in plan."
        )

    # Validate requirements
    req_ids = requirement_ids or []
    await _validate_requirement_entries(session, proj, req_ids)

    # Initial status: ready if plan is active (zero dependencies initially), pending if draft
    initial_status = TASK_STATUS_READY if plan.status == PLAN_STATUS_ACTIVE else TASK_STATUS_PENDING
    now = _now()
    pt = PlanTask(
        plan_id=plan.id,
        project_id=proj.id,
        local_task_id=clean_local_id,
        title=clean_title,
        objective=clean_objective,
        acceptance_criteria=list(acceptance_criteria or []),
        linked_files=list(linked_files or []),
        priority=priority,
        status=initial_status,
        created_at=now,
        updated_at=now,
    )
    session.add(pt)
    await session.flush()

    for rid in set(req_ids):
        ptr = PlanTaskRequirement(
            project_id=proj.id,
            plan_task_id=pt.id,
            requirement_id=rid,
            requirement_section="requirements",
            created_at=now,
        )
        session.add(ptr)

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=pt.id,
        event_type=EVENT_CREATED,
        actor=actor,
        old_status=None,
        new_status=initial_status,
        payload={
            "local_task_id": pt.local_task_id,
            "title": pt.title,
            "priority": pt.priority,
        },
    )

    await session.flush()
    return _as_task_view(pt, dependencies=[], requirement_ids=req_ids)


# ---------------------------------------------------------------------------
# 9. update_plan_task
# ---------------------------------------------------------------------------
async def update_plan_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    title: str | None = None,
    objective: str | None = None,
    acceptance_criteria: list[str] | None = None,
    linked_files: list[str] | None = None,
    requirement_ids: list[str] | None = None,
    priority: int | None = None,
    claim_token: str | None = None,
    actor: str = "agent",
) -> PlanTaskView:
    """Update task fields; active leases strictly require valid claim token (FR44, D20)."""
    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot update tasks in plan in status '{plan.status}'.")

    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    now = _now()
    # Active lease token check (no operator bypass)
    if (
        task.lease_expires_at is not None
        and task.lease_expires_at > now
        and task.claim_token_hash is not None
    ):
        if not claim_token or _hash_token(claim_token) != task.claim_token_hash:
            raise StaleClaimTokenError("Task has an active lease; valid claim_token is required.")
    elif task.lease_expires_at is not None and task.lease_expires_at <= now and claim_token:
        raise StaleClaimTokenError("Claim lease has expired.")

    # Validate non-empty patch
    patch_fields = [title, objective, acceptance_criteria, linked_files, requirement_ids, priority]
    if all(f is None for f in patch_fields):
        raise PlanningValidationError("At least one field must be provided for update.")

    updated_fields: list[str] = []
    if title is not None:
        task.title = _validate_title(title)
        updated_fields.append("title")
    if objective is not None:
        task.objective = _validate_objective(objective)
        updated_fields.append("objective")
    if acceptance_criteria is not None:
        task.acceptance_criteria = list(acceptance_criteria)
        updated_fields.append("acceptance_criteria")
    if linked_files is not None:
        task.linked_files = list(linked_files)
        updated_fields.append("linked_files")
    if priority is not None:
        task.priority = priority
        updated_fields.append("priority")
    if requirement_ids is not None:
        await _validate_requirement_entries(session, proj, requirement_ids)
        # Delete old requirement links
        await session.execute(
            delete(PlanTaskRequirement).where(
                PlanTaskRequirement.plan_task_id == task.id,
                PlanTaskRequirement.project_id == proj.id,
            )
        )
        for rid in set(requirement_ids):
            session.add(
                PlanTaskRequirement(
                    project_id=proj.id,
                    plan_task_id=task.id,
                    requirement_id=rid,
                    requirement_section="requirements",
                    created_at=now,
                )
            )
        updated_fields.append("requirement_ids")

    task.updated_at = now
    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=EVENT_UPDATED,
        actor=actor,
        old_status=task.status,
        new_status=task.status,
        payload={"updated_fields": updated_fields},
    )

    await session.flush()

    # Load dependencies and requirement IDs for view
    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    deps = list(deps_res.scalars().all())

    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    reqs = list(reqs_res.scalars().all())

    return _as_task_view(task, dependencies=deps, requirement_ids=reqs)


# ---------------------------------------------------------------------------
# 10. add_task_dependency
# ---------------------------------------------------------------------------
async def add_task_dependency(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    depends_on_task_id: str,
    claim_token: str | None = None,
    actor: str = "agent",
) -> None:
    """Add a prerequisite dependency edge between two tasks in the same plan.

    Cites FR45, INV-PLAN-1, INV-PLAN-3.
    """
    if task_id == depends_on_task_id:
        raise DependencyCycleError(
            f"Self-dependency detected: task {task_id!r} cannot depend on itself."
        )

    proj = await _resolve_project(session, project)
    # Serialize dependency authoring per plan to prevent concurrent cycle race (INV-PLAN-1)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot add dependency in plan in status '{plan.status}'.")

    # Verify target task exists and lock for lease check
    t_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = t_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    if task.status not in (TASK_STATUS_PENDING, TASK_STATUS_READY):
        raise InvalidStateTransitionError(
            f"Cannot add dependency to task in status '{task.status}'. "
            "Target task must be in 'pending' or 'ready' status."
        )

    dep_res = await session.execute(
        select(PlanTask).where(
            PlanTask.id == depends_on_task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
    )
    dep_task = dep_res.scalar_one_or_none()
    if dep_task is None:
        raise TaskNotFoundError(depends_on_task_id, plan_id, proj.name)

    # Check if already exists
    existing = await session.execute(
        select(TaskDependency).where(
            TaskDependency.task_id == task.id,
            TaskDependency.depends_on_task_id == dep_task.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    # Check for cycles
    all_tasks_res = await session.execute(
        select(PlanTask.id).where(
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
    )
    all_node_ids = list(all_tasks_res.scalars().all())

    all_deps_res = await session.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
            TaskDependency.plan_id == plan.id,
            TaskDependency.project_id == proj.id,
        )
    )
    existing_edges = [(r[0], r[1]) for r in all_deps_res.all()]
    existing_edges.append((task.id, dep_task.id))

    _check_acyclic(all_node_ids, existing_edges)

    now = _now()
    dep_row = TaskDependency(
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        depends_on_task_id=dep_task.id,
        created_at=now,
    )
    session.add(dep_row)

    # If the task was ready, but the prerequisite is not completed, revert to pending
    if task.status == TASK_STATUS_READY and dep_task.status != TASK_STATUS_COMPLETED:
        old_status = task.status
        task.status = TASK_STATUS_PENDING
        task.updated_at = now
        await _append_task_event(
            session,
            project_id=proj.id,
            plan_id=plan.id,
            task_id=task.id,
            event_type=EVENT_STATUS_CHANGED,
            actor=actor,
            old_status=old_status,
            new_status=TASK_STATUS_PENDING,
            payload={
                "reason": "prerequisite_added",
                "depends_on_task_id": dep_task.id,
            },
        )

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=EVENT_DEPENDENCY_ADDED,
        actor=actor,
        old_status=task.status,
        new_status=task.status,
        payload={
            "depends_on_task_id": dep_task.id,
            "depends_on_local_id": dep_task.local_task_id,
        },
    )

    await session.flush()


# ---------------------------------------------------------------------------
# 11. list_ready_tasks
# ---------------------------------------------------------------------------
async def list_ready_tasks(
    session: AsyncSession,
    project: str,
    plan_id: str | None = None,
) -> list[PlanTaskView]:
    """Discover ready tasks across all active plans or scoped to one plan (FR46, D18).

    Canonical Predicate:
    1. plan.status == 'active' in the project.
    2. task.status NOT IN ('completed', 'cancelled', 'blocked').
    3. All prerequisites in DAG are 'completed'.
    4. Task is 'ready' OR has expired lease (status in ('claimed', 'in_progress',
       'in_review') AND lease_expires_at <= now()).
    """
    proj = await _resolve_project(session, project)
    now = _now()

    # Load active plans
    plan_query = select(Plan.id).where(
        Plan.project_id == proj.id,
        Plan.status == PLAN_STATUS_ACTIVE,
    )
    if plan_id is not None:
        plan_query = plan_query.where(Plan.id == plan_id)

    plan_ids_res = await session.execute(plan_query)
    active_plan_ids = list(plan_ids_res.scalars().all())
    if not active_plan_ids:
        return []

    # Load candidate tasks
    tasks_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.project_id == proj.id,
            PlanTask.plan_id.in_(active_plan_ids),
            PlanTask.status.not_in(
                [
                    TASK_STATUS_COMPLETED,
                    TASK_STATUS_CANCELLED,
                    TASK_STATUS_BLOCKED,
                ]
            ),
        )
        .order_by(PlanTask.priority.desc(), PlanTask.created_at.asc())
    )
    candidates = list(tasks_res.scalars().all())
    if not candidates:
        return []

    candidate_ids = [t.id for t in candidates]

    # Load dependencies for candidates
    deps_res = await session.execute(
        select(TaskDependency).where(
            TaskDependency.project_id == proj.id,
            TaskDependency.task_id.in_(candidate_ids),
        )
    )
    deps = list(deps_res.scalars().all())

    # Map task -> prerequisite task IDs
    prereq_ids_by_task: dict[str, list[str]] = {cid: [] for cid in candidate_ids}
    all_prereq_ids: set[str] = set()
    for d in deps:
        prereq_ids_by_task[d.task_id].append(d.depends_on_task_id)
        all_prereq_ids.add(d.depends_on_task_id)

    # Check status of prerequisites
    prereq_statuses: dict[str, str] = {}
    if all_prereq_ids:
        prereq_res = await session.execute(
            select(PlanTask.id, PlanTask.status).where(PlanTask.id.in_(list(all_prereq_ids)))
        )
        prereq_statuses = {row[0]: row[1] for row in prereq_res.all()}

    # Load requirements for views
    reqs_res = await session.execute(
        select(PlanTaskRequirement).where(
            PlanTaskRequirement.project_id == proj.id,
            PlanTaskRequirement.plan_task_id.in_(candidate_ids),
        )
    )
    req_map: dict[str, list[str]] = {cid: [] for cid in candidate_ids}
    for r in reqs_res.scalars().all():
        req_map[r.plan_task_id].append(r.requirement_id)

    ready_tasks: list[PlanTaskView] = []
    for t in candidates:
        # Check all prerequisites completed
        prereqs = prereq_ids_by_task.get(t.id, [])
        all_completed = all(prereq_statuses.get(pid) == TASK_STATUS_COMPLETED for pid in prereqs)
        if not all_completed:
            continue

        # Check lease condition:
        # status == 'ready' OR (status in ('claimed', 'in_progress', 'in_review')
        # AND lease_expires_at <= now())
        is_ready = t.status == TASK_STATUS_READY
        is_expired_lease = (
            t.status in (TASK_STATUS_CLAIMED, TASK_STATUS_IN_PROGRESS, TASK_STATUS_IN_REVIEW)
            and t.lease_expires_at is not None
            and t.lease_expires_at <= now
        )

        if is_ready or is_expired_lease:
            ready_tasks.append(
                _as_task_view(t, dependencies=prereqs, requirement_ids=req_map.get(t.id, []))
            )

    return ready_tasks


# ---------------------------------------------------------------------------
# 12. claim_task
# ---------------------------------------------------------------------------
async def claim_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    claimed_by: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> ClaimResult:
    """Atomically claim or reclaim a ready/expired task with an ephemeral token (FR47, D20)."""
    if lease_seconds < MIN_LEASE_SECONDS or lease_seconds > MAX_LEASE_SECONDS:
        raise PlanningValidationError(
            f"lease_seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}."
        )

    clean_claimant = claimed_by.strip()
    if not clean_claimant:
        raise PlanningValidationError("claimed_by must be non-empty.")

    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Cannot claim task in non-active plan status '{plan.status}'.")
    if plan.status != PLAN_STATUS_ACTIVE:
        raise PlanNotActiveError(f"Cannot claim task in non-active plan status '{plan.status}'.")

    # Row lock task
    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    if task.status in TERMINAL_TASK_STATUSES:
        raise InvalidStateTransitionError(f"Cannot claim task in terminal status '{task.status}'.")

    if task.status == TASK_STATUS_BLOCKED:
        raise InvalidStateTransitionError(
            "Cannot claim blocked task. It must be set to ready first."
        )

    if task.status == TASK_STATUS_PENDING:
        raise InvalidStateTransitionError(
            "Cannot claim task in status 'pending'. "
            "It must be in 'ready' status or have an expired lease."
        )

    # Check prerequisite dependencies
    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    prereq_ids = list(deps_res.scalars().all())
    if prereq_ids:
        uncompleted_res = await session.execute(
            select(PlanTask.id).where(
                PlanTask.id.in_(prereq_ids),
                PlanTask.status != TASK_STATUS_COMPLETED,
            )
        )
        if uncompleted_res.scalar_one_or_none() is not None:
            raise InvalidStateTransitionError(
                "Cannot claim task; not all prerequisite dependencies are completed."
            )

    now = _now()
    is_reclaim = False
    old_claimant = task.claimed_by

    if task.status in (TASK_STATUS_CLAIMED, TASK_STATUS_IN_PROGRESS, TASK_STATUS_IN_REVIEW):
        # Active lease check: lease_expires_at > now() -> conflict
        if task.lease_expires_at is not None and task.lease_expires_at > now:
            raise ClaimConflictError(
                f"Task {task.id!r} is actively claimed by {task.claimed_by!r} "
                f"until {task.lease_expires_at.isoformat()}."
            )
        # lease_expires_at <= now -> eligible for reclaim
        is_reclaim = True
    elif task.status == TASK_STATUS_READY:
        is_reclaim = False
    else:
        raise InvalidStateTransitionError(
            f"Cannot claim task in status '{task.status}'. "
            f"Only tasks in 'ready' status or with expired leases can be claimed."
        )

    # Issue ephemeral token
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = now + timedelta(seconds=lease_seconds)

    old_status = task.status
    task.status = TASK_STATUS_CLAIMED
    task.claim_token_hash = token_hash
    task.claimed_by = clean_claimant
    task.lease_expires_at = expires_at
    task.updated_at = now

    if is_reclaim:
        await _append_task_event(
            session,
            project_id=proj.id,
            plan_id=plan.id,
            task_id=task.id,
            event_type=EVENT_RECLAIMED,
            actor=clean_claimant,
            old_status=old_status,
            new_status=TASK_STATUS_CLAIMED,
            payload={
                "claimed_by": clean_claimant,
                "prior_claimant": old_claimant,
                "lease_seconds": lease_seconds,
            },
        )
    else:
        await _append_task_event(
            session,
            project_id=proj.id,
            plan_id=plan.id,
            task_id=task.id,
            event_type=EVENT_CLAIMED,
            actor=clean_claimant,
            old_status=old_status,
            new_status=TASK_STATUS_CLAIMED,
            payload={
                "claimed_by": clean_claimant,
                "lease_seconds": lease_seconds,
            },
        )

    await session.flush()

    # Load requirements for view
    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    reqs = list(reqs_res.scalars().all())

    task_view = _as_task_view(task, dependencies=prereq_ids, requirement_ids=reqs)
    return ClaimResult(task=task_view, claim_token=raw_token)


# ---------------------------------------------------------------------------
# 13. heartbeat_task
# ---------------------------------------------------------------------------
async def heartbeat_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    claim_token: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> PlanTaskView:
    """Extend lease expiration while strictly preserving current persisted status (FR47, D20)."""
    if lease_seconds < MIN_LEASE_SECONDS or lease_seconds > MAX_LEASE_SECONDS:
        raise PlanningValidationError(
            f"lease_seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}."
        )

    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Plan is {plan.status}.")

    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    now = _now()
    if task.claim_token_hash is None or task.lease_expires_at is None:
        raise StaleClaimTokenError("Task does not hold an active lease.")

    # Exact boundary check: lease_expires_at <= now is treated as expired
    if task.lease_expires_at <= now:
        raise StaleClaimTokenError("Claim lease has expired.")

    if _hash_token(claim_token) != task.claim_token_hash:
        raise StaleClaimTokenError("Invalid claim token.")

    # Extend lease expiration, preserving exact status (never mutate claimed -> in_progress)
    new_expiry = now + timedelta(seconds=lease_seconds)
    task.lease_expires_at = new_expiry
    task.updated_at = now

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=EVENT_HEARTBEAT,
        actor=task.claimed_by or "unknown",
        old_status=task.status,
        new_status=task.status,
        payload={
            "lease_seconds": lease_seconds,
            "new_expiry": new_expiry.isoformat(),
        },
    )

    await session.flush()

    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    return _as_task_view(
        task,
        dependencies=list(deps_res.scalars().all()),
        requirement_ids=list(reqs_res.scalars().all()),
    )


# ---------------------------------------------------------------------------
# 14. release_task
# ---------------------------------------------------------------------------
async def release_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    claim_token: str,
    reason: str = "voluntary_release",
) -> PlanTaskView:
    """Voluntarily release a claimed/in_progress task back to ready (FR47, D20)."""
    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Plan is {plan.status}.")

    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    now = _now()
    if task.claim_token_hash is None or task.lease_expires_at is None:
        raise StaleClaimTokenError("Task does not hold an active lease.")

    if task.lease_expires_at <= now:
        raise StaleClaimTokenError("Claim lease has expired.")

    if _hash_token(claim_token) != task.claim_token_hash:
        raise StaleClaimTokenError("Invalid claim token.")

    if task.status not in (TASK_STATUS_CLAIMED, TASK_STATUS_IN_PROGRESS):
        raise InvalidStateTransitionError(f"Cannot release task in status '{task.status}'.")

    actor = task.claimed_by or "unknown"
    old_status = task.status
    task.status = TASK_STATUS_READY
    task.claim_token_hash = None
    task.claimed_by = None
    task.lease_expires_at = None
    task.updated_at = now

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=EVENT_RELEASED,
        actor=actor,
        old_status=old_status,
        new_status=TASK_STATUS_READY,
        payload={"reason": reason[:MAX_REASON_CHARS]},
    )

    await session.flush()

    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    return _as_task_view(
        task,
        dependencies=list(deps_res.scalars().all()),
        requirement_ids=list(reqs_res.scalars().all()),
    )


# ---------------------------------------------------------------------------
# 15. set_task_status
# ---------------------------------------------------------------------------
async def set_task_status(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    status: str,
    claim_token: str | None = None,
    reason: str | None = None,
    actor: str = "agent",
) -> PlanTaskView:
    """Transition task status, enforcing lease rules and state machine (FR44, FR47, D20)."""
    if status not in TASK_STATUSES:
        raise PlanningValidationError(f"Invalid task status {status!r}.")

    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Plan is {plan.status}.")

    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    now = _now()
    has_active_lease = (
        task.lease_expires_at is not None
        and task.lease_expires_at > now
        and task.claim_token_hash is not None
    )
    has_expired_lease = task.lease_expires_at is not None and task.lease_expires_at <= now

    # Active lease strictly requires valid claim token (no operator bypass)
    if has_active_lease:
        if not claim_token:
            raise ClaimConflictError(
                "Task has an active lease; valid claim_token is strictly required."
            )
        if _hash_token(claim_token) != task.claim_token_hash:
            raise StaleClaimTokenError("Invalid claim token.")
    elif has_expired_lease:
        if claim_token:
            raise StaleClaimTokenError("Claim lease has expired.")

    # Validate state transitions
    old_status = task.status
    if status == old_status:
        pass  # No-op status change
    elif status == TASK_STATUS_IN_PROGRESS:
        if old_status != TASK_STATUS_CLAIMED:
            raise InvalidStateTransitionError(
                f"Cannot transition to 'in_progress' from '{old_status}'."
            )
    elif status == TASK_STATUS_IN_REVIEW:
        if old_status != TASK_STATUS_IN_PROGRESS:
            raise InvalidStateTransitionError(
                f"Cannot transition to 'in_review' from '{old_status}'."
            )
    elif status == TASK_STATUS_BLOCKED:
        if old_status not in (TASK_STATUS_CLAIMED, TASK_STATUS_IN_PROGRESS):
            raise InvalidStateTransitionError(f"Cannot block task from status '{old_status}'.")
        # Blocked task revokes active lease
        task.claim_token_hash = None
        task.claimed_by = None
        task.lease_expires_at = None
    elif status == TASK_STATUS_READY:
        if old_status != TASK_STATUS_BLOCKED:
            raise InvalidStateTransitionError(
                f"Cannot set status to 'ready' from '{old_status}'. Use release_task instead."
            )
    elif status == TASK_STATUS_CANCELLED:
        if old_status in TERMINAL_TASK_STATUSES:
            raise InvalidStateTransitionError(
                f"Cannot cancel task in terminal status '{old_status}'."
            )
        # Cancellation revokes lease
        task.claim_token_hash = None
        task.claimed_by = None
        task.lease_expires_at = None
    elif status == TASK_STATUS_COMPLETED:
        # Re-route to complete_task logic to ensure downstream tasks unlock
        return await complete_task(
            session,
            project,
            plan_id,
            task_id,
            claim_token=claim_token,
            actor=actor,
        )
    else:
        raise InvalidStateTransitionError(
            f"Transition from '{old_status}' to '{status}' is not permitted."
        )

    task.status = status
    task.updated_at = now

    event_type = EVENT_CANCELLED if status == TASK_STATUS_CANCELLED else EVENT_STATUS_CHANGED
    payload: dict[str, Any] = {
        "reason": (reason or "")[:MAX_REASON_CHARS],
        "old_status": old_status,
        "new_status": status,
    }
    if status == TASK_STATUS_CANCELLED:
        payload = {"reason": (reason or "cancelled")[:MAX_REASON_CHARS]}

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=event_type,
        actor=actor,
        old_status=old_status,
        new_status=status,
        payload=payload,
    )

    await session.flush()

    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    return _as_task_view(
        task,
        dependencies=list(deps_res.scalars().all()),
        requirement_ids=list(reqs_res.scalars().all()),
    )


# ---------------------------------------------------------------------------
# 16. complete_task
# ---------------------------------------------------------------------------
async def complete_task(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
    claim_token: str | None = None,
    actor: str = "agent",
) -> PlanTaskView:
    """Complete a task, revoke lease, unlock downstream tasks.

    Never mutates requirements (FR44, FR47, D4, INV-PLAN-2).
    """
    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        raise PlanNotActiveError(f"Plan is {plan.status}.")

    task_res = await session.execute(
        select(PlanTask)
        .where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
        .with_for_update()
    )
    task = task_res.scalar_one_or_none()
    if task is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    if task.status not in (TASK_STATUS_CLAIMED, TASK_STATUS_IN_PROGRESS, TASK_STATUS_IN_REVIEW):
        raise InvalidStateTransitionError(f"Cannot complete task in status '{task.status}'.")

    now = _now()
    has_active_lease = (
        task.lease_expires_at is not None
        and task.lease_expires_at > now
        and task.claim_token_hash is not None
    )
    has_expired_lease = task.lease_expires_at is not None and task.lease_expires_at <= now

    if has_active_lease:
        if not claim_token:
            raise ClaimConflictError(
                "Task has an active lease; claim_token is required to complete."
            )
        if _hash_token(claim_token) != task.claim_token_hash:
            raise StaleClaimTokenError("Invalid claim token.")
    elif has_expired_lease:
        if claim_token:
            raise StaleClaimTokenError("Claim lease has expired.")
        # Tokenless completion allowed ONLY IF status is in_review (single-user model)
        if task.status != TASK_STATUS_IN_REVIEW:
            raise StaleClaimTokenError(
                "Claim lease has expired; task must be reclaimed before completion."
            )

    old_status = task.status
    task.status = TASK_STATUS_COMPLETED
    task.claim_token_hash = None
    task.lease_expires_at = None
    task.claimed_by = actor
    task.updated_at = now

    await _append_task_event(
        session,
        project_id=proj.id,
        plan_id=plan.id,
        task_id=task.id,
        event_type=EVENT_COMPLETED,
        actor=actor,
        old_status=old_status,
        new_status=TASK_STATUS_COMPLETED,
        payload={"completed_by": actor},
    )

    # Downstream task unlocking: find pending tasks that depend on task.id
    downstream_deps_res = await session.execute(
        select(TaskDependency.task_id).where(
            TaskDependency.depends_on_task_id == task.id,
            TaskDependency.plan_id == plan.id,
            TaskDependency.project_id == proj.id,
        )
    )
    downstream_task_ids = list(set(downstream_deps_res.scalars().all()))

    if downstream_task_ids:
        # Load pending downstream tasks
        ds_tasks_res = await session.execute(
            select(PlanTask)
            .where(
                PlanTask.id.in_(downstream_task_ids),
                PlanTask.status == TASK_STATUS_PENDING,
            )
            .with_for_update()
        )
        pending_downstream = list(ds_tasks_res.scalars().all())

        for dt in pending_downstream:
            # Check if all dt's prerequisites are completed
            dt_deps_res = await session.execute(
                select(TaskDependency.depends_on_task_id).where(
                    TaskDependency.task_id == dt.id,
                    TaskDependency.plan_id == plan.id,
                    TaskDependency.project_id == proj.id,
                )
            )
            dt_prereqs = list(dt_deps_res.scalars().all())

            # Check if any prerequisite is NOT completed
            uncompleted_res = await session.execute(
                select(PlanTask.id).where(
                    PlanTask.id.in_(dt_prereqs),
                    PlanTask.status != TASK_STATUS_COMPLETED,
                )
            )
            if uncompleted_res.scalar_one_or_none() is None:
                # All prerequisites complete! Transition pending -> ready
                dt_old = dt.status
                dt.status = TASK_STATUS_READY
                dt.updated_at = now
                await _append_task_event(
                    session,
                    project_id=proj.id,
                    plan_id=plan.id,
                    task_id=dt.id,
                    event_type=EVENT_STATUS_CHANGED,
                    actor=actor,
                    old_status=dt_old,
                    new_status=TASK_STATUS_READY,
                    payload={
                        "reason": "prerequisites_completed",
                        "completed_dependency_id": task.id,
                    },
                )

    await session.flush()

    deps_res = await session.execute(
        select(TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id == task.id,
            TaskDependency.project_id == proj.id,
        )
    )
    reqs_res = await session.execute(
        select(PlanTaskRequirement.requirement_id).where(
            PlanTaskRequirement.plan_task_id == task.id,
            PlanTaskRequirement.project_id == proj.id,
        )
    )
    return _as_task_view(
        task,
        dependencies=list(deps_res.scalars().all()),
        requirement_ids=list(reqs_res.scalars().all()),
    )


# ---------------------------------------------------------------------------
# 17. complete_plan
# ---------------------------------------------------------------------------
async def complete_plan(
    session: AsyncSession,
    project: str,
    plan_id: str,
    actor: str = "agent",
) -> PlanView:
    """Mark an active plan completed if all tasks are terminal.

    Never mutates requirements (FR43, D4, INV-PLAN-2).
    """
    proj = await _resolve_project(session, project)
    plan_res = await session.execute(
        select(Plan)
        .where(Plan.id == plan_id, Plan.project_id == proj.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    plan = plan_res.scalar_one_or_none()
    if plan is None:
        raise PlanNotFoundError(plan_id, proj.name)

    if plan.status in (PLAN_STATUS_COMPLETED, PLAN_STATUS_ARCHIVED):
        return await get_plan(session, project, plan_id)

    if plan.status != PLAN_STATUS_ACTIVE:
        raise PlanNotActiveError(f"Cannot complete plan in status '{plan.status}'.")

    # Verify all tasks are terminal
    tasks_res = await session.execute(
        select(PlanTask.status).where(
            PlanTask.plan_id == plan.id,
            PlanTask.project_id == proj.id,
        )
    )
    statuses = list(tasks_res.scalars().all())
    non_terminal = [s for s in statuses if s not in TERMINAL_TASK_STATUSES]
    if non_terminal:
        raise PlanningValidationError(
            f"Cannot complete plan; {len(non_terminal)} task(s) are not completed or cancelled."
        )

    plan.status = PLAN_STATUS_COMPLETED
    plan.updated_at = _now()
    await session.flush()
    return await get_plan(session, project, plan_id)


# ---------------------------------------------------------------------------
# 18. get_task_history
# ---------------------------------------------------------------------------
async def get_task_history(
    session: AsyncSession,
    project: str,
    plan_id: str,
    task_id: str,
) -> list[TaskEventView]:
    """Retrieve immutable chronological audit event history for a task (FR48, D21, INV-PLAN-4)."""
    proj = await _resolve_project(session, project)
    t_res = await session.execute(
        select(PlanTask.id).where(
            PlanTask.id == task_id,
            PlanTask.plan_id == plan_id,
            PlanTask.project_id == proj.id,
        )
    )
    if t_res.scalar_one_or_none() is None:
        raise TaskNotFoundError(task_id, plan_id, proj.name)

    events_res = await session.execute(
        select(PlanTaskEvent)
        .where(
            PlanTaskEvent.task_id == task_id,
            PlanTaskEvent.plan_id == plan_id,
            PlanTaskEvent.project_id == proj.id,
        )
        .order_by(PlanTaskEvent.created_at.asc(), PlanTaskEvent.id.asc())
    )
    events = list(events_res.scalars().all())

    return [
        TaskEventView(
            id=e.id,
            project_id=e.project_id,
            plan_id=e.plan_id,
            task_id=e.task_id,
            event_type=e.event_type,
            actor=e.actor,
            old_status=e.old_status,
            new_status=e.new_status,
            payload=e.payload if isinstance(e.payload, dict) else {},
            created_at=e.created_at,
        )
        for e in events
    ]
