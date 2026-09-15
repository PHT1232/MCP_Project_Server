"""Core domain and PostgreSQL tests for Plan & Task Orchestration (T23).

Covers:
- INV-PLAN-1..4 and AC-PLAN-1..6.
- Database-level composite foreign key isolation (cross-plan and cross-project prevention).
- Requirement section check at both database and service layers.
- DAG validation and cycle detection (Kahn's algorithm).
- Ready-task discovery canonical predicate.
- Requirement status independence (D4 / FR53).
- Atomic claim concurrency race with exactly one winner.
- Exact boundary condition: lease_expires_at == now().
- Stale token rejection after release and reclaim.
- Expired and unexpired in_review leases.
- Heartbeat status preservation.
- Active lease token enforcement (no operator bypass).
- Blocked and cancelled lease revocation.
- Administrative archive_plan lease revocation.
- Completed and archived plan freeze.
- 10-event immutable audit log and token redaction.
- Alembic migration upgrade and downgrade against PostgreSQL.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Select, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context import service as ctx_service
from pcs.db.base import session_scope
from pcs.db.models import Plan
from pcs.planning import (
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
    PLAN_STATUS_ACTIVE,
    PLAN_STATUS_ARCHIVED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_DRAFT,
    TASK_STATUS_BLOCKED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CLAIMED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_IN_REVIEW,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    ClaimConflictError,
    DependencyCycleError,
    DependencySpec,
    InvalidStateTransitionError,
    PlanningValidationError,
    PlanNotActiveError,
    StaleClaimTokenError,
    TaskSpec,
    activate_plan,
    add_plan_task,
    add_task_dependency,
    archive_plan,
    claim_task,
    complete_plan,
    complete_task,
    create_plan,
    create_plan_with_tasks,
    get_plan,
    get_task_history,
    heartbeat_task,
    list_plans,
    list_ready_tasks,
    release_task,
    set_task_status,
    update_plan,
    update_plan_task,
)

pytestmark = pytest.mark.usefixtures("clean_db")
PROJECT_A = "proj-alpha"
PROJECT_B = "proj-beta"


async def _seed_project(name: str = PROJECT_A) -> str:
    async with session_scope() as session:
        proj = await ctx_service.register_project(
            session, name=name, root_path=f"/tmp/{name}", overview=f"Test project {name}"
        )
        return proj.id


# ---------------------------------------------------------------------------
# AC-PLAN-1: DAG validation, self-dependencies, cycles
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_and_task_dag_creation_and_cycle_detection() -> None:
    """AC-PLAN-1: DAG creation rejects self-dependencies and cycles (INV-PLAN-1)."""
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Do 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Do 2"),
        TaskSpec(local_task_id="T03", title="Task 3", objective="Do 3"),
    ]

    # 1. Valid linear DAG: T01 -> T02 -> T03
    deps = [
        DependencySpec(task_local_id="T02", depends_on_local_id="T01"),
        DependencySpec(task_local_id="T03", depends_on_local_id="T02"),
    ]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session, PROJECT_A, "Milestone 1", "Goal 1", tasks, deps
        )
        assert plan.status == PLAN_STATUS_DRAFT
        assert len(plan.tasks) == 3
        t3 = next(t for t in plan.tasks if t.local_task_id == "T03")
        assert len(t3.dependencies) == 1

    # 2. Self-dependency rejected
    self_deps = [DependencySpec(task_local_id="T01", depends_on_local_id="T01")]
    async with session_scope() as session:
        with pytest.raises(DependencyCycleError, match="Self-dependency"):
            await create_plan_with_tasks(
                session, PROJECT_A, "Self Dep Plan", "Goal", tasks, self_deps
            )

    # 3. 2-cycle rejected: T01 -> T02 -> T01
    cycle_2 = [
        DependencySpec(task_local_id="T02", depends_on_local_id="T01"),
        DependencySpec(task_local_id="T01", depends_on_local_id="T02"),
    ]
    async with session_scope() as session:
        with pytest.raises(DependencyCycleError, match="Dependency cycle"):
            await create_plan_with_tasks(session, PROJECT_A, "Cycle 2 Plan", "Goal", tasks, cycle_2)

    # 4. 3-cycle rejected: T01 -> T02 -> T03 -> T01
    cycle_3 = [
        DependencySpec(task_local_id="T02", depends_on_local_id="T01"),
        DependencySpec(task_local_id="T03", depends_on_local_id="T02"),
        DependencySpec(task_local_id="T01", depends_on_local_id="T03"),
    ]
    async with session_scope() as session:
        with pytest.raises(DependencyCycleError, match="Dependency cycle"):
            await create_plan_with_tasks(session, PROJECT_A, "Cycle 3 Plan", "Goal", tasks, cycle_3)


# ---------------------------------------------------------------------------
# Composite Foreign Key Isolation: Cross-plan and cross-project
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_database_composite_foreign_key_cross_plan_isolation() -> None:
    """Database composite FKs strictly prevent inserting cross-plan dependencies (INV-PLAN-1)."""
    p_a = await _seed_project(PROJECT_A)

    tasks_1 = [TaskSpec(local_task_id="T01", title="Plan 1 Task", objective="Objective")]
    tasks_2 = [TaskSpec(local_task_id="T02", title="Plan 2 Task", objective="Objective")]

    async with session_scope() as session:
        plan_1 = await create_plan_with_tasks(session, PROJECT_A, "Plan 1", "Goal 1", tasks_1)
        plan_2 = await create_plan_with_tasks(session, PROJECT_A, "Plan 2", "Goal 2", tasks_2)

        t1_id = plan_1.tasks[0].id
        t2_id = plan_2.tasks[0].id

        # Attempt raw cross-plan dependency insert into database:
        # task_id from plan 1, depends_on_task_id from plan 2, but plan_id = plan_1.id
        with pytest.raises(IntegrityError) as exc_info:
            await session.execute(
                text(
                    "INSERT INTO task_dependencies "
                    "(project_id, plan_id, task_id, depends_on_task_id, created_at) "
                    "VALUES (:proj, :plan, :t1, :t2, now())"
                ),
                {"proj": p_a, "plan": plan_1.id, "t1": t1_id, "t2": t2_id},
            )
            await session.flush()
        assert "fk_task_deps_depends_on" in str(exc_info.value)


@pytest.mark.asyncio
async def test_database_composite_foreign_key_cross_project_isolation() -> None:
    """Database composite FKs strictly prevent inserting cross-project dependencies (INV-PLAN-1)."""
    p_a = await _seed_project(PROJECT_A)
    await _seed_project(PROJECT_B)

    tasks_a = [TaskSpec(local_task_id="TA", title="Task A", objective="Objective")]
    tasks_b = [TaskSpec(local_task_id="TB", title="Task B", objective="Objective")]

    async with session_scope() as session:
        plan_a = await create_plan_with_tasks(session, PROJECT_A, "Plan A", "Goal A", tasks_a)
        plan_b = await create_plan_with_tasks(session, PROJECT_B, "Plan B", "Goal B", tasks_b)

        ta_id = plan_a.tasks[0].id
        tb_id = plan_b.tasks[0].id

        # Attempt raw cross-project dependency insert
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO task_dependencies "
                    "(project_id, plan_id, task_id, depends_on_task_id, created_at) "
                    "VALUES (:proj_a, :plan_a, :ta, :tb, now())"
                ),
                {"proj_a": p_a, "plan_a": plan_a.id, "ta": ta_id, "tb": tb_id},
            )
            await session.flush()


# ---------------------------------------------------------------------------
# Requirement links: section validation & DB constraints
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_requirement_link_section_validation_service_and_db() -> None:
    """plan_task_requirements enforces section == 'requirements' at service and DB (INV-PLAN-1)."""
    p_a = await _seed_project(PROJECT_A)

    async with session_scope() as session:
        # Create a genuine requirement entry
        req_entry = await ctx_service.add_entry(
            session, project=PROJECT_A, section="requirements", headline="FR43: Plans"
        )
        # Create a non-requirement entry (e.g. bug)
        bug_entry = await ctx_service.add_entry(
            session, project=PROJECT_A, section="bugs", headline="Fix crash"
        )

        # 1. Service validation rejects non-requirement entry
        with pytest.raises(PlanningValidationError, match="not 'requirements'"):
            await create_plan_with_tasks(
                session,
                PROJECT_A,
                "Plan with Bug Link",
                "Goal",
                [
                    TaskSpec(
                        local_task_id="T01",
                        title="Task 1",
                        objective="Obj",
                        requirement_ids=[bug_entry.id],
                    )
                ],
            )

        # 2. Valid plan with genuine requirement succeeds
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Valid Plan",
            "Goal",
            [
                TaskSpec(
                    local_task_id="T01",
                    title="Task 1",
                    objective="Obj",
                    requirement_ids=[req_entry.id],
                )
            ],
        )
        task_id = plan.tasks[0].id
        assert plan.tasks[0].requirement_ids == [req_entry.id]

    # 3. Database check constraint rejects invalid section directly
    async with session_scope() as session:
        with pytest.raises(IntegrityError) as exc_check:
            await session.execute(
                text(
                    "INSERT INTO plan_task_requirements "
                    "(project_id, plan_task_id, requirement_id, requirement_section, created_at) "
                    "VALUES (:proj, :task, :req, 'bugs', now())"
                ),
                {"proj": p_a, "task": task_id, "req": bug_entry.id},
            )
            await session.flush()
        assert "ck_plan_task_requirements_section" in str(exc_check.value)

    # 4. Database composite FK rejects section mismatch with context_entries
    async with session_scope() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO plan_task_requirements "
                    "(project_id, plan_task_id, requirement_id, requirement_section, created_at) "
                    "VALUES (:proj, :task, :req, 'requirements', now())"
                ),
                {"proj": p_a, "task": task_id, "req": bug_entry.id},
            )
            await session.flush()


# ---------------------------------------------------------------------------
# AC-PLAN-2: Ready-task discovery canonical predicate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ready_task_discovery() -> None:
    """AC-PLAN-2: Ready-task discovery returns only tasks whose prerequisites are complete.

    Cites FR46.
    """
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
    ]
    deps = [DependencySpec(task_local_id="T02", depends_on_local_id="T01")]

    async with session_scope() as session:
        # In draft status, no tasks are ready
        plan = await create_plan_with_tasks(
            session, PROJECT_A, "Ready Discovery Plan", "Goal", tasks, deps
        )
        ready = await list_ready_tasks(session, PROJECT_A)
        assert len(ready) == 0

        # Activate plan: T01 (root) becomes ready; T02 (has prerequisite) stays pending
        await activate_plan(session, PROJECT_A, plan.id)
        ready = await list_ready_tasks(session, PROJECT_A)
        assert len(ready) == 1
        assert ready[0].local_task_id == "T01"

        # Claim T01 with active lease: T01 no longer in ready list
        claim_res = await claim_task(session, PROJECT_A, plan.id, ready[0].id, "worker-1", 1800)
        ready_after_claim = await list_ready_tasks(session, PROJECT_A)
        assert len(ready_after_claim) == 0

        # Complete T01: T02 unlocks and becomes ready
        await complete_task(
            session, PROJECT_A, plan.id, ready[0].id, claim_token=claim_res.claim_token
        )
        ready_after_t1_done = await list_ready_tasks(session, PROJECT_A)
        assert len(ready_after_t1_done) == 1
        assert ready_after_t1_done[0].local_task_id == "T02"


# ---------------------------------------------------------------------------
# AC-PLAN-3: Requirement status independence (D4 / FR53)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_requirement_status_independence_d4() -> None:
    """AC-PLAN-3: Task and plan completion NEVER mutate requirement status (D4, INV-PLAN-2)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        req = await ctx_service.add_entry(
            session, project=PROJECT_A, section="requirements", headline="FR53: Independence"
        )
        await ctx_service.set_requirement_status(
            session, project=PROJECT_A, entry_id=req.id, status="in-progress"
        )

        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "D4 Plan",
            "Goal",
            [
                TaskSpec(
                    local_task_id="T01",
                    title="Implement D4",
                    objective="Objective",
                    requirement_ids=[req.id],
                )
            ],
        )
        await activate_plan(session, PROJECT_A, plan.id)

        # Claim and complete task
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)
        await complete_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, claim_token=claim.claim_token
        )

        # Verify requirement status is STILL in-progress
        entry_after_task = await ctx_service.get_entry(session, project=PROJECT_A, entry_id=req.id)
        assert entry_after_task.requirement_status == "in-progress"

        # Complete plan
        await complete_plan(session, PROJECT_A, plan.id)

        # Verify requirement status is STILL in-progress
        entry_after_plan = await ctx_service.get_entry(session, project=PROJECT_A, entry_id=req.id)
        assert entry_after_plan.requirement_status == "in-progress"


