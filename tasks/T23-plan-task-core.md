# T23 — Plan & Task core model and service

**Branch:** `task/T23-plan-task-core` · **Depends on:** T22 · **Blocks:** T24

## Goal

Implement the foundational planning domain model, database migrations, and deterministic Python service in `pcs.planning` for plans, plan tasks, DAG dependencies with database-level plan/project isolation, normalized requirement links with section validation, atomic claim leases, and immutable task event history with strict project isolation.

## Owned files/modules

- New `server/src/pcs/planning/` package:
  - `server/src/pcs/planning/__init__.py`
  - `server/src/pcs/planning/models.py`
  - `server/src/pcs/planning/service.py`
  - `server/src/pcs/planning/types.py`
  - `server/src/pcs/planning/errors.py`
- `server/src/pcs/db/models.py` (only for registering planning ORM models)
- New Alembic migration under `server/src/pcs/alembic/versions/*_plan_task_orchestration.py`
- `server/tests/test_planning_core.py`
- `tasks/T23-plan-task-core.md`

Do not touch MCP tools, HTTP routes, retrieval/prepare_task, frontend, or AI generation.

## Non-goals

- Exposing MCP tools or HTTP routes (owned by T24).
- Formatting task handoff prompts or modifying `prepare_task` (owned by T25).
- Integrating AI generation providers (owned by T26).
- Building React components or pages (owned by T27, T28).
- Spawning worker processes or running shell commands (D24).