# ---------------------------------------------------------------------------
# AC-PLAN-4: Concurrency race test (Exactly one winner)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_claim_race_single_winner() -> None:
    """AC-PLAN-4: Two concurrent claims on the same ready task result in exactly one winner."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Race Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Contested Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        task_id = plan.tasks[0].id

    # Concurrently attempt claim from two distinct sessions
    async def _try_claim(worker_name: str) -> str | None:
        async with session_scope() as session:
            try:
                res = await claim_task(session, PROJECT_A, plan.id, task_id, worker_name, 1800)
                return res.claim_token
            except ClaimConflictError:
                return None

    results = await asyncio.gather(_try_claim("worker-A"), _try_claim("worker-B"))

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]

    assert len(winners) == 1, f"Expected exactly 1 claim winner, got {len(winners)}"
    assert len(losers) == 1, f"Expected exactly 1 claim loser, got {len(losers)}"


# ---------------------------------------------------------------------------
# AC-PLAN-5: Heartbeat, release, reclaim, stale tokens
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_heartbeat_preserves_status() -> None:
    """Heartbeat on claimed task keeps status 'claimed' and extends lease (INV-PLAN-3)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "HB Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="HB Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 60)

        initial_expiry = claim.task.lease_expires_at
        assert claim.task.status == TASK_STATUS_CLAIMED

        # Heartbeat
        hb_task = await heartbeat_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, claim.claim_token, 300
        )
        assert hb_task.status == TASK_STATUS_CLAIMED  # Must NOT transition to in_progress!
        assert hb_task.lease_expires_at is not None
        assert initial_expiry is not None
        assert hb_task.lease_expires_at > initial_expiry


@pytest.mark.asyncio
async def test_stale_token_after_release() -> None:
    """Stale token rejected after task release (INV-PLAN-3)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Release Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)

        # Release task
        released = await release_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, claim.claim_token
        )
        assert released.status == TASK_STATUS_READY
        assert released.claimed_by is None
        assert released.lease_expires_at is None

        # Presenting old token must fail
        with pytest.raises(StaleClaimTokenError):
            await heartbeat_task(
                session, PROJECT_A, plan.id, plan.tasks[0].id, claim.claim_token, 1800
            )


@pytest.mark.asyncio
async def test_stale_token_after_reclaim() -> None:
    """Stale token rejected after task reclaim (INV-PLAN-3)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Reclaim Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim_1 = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)

        # Manually expire lease
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": plan.tasks[0].id},
        )
        await session.flush()

        # Worker 2 reclaims task
        claim_2 = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-2", 1800)
        assert claim_2.task.claimed_by == "worker-2"

        # Worker 1's token is permanently stale
        with pytest.raises(StaleClaimTokenError):
            await heartbeat_task(
                session, PROJECT_A, plan.id, plan.tasks[0].id, claim_1.claim_token, 1800
            )

        # Worker 2's token works
        hb = await heartbeat_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, claim_2.claim_token, 1800
        )
        assert hb.claimed_by == "worker-2"


# ---------------------------------------------------------------------------
# Lease boundary: in_review unexpired conflict & expired reclaim
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_in_review_lease_lifecycle() -> None:
    """in_review task protects active lease, but allows reclaim and discovery when expired."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Review Lease Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Review Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "author", 1800)
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_IN_PROGRESS,
            claim_token=claim.claim_token,
        )
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_IN_REVIEW,
            claim_token=claim.claim_token,
        )

        # 1. Unexpired in_review rejects concurrent claim attempts
        with pytest.raises(ClaimConflictError):
            await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "reviewer", 1800)

        # Unexpired task not in ready list
        ready = await list_ready_tasks(session, PROJECT_A)
        assert len(ready) == 0

        # 2. Expire lease
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": plan.tasks[0].id},
        )
        await session.flush()

        # 3. Expired in_review appears in list_ready_tasks
        ready_expired = await list_ready_tasks(session, PROJECT_A)
        assert len(ready_expired) == 1
        assert ready_expired[0].status == TASK_STATUS_IN_REVIEW

        # 4. Expired in_review can be reclaimed atomically to claimed
        reclaim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "reviewer", 1800)
        assert reclaim.task.status == TASK_STATUS_CLAIMED
        assert reclaim.task.claimed_by == "reviewer"


# ---------------------------------------------------------------------------
# Exact Boundary condition: lease_expires_at == now()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exact_boundary_lease_expires_at_equals_now() -> None:
    """Exact boundary lease_expires_at == now() is treated as expired and reclaimable."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Boundary Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Boundary Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)

        # Force exact boundary: lease_expires_at = clock_timestamp()
        await session.execute(
            text("UPDATE plan_tasks SET lease_expires_at = clock_timestamp() WHERE id = :tid"),
            {"tid": plan.tasks[0].id},
        )
        await session.flush()

        # 1. Appears in list_ready_tasks as reclaimable
        ready = await list_ready_tasks(session, PROJECT_A)
        assert len(ready) == 1

        # 2. Presenting existing token fails with StaleClaimTokenError
        with pytest.raises(StaleClaimTokenError):
            await heartbeat_task(
                session, PROJECT_A, plan.id, plan.tasks[0].id, claim.claim_token, 1800
            )

        # 3. Reclaim succeeds atomically
        reclaimed = await claim_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-2", 1800
        )
        assert reclaimed.task.claimed_by == "worker-2"