## Invariants

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; task dependencies and requirement links enforce tenant and plan isolation via database composite foreign keys; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-2` (`fdab6d29-f527-4d13-91c2-6510a3309f2d`): Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4).
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.
- `INV-PLAN-4` (`d196d5d6-20fc-4771-ad07-f80397eda510`): Every plan task mutation appends an immutable event recording author, event type, prior state, new state, timestamp, and structured payload; events are never updated or deleted.

## Requirements

- Database Architecture & Isolation:
  - `plans`: `(id, project_id)` unique constraint.
  - `plan_tasks`:
    - `UniqueConstraint("id", "plan_id", "project_id", name="uq_plan_tasks_id_plan_project")`
    - `UniqueConstraint("id", "project_id", name="uq_plan_tasks_id_project")`
    - `UniqueConstraint("plan_id", "local_task_id", name="uq_plan_tasks_plan_local_id")`
  - `task_dependencies`:
    - Columns: `project_id`, `plan_id`, `task_id`, `depends_on_task_id`, `created_at`.
    - Primary Key: `(task_id, depends_on_task_id)`.
    - Composite Foreign Keys:
      - `["task_id", "plan_id", "project_id"]` -> `plan_tasks["id", "plan_id", "project_id"]`
      - `["depends_on_task_id", "plan_id", "project_id"]` -> `plan_tasks["id", "plan_id", "project_id"]`
    - CheckConstraint: `task_id != depends_on_task_id`.
    - Enforces at the database level that both tasks belong to the exact same plan and project.
  - `plan_task_requirements`:
    - Columns: `project_id`, `plan_task_id`, `requirement_id`, `requirement_section` (server_default="requirements"), `created_at`.
    - Primary Key: `(plan_task_id, requirement_id)`.
    - CheckConstraint: `requirement_section = 'requirements'`.
    - Composite Foreign Keys:
      - `["plan_task_id", "project_id"]` -> `plan_tasks["id", "project_id"]`
      - `["requirement_id", "project_id"]` -> `context_entries["id", "project_id"]`
      - `["requirement_id", "requirement_section"]` -> `context_entries["id", "section"]`
    - Guarantees at database level that the target entry belongs to the same project AND belongs to section `requirements`.
    - Service validation also verifies `target.section == 'requirements'` and rejects non-requirement entries (bugs, focus, decisions).
  - `plan_task_events`:
    - Columns: `id`, `project_id`, `plan_id`, `task_id`, `event_type`, `actor`, `old_status`, `new_status`, `payload`, `created_at`.
    - Composite Foreign Key: `["task_id", "plan_id", "project_id"]` -> `plan_tasks["id", "plan_id", "project_id"]`.
    - `event_type` Enum (10 types): `created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`.
    - `payload` JSONB: Bounded structured dictionary recording event-specific metadata (redacted of secrets/tokens).
- Plan Task State Machine & Complete Lease Lifecycle:
  - States: `pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`.
  - Persisted status: `status` is persisted. On `activate_plan`, root tasks with zero dependencies transition `pending -> ready`. On `complete_task`, downstream tasks whose dependencies are now all `completed` transition `pending -> ready`.
  - Claim & in-progress: `claim_task` atomically transitions `ready` (or expired claimed/in_progress/in_review) to `claimed`. Worker calls `set_task_status(status='in_progress')` with valid token to transition to `in_progress`, retaining the lease.
  - Heartbeat: verifies active token, extends `lease_expires_at`, and strictly preserves exact persisted status (`claimed` remains `claimed`, `in_progress` remains `in_progress`; never mutates status).
  - Release: `release_task` atomically sets `claim_token_hash = NULL`, `claimed_by = NULL`, `lease_expires_at = NULL`, transitioning task to `ready`. Old token is permanently revoked.
  - Reclaim: when `lease_expires_at <= now()` across `claimed`, `in_progress`, or `in_review`, another worker can call `claim_task`. Old token is revoked; new token and lease are issued, and status transitions to `claimed`.
  - Review: `in_progress -> in_review` retains lease fields. While lease is active (`lease_expires_at > now()`), only the leaseholder with the valid token can complete or mutate the task; concurrent claim attempts are rejected with 409 Conflict. When lease expires (`lease_expires_at <= now()`), the task appears in `list_ready_tasks` as reclaimable, and can be reclaimed to `claimed` with a new token, or completed without token in the single-user model.
  - Blocked: `set_task_status(status='blocked')` strictly requires active claim token if lease is active; atomically clears all lease fields (`claim_token_hash = NULL`, `claimed_by = NULL`, `lease_expires_at = NULL`). A blocked task cannot hold a lease. `blocked -> ready` returns task to pool with no active token.
  - Complete: `complete_task` requires valid token if lease is active; clears `claim_token_hash = NULL`, `lease_expires_at = NULL`, permanently revoking claim token.
  - Cancellation: requires valid token if lease is active; revokes lease fields and marks terminal.
  - No Operator Bypass: mutations on tasks with active leases strictly require the valid claim token; no caller can bypass an active lease by claiming to be an operator.
  - Plan Archival: `archive_plan` is the sole administrative exception that atomically revokes all active leases across all tasks in the plan, sets non-completed tasks to `cancelled`, and sets plan status to `archived`.
  - Completed / Archived Plans: any mutation on a task in a completed or archived plan is strictly rejected with `PlanNotActiveError`.
  - Stale Token Rejection: any mutation presenting an expired (`lease_expires_at <= now()`), revoked, or mismatched token fails with `StaleClaimTokenError`.
  - Lease Expiration Boundary Normalization: Active lease is strictly `lease_expires_at > now()`. Expired/reclaimable lease is `lease_expires_at <= now()`. At exact boundary `lease_expires_at == now()`, task is treated as expired (reclaimable via `claim_task`; token mutations rejected).
  - Canonical predicate for `list_ready_tasks`:
    - Plan is `active` in active project.
    - Task is not `completed`, `cancelled`, or `blocked`.
    - All prerequisite dependencies in DAG are `completed`.
    - Task is either `ready` OR has an expired lease (`status IN ('claimed', 'in_progress', 'in_review') AND lease_expires_at <= now()`).
- Deterministic Service Methods in `pcs.planning.service`:
  - `create_plan`, `create_plan_with_tasks`
  - `get_plan`, `list_plans`, `update_plan`, `archive_plan`, `activate_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`
  - `list_ready_tasks`
  - `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`, `get_task_history`
- DAG Validation: Kahn's algorithm or DFS rejects cycles and self-dependencies before persisting.
- Append-Only Event Log: Every mutation writes a corresponding event with structured `payload` dictionary.

## Acceptance checklist

- [x] `AC-PLAN-1` (`bcfa212d-eae5-42c6-b98a-7ba78cbfcb75`): Plan and task DAG creation rejects cycles, self-dependencies, cross-plan, and cross-project references, enforcing database composite foreign keys and section validation on plan_task_requirements.
- [x] `AC-PLAN-2` (`911bab97-9662-4acb-8efe-4cece2aeab7c`): Ready-task discovery returns only tasks whose prerequisites are complete and lease is unacquired or expired.
- [x] `AC-PLAN-3` (`42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b`): Task completion and plan completion never mutate requirement status or bypass evidence close gate.
- [x] `AC-PLAN-4` (`8fc004f9-b782-4158-afa5-7ceb693a4315`): Atomic task claim issues unique ephemeral token and rejects concurrent claim race.
- [x] `AC-PLAN-5` (`05f02bf6-ab90-4f28-9002-2e88d69a07a1`): Task heartbeat, release, and reclaim enforce lease validity and reject invalid or stale tokens.
- [x] `AC-PLAN-6` (`e671ec47-f6b3-4e18-8fbf-5606f5afe90b`): Every plan task mutation appends an immutable event with structured payload diff and preserves complete queryable task history.
- [x] Database composite FKs strictly prevent inserting cross-plan and cross-project dependencies.
- [x] Linking a non-requirement entry (e.g. bug, focus, decision) to `plan_task_requirements` fails at both service validation and database check/FK constraint.
- [x] Stale token rejected after task release.
- [x] Stale token rejected after task reclaim.
- [x] Expired lease in `in_review` appears in `list_ready_tasks` and can be reclaimed atomically to `claimed`.
- [x] Unexpired lease in `in_review` rejects concurrent claim attempts with 409 Conflict.
- [x] Exact boundary condition `lease_expires_at == now()` is verified treated as expired and reclaimable; presenting token at `lease_expires_at == now()` fails with 409 / StaleClaimTokenError.
- [x] Heartbeat on `claimed` task keeps status `claimed` and does not transition to `in_progress`.
- [x] Mutating task with active lease without valid token (or claiming operator status) is rejected.
- [x] Transitioning task to `blocked` revokes active lease; `blocked -> ready` leaves no active token.
- [x] Cancelling a claimed/in-progress task revokes active lease.
- [x] `archive_plan` atomically revokes all active leases on plan tasks.
- [x] Claim, heartbeat, and status mutations on completed or archived plans are rejected.
- [x] Migration upgrades cleanly from prior integrated head on PostgreSQL and downgrades cleanly.
- [x] Concurrency tests verify that two concurrent `claim_task` calls on the same ready task result in exactly one claim and one conflict rejection.
- [x] Strict typecheck (`mypy --strict`), ruff format/lint, and focused tests pass.
- [x] `just check` passes at repo root.
- [x] Task handoff documents schema, service API seams for T24, migration revision, and verification results.

## Required evidence

- Unit, concurrency, and migration tests in `server/tests/test_planning_core.py`.
- Independent review required for `AC-PLAN-3` (Requirement independence / D4).

## Verification

```bash
cd server && uv run pytest tests/test_planning_core.py -v
just check
```

## Handoff

- **Branch:** `task/T23-plan-task-core`
- **What was done:**
  - Implemented core domain types, models, constants, and custom domain exceptions in `pcs.planning`.
  - Authored Alembic migration `0023_plan_task_orchestration.py` adding `plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, and `plan_task_events` tables with composite foreign keys and constraints.
  - Implemented deterministic planning domain service in `pcs.planning.service` providing full lifecycle operations: plan creation, task authoring, Kahn's algorithm DAG cycle detection, ready-task discovery, atomic concurrency-safe claim leases, heartbeat, release, status transitions, task and plan completion, archival revocation, and 10-event immutable audit logging with SHA-256 token hashing and secret redaction.
  - Preserved D4 / INV-PLAN-2: neither task completion nor plan completion touches requirement status or evidence close gate.
  - Implemented 22 comprehensive PostgreSQL-backed unit, concurrency, and migration tests in `server/tests/test_planning_core.py`.