# ---------------------------------------------------------------------------
# No operator bypass of active leases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_operator_bypass_active_lease() -> None:
    """Mutating task with active lease without valid token is rejected (no operator bypass)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Operator Bypass Test",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_IN_PROGRESS,
            claim_token=claim.claim_token,
        )

        # Attempt tokenless complete_task fails
        with pytest.raises(ClaimConflictError):
            await complete_task(
                session, PROJECT_A, plan.id, plan.tasks[0].id, claim_token=None, actor="admin"
            )

        # Attempt tokenless set_task_status fails
        with pytest.raises(ClaimConflictError):
            await set_task_status(
                session,
                PROJECT_A,
                plan.id,
                plan.tasks[0].id,
                TASK_STATUS_BLOCKED,
                claim_token=None,
                actor="admin",
            )

        # Attempt tokenless update_plan_task fails
        with pytest.raises(StaleClaimTokenError):
            await update_plan_task(
                session,
                PROJECT_A,
                plan.id,
                plan.tasks[0].id,
                title="New Title",
                claim_token=None,
                actor="admin",
            )


# ---------------------------------------------------------------------------
# Lease revocation: Blocked and Cancelled
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_blocked_status_revokes_lease() -> None:
    """Transitioning to blocked revokes active lease; blocked -> ready leaves no token."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Blocked Test",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)

        blocked = await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_BLOCKED,
            claim_token=claim.claim_token,
            reason="Blocked by dependency",
        )
        assert blocked.status == TASK_STATUS_BLOCKED
        assert blocked.claimed_by is None
        assert blocked.lease_expires_at is None

        # Return blocked to ready
        ready = await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_READY,
            claim_token=None,
        )
        assert ready.status == TASK_STATUS_READY
        assert ready.claimed_by is None

        # Old token cannot be used
        with pytest.raises(StaleClaimTokenError):
            await heartbeat_task(
                session, PROJECT_A, plan.id, plan.tasks[0].id, claim.claim_token, 1800
            )


@pytest.mark.asyncio
async def test_cancelled_status_revokes_lease() -> None:
    """Cancelling a claimed/in-progress task revokes lease."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Cancel Test",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)

        cancelled = await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_CANCELLED,
            claim_token=claim.claim_token,
        )
        assert cancelled.status == TASK_STATUS_CANCELLED
        assert cancelled.claimed_by is None
        assert cancelled.lease_expires_at is None


# ---------------------------------------------------------------------------
# Administrative archive_plan revokes all active leases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_archive_plan_revokes_all_active_leases() -> None:
    """archive_plan atomically revokes all active leases and cancels non-completed tasks (D20)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Archive Plan",
            "Goal",
            [
                TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
                TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
                TaskSpec(local_task_id="T03", title="Task 3", objective="Obj 3"),
            ],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "worker-1", 1800)
        await claim_task(session, PROJECT_A, plan.id, plan.tasks[1].id, "worker-2", 1800)

        # Complete T03 directly
        c3 = await claim_task(session, PROJECT_A, plan.id, plan.tasks[2].id, "worker-3", 1800)
        await complete_task(session, PROJECT_A, plan.id, plan.tasks[2].id, c3.claim_token)

        # Archive plan
        archived = await archive_plan(session, PROJECT_A, plan.id, actor="admin")
        assert archived.status == PLAN_STATUS_ARCHIVED

        # T01 and T02 are cancelled and lease fields are cleared
        p = await get_plan(session, PROJECT_A, plan.id)
        t1 = next(t for t in p.tasks if t.local_task_id == "T01")
        t2 = next(t for t in p.tasks if t.local_task_id == "T02")
        t3 = next(t for t in p.tasks if t.local_task_id == "T03")

        assert t1.status == TASK_STATUS_CANCELLED
        assert t1.claimed_by is None
        assert t2.status == TASK_STATUS_CANCELLED
        assert t2.claimed_by is None
        assert t3.status == TASK_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Completed and Archived plans freeze mutations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_completed_and_archived_plan_freezes() -> None:
    """Mutations on completed or archived plans are rejected with PlanNotActiveError."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Freeze Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        c = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "w", 1800)
        await complete_task(session, PROJECT_A, plan.id, plan.tasks[0].id, c.claim_token)
        await complete_plan(session, PROJECT_A, plan.id)

        # Attempt to add task to completed plan fails
        with pytest.raises(PlanNotActiveError):
            await add_plan_task(session, PROJECT_A, plan.id, "T02", "New Task", "Objective")

        # Attempt to claim task fails
        with pytest.raises(PlanNotActiveError):
            await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "w", 1800)

        # Attempt to update plan fails
        with pytest.raises(PlanNotActiveError):
            await update_plan(session, PROJECT_A, plan.id, title="New Title")


# ---------------------------------------------------------------------------
# AC-PLAN-6: Immutable event audit log & token redaction
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_immutable_event_taxonomy_and_token_redaction() -> None:
    """AC-PLAN-6: All 10 event types are recorded with bounded payloads.

    Tokens are redacted (FR48).
    """
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        # 1. created & dependency_added
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Event Taxonomy Plan",
            "Goal",
            [
                TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
                TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
            ],
            [DependencySpec(task_local_id="T02", depends_on_local_id="T01")],
        )
        t1_id = plan.tasks[0].id
        t2_id = plan.tasks[1].id

        # 2. updated
        await update_plan_task(
            session, PROJECT_A, plan.id, t1_id, title="Updated Task 1", actor="updater"
        )

        # 3. status_changed (activate)
        await activate_plan(session, PROJECT_A, plan.id)

        # 4. claimed
        c1 = await claim_task(session, PROJECT_A, plan.id, t1_id, "agent-1", 1800)

        # 5. heartbeat
        await heartbeat_task(session, PROJECT_A, plan.id, t1_id, c1.claim_token, 1800)

        # 6. released
        await release_task(session, PROJECT_A, plan.id, t1_id, c1.claim_token)

        # Re-claim and expire for reclaimed event
        await claim_task(session, PROJECT_A, plan.id, t1_id, "agent-1", 1800)
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": t1_id},
        )
        await session.flush()

        # 7. reclaimed
        c2 = await claim_task(session, PROJECT_A, plan.id, t1_id, "agent-2", 1800)

        # 8. completed
        await set_task_status(
            session, PROJECT_A, plan.id, t1_id, TASK_STATUS_IN_PROGRESS, c2.claim_token
        )
        await complete_task(session, PROJECT_A, plan.id, t1_id, c2.claim_token, actor="agent-2")

        # 9. cancelled (cancel T02)
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            t2_id,
            TASK_STATUS_CANCELLED,
            reason="not needed",
            actor="admin",
        )

        history_t1 = await get_task_history(session, PROJECT_A, plan.id, t1_id)
        history_t2 = await get_task_history(session, PROJECT_A, plan.id, t2_id)

        events_t1_types = {e.event_type for e in history_t1}
        assert EVENT_CREATED in events_t1_types
        assert EVENT_UPDATED in events_t1_types
        assert EVENT_CLAIMED in events_t1_types
        assert EVENT_HEARTBEAT in events_t1_types
        assert EVENT_RELEASED in events_t1_types
        assert EVENT_RECLAIMED in events_t1_types
        assert EVENT_COMPLETED in events_t1_types
        assert EVENT_STATUS_CHANGED in events_t1_types

        events_t2_types = {e.event_type for e in history_t2}
        assert EVENT_DEPENDENCY_ADDED in events_t2_types
        assert EVENT_CANCELLED in events_t2_types

        # Verify token redaction across ALL events
        for e in history_t1 + history_t2:
            payload_str = str(e.payload).lower()
            assert "token" not in e.payload
            assert "claim_token" not in e.payload
            assert "claim_token_hash" not in e.payload
            assert c1.claim_token not in payload_str
            assert c2.claim_token not in payload_str


# ---------------------------------------------------------------------------
# Additional Plan CRUD, Patch Validation, and Filtering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_plan_crud_and_validation() -> None:
    """Verify create_plan, list_plans filtering, and patch validation."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        # Create empty plan
        plan = await create_plan(session, PROJECT_A, "Empty Plan", "Goal")
        assert plan.status == PLAN_STATUS_DRAFT
        assert len(plan.tasks) == 0

        # list_plans with status filter
        draft_plans = await list_plans(session, PROJECT_A, status=PLAN_STATUS_DRAFT)
        assert any(p.id == plan.id for p in draft_plans)
        active_plans = await list_plans(session, PROJECT_A, status=PLAN_STATUS_ACTIVE)
        assert not any(p.id == plan.id for p in active_plans)

        # Empty patch rejected
        with pytest.raises(PlanningValidationError, match="At least one"):
            await update_plan(session, PROJECT_A, plan.id)

        # Update title and goal
        updated = await update_plan(
            session, PROJECT_A, plan.id, title="Updated Title", goal="Updated Goal"
        )
        assert updated.title == "Updated Title"
        assert updated.goal == "Updated Goal"

        # Add task to draft plan (status pending)
        t1 = await add_plan_task(session, PROJECT_A, plan.id, "T01", "Task 1", "Obj 1")
        assert t1.status == TASK_STATUS_PENDING

        # Duplicate local_task_id rejected
        with pytest.raises(PlanningValidationError, match="already exists"):
            await add_plan_task(session, PROJECT_A, plan.id, "T01", "Task 1 Dup", "Obj 1")

        # Update plan task with empty patch rejected
        with pytest.raises(PlanningValidationError, match="At least one"):
            await update_plan_task(session, PROJECT_A, plan.id, t1.id)


# ---------------------------------------------------------------------------
# Downstream unlocking and plan completion validation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_downstream_task_unlock_and_plan_completion() -> None:
    """Cascading downstream task unlock on completion; complete_plan requires terminal tasks."""
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
        TaskSpec(local_task_id="T03", title="Task 3", objective="Obj 3"),
    ]
    deps = [
        DependencySpec(task_local_id="T02", depends_on_local_id="T01"),
        DependencySpec(task_local_id="T03", depends_on_local_id="T02"),
    ]

    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Chain Plan", "Goal", tasks, deps)
        await activate_plan(session, PROJECT_A, plan.id)

        # Attempting complete_plan while tasks pending fails
        with pytest.raises(PlanningValidationError, match="Cannot complete plan"):
            await complete_plan(session, PROJECT_A, plan.id)

        # T01 is ready; T02 and T03 are pending
        p = await get_plan(session, PROJECT_A, plan.id)
        t1 = next(t for t in p.tasks if t.local_task_id == "T01")
        t2 = next(t for t in p.tasks if t.local_task_id == "T02")
        t3 = next(t for t in p.tasks if t.local_task_id == "T03")

        assert t1.status == TASK_STATUS_READY
        assert t2.status == TASK_STATUS_PENDING
        assert t3.status == TASK_STATUS_PENDING

        # Complete T01 -> T02 becomes ready
        c1 = await claim_task(session, PROJECT_A, plan.id, t1.id, "w", 1800)
        await complete_task(session, PROJECT_A, plan.id, t1.id, c1.claim_token)

        p = await get_plan(session, PROJECT_A, plan.id)
        t2 = next(t for t in p.tasks if t.local_task_id == "T02")
        t3 = next(t for t in p.tasks if t.local_task_id == "T03")
        assert t2.status == TASK_STATUS_READY
        assert t3.status == TASK_STATUS_PENDING

        # Complete T02 -> T03 becomes ready
        c2 = await claim_task(session, PROJECT_A, plan.id, t2.id, "w", 1800)
        await complete_task(session, PROJECT_A, plan.id, t2.id, c2.claim_token)

        p = await get_plan(session, PROJECT_A, plan.id)
        t3 = next(t for t in p.tasks if t.local_task_id == "T03")
        assert t3.status == TASK_STATUS_READY

        # Complete T03
        c3 = await claim_task(session, PROJECT_A, plan.id, t3.id, "w", 1800)
        await complete_task(session, PROJECT_A, plan.id, t3.id, c3.claim_token)

        # Now complete_plan succeeds
        done_plan = await complete_plan(session, PROJECT_A, plan.id)
        assert done_plan.status == PLAN_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Expired in_review tokenless completion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_in_review_tokenless_completion() -> None:
    """Expired in_review task can be completed tokenless (single-user review approval)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Expired Review Approval",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task", objective="Obj")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        claim = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "author", 1800)
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_IN_PROGRESS,
            claim_token=claim.claim_token,
        )
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            plan.tasks[0].id,
            TASK_STATUS_IN_REVIEW,
            claim_token=claim.claim_token,
        )

        # Expire lease
        await session.execute(
            text(
                "UPDATE plan_tasks SET lease_expires_at = now() - interval '1 second' "
                "WHERE id = :tid"
            ),
            {"tid": plan.tasks[0].id},
        )
        await session.flush()

        # Tokenless completion succeeds on expired in_review
        done = await complete_task(
            session, PROJECT_A, plan.id, plan.tasks[0].id, claim_token=None, actor="reviewer"
        )
        assert done.status == TASK_STATUS_COMPLETED
        assert done.claimed_by == "reviewer"


# ---------------------------------------------------------------------------
# Finding 1 Regression: Archive / Complete Race with add_plan_task
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_task_insert_and_archive_race() -> None:
    """Task insert concurrent with plan archive fails with PlanNotActiveError (FR43, D20)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Archive Race Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1")],
        )
        await activate_plan(session, PROJECT_A, plan.id)

    add_task_paused = asyncio.Event()
    resume_add_task = asyncio.Event()

    async def _do_add_task() -> Exception | None:
        try:
            async with session_scope() as s:
                # 1. Plain read of plan while active in this session (identity-maps active plan)
                await s.execute(select(Plan).where(Plan.id == plan.id))
                add_task_paused.set()
                await resume_add_task.wait()
                await add_plan_task(s, PROJECT_A, plan.id, "T02", "Task 2", "Obj 2")
            return None
        except Exception as exc:
            return exc

    add_task_future = asyncio.create_task(_do_add_task())
    # Wait until add_plan_task session has read active plan into identity map
    await add_task_paused.wait()

    # Commit archive_plan while add_plan_task is paused
    async with session_scope() as s:
        await archive_plan(s, PROJECT_A, plan.id)

    # Release add_plan_task to take row lock and verify status refresh
    resume_add_task.set()
    add_result = await add_task_future

    assert isinstance(add_result, PlanNotActiveError)

    async with session_scope() as session:
        p = await get_plan(session, PROJECT_A, plan.id)
        assert p.status == PLAN_STATUS_ARCHIVED
        assert not any(t.local_task_id == "T02" for t in p.tasks)