- **Schema & Migration:**
  - Migration revision: `0023_plan_task_orchestration`
  - Down revision: `0019_evidence_quality`
  - Tables: `plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, `plan_task_events`
- **Database Isolation & Integrity:**
  - `task_dependencies`: composite foreign keys `(task_id, plan_id, project_id)` and `(depends_on_task_id, plan_id, project_id)` referencing `plan_tasks(id, plan_id, project_id)`.
  - `plan_task_requirements`: composite foreign key `(requirement_id, requirement_section)` referencing `context_entries(id, section)` with check constraint `chk_ptr_requirement_section` enforcing `requirement_section = 'requirements'`.
  - Unique composite keys `(project_id, plan_id, local_task_id)` and `(id, plan_id, project_id)` on `plan_tasks`.
- **Service API seams for T24:**
  - `create_plan(session, project, title, goal, author="agent") -> PlanView`
  - `create_plan_with_tasks(session, project, title, goal, tasks, dependencies, author="agent") -> PlanView`
  - `get_plan(session, project, plan_id) -> PlanView`
  - `list_plans(session, project, status=None, limit=50, offset=0) -> list[PlanSummaryView]`
  - `update_plan(session, project, plan_id, title=None, goal=None, author="agent") -> PlanView`
  - `archive_plan(session, project, plan_id, actor="agent") -> PlanView`
  - `activate_plan(session, project, plan_id, actor="agent") -> PlanView`
  - `add_plan_task(session, project, plan_id, local_task_id, title, objective, scope_files=None, requirement_ids=None, actor="agent") -> PlanTaskView`
  - `update_plan_task(session, project, plan_id, task_id, title=None, objective=None, scope_files=None, requirement_ids=None, claim_token=None, actor="agent") -> PlanTaskView`
  - `add_task_dependency(session, project, plan_id, task_id, depends_on_task_id, actor="agent") -> None`
  - `list_ready_tasks(session, project, plan_id=None) -> list[PlanTaskView]`
  - `claim_task(session, project, plan_id, task_id, claimed_by, lease_seconds=DEFAULT_LEASE_SECONDS) -> ClaimResultView`
  - `heartbeat_task(session, project, plan_id, task_id, claim_token, lease_seconds=DEFAULT_LEASE_SECONDS, actor="agent") -> PlanTaskView`
  - `release_task(session, project, plan_id, task_id, claim_token, reason="voluntary_release") -> PlanTaskView`
  - `set_task_status(session, project, plan_id, task_id, status, claim_token=None, actor="agent", payload=None) -> PlanTaskView`
  - `complete_task(session, project, plan_id, task_id, claim_token=None, actor="agent", handoff=None) -> PlanTaskView`
  - `complete_plan(session, project, plan_id, actor="agent") -> PlanView`
  - `get_task_history(session, project, plan_id, task_id) -> list[TaskEventView]`
- **Exceptions for transport mapping in T24:**
  - `PlanNotFoundError` -> 404 / NotFound
  - `TaskNotFoundError` -> 404 / NotFound
  - `PlanningValidationError` -> 400 / BadRequest
  - `DependencyCycleError` -> 400 / BadRequest
  - `ClaimConflictError` -> 409 / Conflict
  - `StaleClaimTokenError` -> 409 / Conflict
  - `InvalidStateTransitionError` -> 409 / Conflict
  - `PlanNotActiveError` -> 409 / Conflict
- **Verification:**
  - `cd server && uv run pytest tests/test_planning_core.py -v`: 22 passed in 8.19s
  - `just check`: green (101 files ruff format/check, web eslint, server mypy, web tsc, 301 server pytest passed, 68 vitest passed, docker compose config verified, web vite build succeeded)
- **Deviations:** None
- **Cross-task / Independent Review Needs:**
  - `AC-PLAN-3` (`42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b`): Requires independent review for requirement status independence (D4) before gate close. Evidence recorded at commit SHA `dfb1eced3bb4bfd7b115be0ab441cd237b19f441`.
  - Requirement `R-086` remains `in-progress` pending downstream implementation of T24–T29.