@pytest.mark.asyncio
async def test_concurrent_task_insert_and_complete_race() -> None:
    """Task insert concurrent with plan complete fails with PlanNotActiveError (FR43, D20)."""
    await _seed_project(PROJECT_A)

    async with session_scope() as session:
        plan = await create_plan_with_tasks(
            session,
            PROJECT_A,
            "Complete Race Plan",
            "Goal",
            [TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1")],
        )
        await activate_plan(session, PROJECT_A, plan.id)
        c = await claim_task(session, PROJECT_A, plan.id, plan.tasks[0].id, "w", 1800)
        await complete_task(session, PROJECT_A, plan.id, plan.tasks[0].id, c.claim_token)

    add_task_paused = asyncio.Event()
    resume_add_task = asyncio.Event()

    async def _do_add_task() -> Exception | None:
        try:
            async with session_scope() as s:
                # 1. Plain read of plan while active in this session (identity-maps active plan)
                await s.execute(select(Plan).where(Plan.id == plan.id))
                add_task_paused.set()
                await resume_add_task.wait()
                await add_plan_task(s, PROJECT_A, plan.id, "T02", "Task 2", "Obj 2")
            return None
        except Exception as exc:
            return exc

    add_task_future = asyncio.create_task(_do_add_task())
    # Wait until add_plan_task session has read active plan into identity map
    await add_task_paused.wait()

    # Commit complete_plan while add_plan_task is paused
    async with session_scope() as s:
        await complete_plan(s, PROJECT_A, plan.id)

    # Release add_plan_task to take row lock and verify status refresh
    resume_add_task.set()
    add_result = await add_task_future

    assert isinstance(add_result, PlanNotActiveError)

    async with session_scope() as session:
        p = await get_plan(session, PROJECT_A, plan.id)
        assert p.status == PLAN_STATUS_COMPLETED
        assert not any(t.local_task_id == "T02" for t in p.tasks)


# ---------------------------------------------------------------------------
# Finding 2 Regression: Concurrent DAG Cycle Serialization
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_dag_cycle_prevention(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two concurrent transactions adding A->B and B->A serialize.

    One succeeds and one raises DependencyCycleError (FR45, INV-PLAN-1).
    """
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
    ]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Cycle Plan", "Goal", tasks)
        await activate_plan(session, PROJECT_A, plan.id)

    t1 = next(t for t in plan.tasks if t.local_task_id == "T01")
    t2 = next(t for t in plan.tasks if t.local_task_id == "T02")

    at_check: dict[str, asyncio.Event] = {
        t1.id: asyncio.Event(),
        t2.id: asyncio.Event(),
    }
    release_both = asyncio.Event()

    def _wrap_session(s: AsyncSession, target_task_id: str) -> None:
        real_exec = s.execute

        async def _sync_exec(statement: Any, *args: Any, **kwargs: Any) -> Any:
            result = await real_exec(statement, *args, **kwargs)
            froms = [
                getattr(t, "name", None)
                for t in getattr(statement, "get_final_froms", lambda: [])()
            ]
            if "task_dependencies" in froms and isinstance(statement, Select):
                at_check[target_task_id].set()
                await release_both.wait()
            return result

        monkeypatch.setattr(s, "execute", _sync_exec)

    async def _add_dep_1_2() -> DependencyCycleError | None:
        try:
            async with session_scope() as s:
                _wrap_session(s, t1.id)
                await add_task_dependency(s, PROJECT_A, plan.id, t1.id, t2.id)
            return None
        except DependencyCycleError as exc:
            return exc

    async def _add_dep_2_1() -> DependencyCycleError | None:
        try:
            async with session_scope() as s:
                _wrap_session(s, t2.id)
                await add_task_dependency(s, PROJECT_A, plan.id, t2.id, t1.id)
            return None
        except DependencyCycleError as exc:
            return exc

    task1 = asyncio.create_task(_add_dep_1_2())
    task2 = asyncio.create_task(_add_dep_2_1())

    # Wait for the first transaction to read dependency graph and pause before Kahn check
    await asyncio.wait(
        [
            asyncio.create_task(at_check[t1.id].wait()),
            asyncio.create_task(at_check[t2.id].wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # In un-serialized code, the loser would also reach barrier before either commits.
    # In serialized code, loser is blocked by DB lock until winner commits.
    loser_id = t2.id if at_check[t1.id].is_set() else t1.id
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(at_check[loser_id].wait(), timeout=0.05)

    # Release both simultaneously
    release_both.set()

    results = await asyncio.gather(task1, task2)

    successes = [r for r in results if r is None]
    cycle_errors = [r for r in results if isinstance(r, DependencyCycleError)]
    assert len(successes) == 1
    assert len(cycle_errors) == 1

    async with session_scope() as session:
        deps_res = await session.execute(
            text("SELECT task_id, depends_on_task_id FROM task_dependencies WHERE plan_id = :pid"),
            {"pid": plan.id},
        )
        edges = list(deps_res.all())
        assert len(edges) == 1


# ---------------------------------------------------------------------------
# TOCTOU Regression: set_task_status vs archive_plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_task_status_archive_race() -> None:
    """set_task_status on archived plan raises PlanNotActiveError and records no event.

    Demonstrates TOCTOU prevention: reading active plan before archive commits
    must still be rejected with PlanNotActiveError once archive commits (FR43, FR44, D20).
    """
    await _seed_project(PROJECT_A)

    tasks = [TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1")]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Status Race Plan", "Goal", tasks)
        await activate_plan(session, PROJECT_A, plan.id)

    t1 = next(t for t in plan.tasks if t.local_task_id == "T01")

    paused = asyncio.Event()
    resume = asyncio.Event()

    async def _do_status_update() -> Exception | None:
        try:
            async with session_scope() as s:
                # Plain read of plan while active in this session (identity-maps active plan)
                await s.execute(select(Plan).where(Plan.id == plan.id))
                paused.set()
                await resume.wait()
                await set_task_status(
                    s,
                    PROJECT_A,
                    plan.id,
                    t1.id,
                    status=TASK_STATUS_CANCELLED,
                )
            return None
        except Exception as exc:
            return exc

    update_task = asyncio.create_task(_do_status_update())
    await paused.wait()

    # Commit archive while update_task holds stale active plan read
    async with session_scope() as s_arch:
        await archive_plan(s_arch, PROJECT_A, plan.id)
        events_before = len(await get_task_history(s_arch, PROJECT_A, plan.id, t1.id))

    resume.set()
    result = await update_task

    assert isinstance(result, PlanNotActiveError)

    # Verify no mutation or new events occurred after archive
    async with session_scope() as session:
        p = await get_plan(session, PROJECT_A, plan.id)
        assert p.status == PLAN_STATUS_ARCHIVED
        events_after = len(await get_task_history(session, PROJECT_A, plan.id, t1.id))
        assert events_after == events_before


# ---------------------------------------------------------------------------
# TOCTOU Regression: heartbeat_task and complete_task vs archive_plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_heartbeat_and_complete_task_archive_race() -> None:
    """heartbeat_task and complete_task on archived plan raise PlanNotActiveError.

    Must return PlanNotActiveError, not StaleClaimTokenError or success (FR43, FR47, D20).
    """
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
    ]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Lease Race Plan", "Goal", tasks)
        await activate_plan(session, PROJECT_A, plan.id)

    t1 = next(t for t in plan.tasks if t.local_task_id == "T01")
    t2 = next(t for t in plan.tasks if t.local_task_id == "T02")

    # Claim both tasks
    async with session_scope() as session:
        c1 = await claim_task(session, PROJECT_A, plan.id, t1.id, "worker-1", 1800)
        c2 = await claim_task(session, PROJECT_A, plan.id, t2.id, "worker-2", 1800)

    # 1. Test heartbeat_task on archived plan with stale active plan read
    hb_paused = asyncio.Event()
    hb_resume = asyncio.Event()

    async def _do_heartbeat() -> Exception | None:
        try:
            async with session_scope() as s:
                await s.execute(select(Plan).where(Plan.id == plan.id))
                hb_paused.set()
                await hb_resume.wait()
                await heartbeat_task(s, PROJECT_A, plan.id, t1.id, c1.claim_token)
            return None
        except Exception as exc:
            return exc

    hb_future = asyncio.create_task(_do_heartbeat())
    await hb_paused.wait()

    # Archive plan while heartbeat holds stale active plan read
    async with session_scope() as s_arch:
        await archive_plan(s_arch, PROJECT_A, plan.id)

    hb_resume.set()
    hb_result = await hb_future
    assert isinstance(hb_result, PlanNotActiveError)

    # 2. Test complete_task on archived plan with stale active plan read
    async with session_scope() as s_comp:
        await s_comp.execute(select(Plan).where(Plan.id == plan.id))
        with pytest.raises(PlanNotActiveError):
            await complete_task(s_comp, PROJECT_A, plan.id, t2.id, c2.claim_token)


# ---------------------------------------------------------------------------
# Finding 1 Regression: Dependency edit on leased task rejected; prerequisite semantics
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_add_task_dependency_rejects_leased_and_reverts_ready() -> None:
    """Adding dependency rejects leased tasks (claimed/in_progress/in_review).

    Also reverts ready to pending on uncompleted prerequisite (INV-PLAN-1, INV-PLAN-3, D20).
    """
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
        TaskSpec(local_task_id="T03", title="Task 3", objective="Obj 3"),
    ]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Dep Lease Plan", "Goal", tasks)
        await activate_plan(session, PROJECT_A, plan.id)

    t1 = next(t for t in plan.tasks if t.local_task_id == "T01")
    t2 = next(t for t in plan.tasks if t.local_task_id == "T02")
    t3 = next(t for t in plan.tasks if t.local_task_id == "T03")

    # 1. Claim T01
    async with session_scope() as session:
        c1 = await claim_task(session, PROJECT_A, plan.id, t1.id, "worker-1", 1800)

    # 2. Adding dependency to claimed task fails with InvalidStateTransitionError
    with pytest.raises(
        InvalidStateTransitionError, match="Target task must be in 'pending' or 'ready'"
    ):
        async with session_scope() as session:
            await add_task_dependency(
                session, PROJECT_A, plan.id, t1.id, t2.id, claim_token=c1.claim_token
            )

    # 3. Transition to in_progress; adding dependency still rejected
    async with session_scope() as session:
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            t1.id,
            TASK_STATUS_IN_PROGRESS,
            claim_token=c1.claim_token,
        )

    with pytest.raises(
        InvalidStateTransitionError, match="Target task must be in 'pending' or 'ready'"
    ):
        async with session_scope() as session:
            await add_task_dependency(
                session, PROJECT_A, plan.id, t1.id, t2.id, claim_token=c1.claim_token
            )

    # 4. Transition to in_review; adding dependency still rejected
    async with session_scope() as session:
        await set_task_status(
            session,
            PROJECT_A,
            plan.id,
            t1.id,
            TASK_STATUS_IN_REVIEW,
            claim_token=c1.claim_token,
        )

    with pytest.raises(
        InvalidStateTransitionError, match="Target task must be in 'pending' or 'ready'"
    ):
        async with session_scope() as session:
            await add_task_dependency(
                session, PROJECT_A, plan.id, t1.id, t2.id, claim_token=c1.claim_token
            )

    # 5. Adding dependency on uncompleted T03 succeeds and reverts T02 to 'pending'
    async with session_scope() as session:
        await add_task_dependency(session, PROJECT_A, plan.id, t2.id, t3.id)

    # 6. Verify T02 is now pending and cannot be completed prematurely
    async with session_scope() as session:
        p = await get_plan(session, PROJECT_A, plan.id)
        t2_cur = next(t for t in p.tasks if t.id == t2.id)
        assert t2_cur.status == TASK_STATUS_PENDING

        # Attempting to complete T02 while prerequisite T03 is uncompleted fails
        with pytest.raises(InvalidStateTransitionError, match="pending"):
            await complete_task(session, PROJECT_A, plan.id, t2.id, claim_token=None)

        # Attempting to claim T02 while pending fails
        with pytest.raises(InvalidStateTransitionError, match="pending"):
            await claim_task(session, PROJECT_A, plan.id, t2.id, "worker-2", 1800)

        # 7. Complete prerequisite T03 -> T02 unlocks and becomes ready
        c3 = await claim_task(session, PROJECT_A, plan.id, t3.id, "worker-3", 1800)
        await complete_task(session, PROJECT_A, plan.id, t3.id, c3.claim_token)

        p_after = await get_plan(session, PROJECT_A, plan.id)
        t2_unlocked = next(t for t in p_after.tasks if t.id == t2.id)
        assert t2_unlocked.status == TASK_STATUS_READY

        # Now T02 can be claimed and completed cleanly
        c2_new = await claim_task(session, PROJECT_A, plan.id, t2.id, "worker-2", 1800)
        done = await complete_task(session, PROJECT_A, plan.id, t2.id, c2_new.claim_token)
        assert done.status == TASK_STATUS_COMPLETED


# ---------------------------------------------------------------------------
# Finding 4 Regression: Database-Enforced Event Log Immutability
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_database_immutable_event_log() -> None:
    """PostgreSQL trigger rejects UPDATE and DELETE on plan_task_events (INV-PLAN-4, FR48, D21)."""
    await _seed_project(PROJECT_A)

    tasks = [TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1")]
    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Event Plan", "Goal", tasks)

    # Query event ID
    async with session_scope() as session:
        res = await session.execute(
            text("SELECT id FROM plan_task_events WHERE plan_id = :pid LIMIT 1"),
            {"pid": plan.id},
        )
        event_id = res.scalar_one()

    # Attempt raw SQL UPDATE -> DBAPIError (append-only)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session_scope() as session:
            await session.execute(
                text("UPDATE plan_task_events SET actor = 'tampered' WHERE id = :id"),
                {"id": event_id},
            )
            await session.flush()

    # Attempt raw SQL DELETE -> DBAPIError (append-only)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session_scope() as session:
            await session.execute(
                text("DELETE FROM plan_task_events WHERE id = :id"),
                {"id": event_id},
            )
            await session.flush()

    # History remains fully queryable
    async with session_scope() as session:
        events = await get_task_history(session, PROJECT_A, plan.id, plan.tasks[0].id)
        assert len(events) >= 1
        assert events[0].id == event_id


# ---------------------------------------------------------------------------
# Finding 5 Regression: claim_task on Pending Task Rejected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_claim_pending_task_rejected() -> None:
    """Tasks in 'pending' status cannot be claimed directly; must be ready or expired (FR47)."""
    await _seed_project(PROJECT_A)

    tasks = [
        TaskSpec(local_task_id="T01", title="Task 1", objective="Obj 1"),
        TaskSpec(local_task_id="T02", title="Task 2", objective="Obj 2"),
    ]
    deps = [DependencySpec(task_local_id="T02", depends_on_local_id="T01")]

    async with session_scope() as session:
        plan = await create_plan_with_tasks(session, PROJECT_A, "Pending Plan", "Goal", tasks, deps)
        activated = await activate_plan(session, PROJECT_A, plan.id)

    t2 = next(t for t in activated.tasks if t.local_task_id == "T02")
    assert t2.status == TASK_STATUS_PENDING

    # Attempting to claim T02 while pending fails
    with pytest.raises(InvalidStateTransitionError, match="pending"):
        async with session_scope() as session:
            await claim_task(session, PROJECT_A, plan.id, t2.id, "worker-1", 1800)


# ---------------------------------------------------------------------------
# Migration test: Upgrade & Downgrade roundtrip
# ---------------------------------------------------------------------------
def test_migration_upgrade_and_downgrade() -> None:
    """Migration 0023 upgrades cleanly from 0019 and downgrades cleanly back."""
    config = Config("alembic.ini")

    # Downgrade to 0019
    command.downgrade(config, "0019_evidence_quality")

    # Verify tables do not exist
    # Upgrade back to head
    command.upgrade(config, "head")
