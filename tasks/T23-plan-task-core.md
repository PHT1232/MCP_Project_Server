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
  - Reclaim: when `lease_expires_at < now()` across `claimed`, `in_progress`, or `in_review`, another worker can call `claim_task`. Old token is revoked; new token and lease are issued, and status transitions to `claimed`.
  - Review: `in_progress -> in_review` retains lease fields. While lease is active (`lease_expires_at >= now()`), only the leaseholder with the valid token can complete or mutate the task; concurrent claim attempts are rejected with 409 Conflict. When lease expires, the task appears in `list_ready_tasks` as reclaimable, and can be reclaimed to `claimed` with a new token, or completed without token in the single-user model.
  - Blocked: `set_task_status(status='blocked')` strictly requires active claim token if lease is active; atomically clears all lease fields (`claim_token_hash = NULL`, `claimed_by = NULL`, `lease_expires_at = NULL`). A blocked task cannot hold a lease. `blocked -> ready` returns task to pool with no active token.
  - Complete: `complete_task` requires valid token if lease is active; clears `claim_token_hash = NULL`, `lease_expires_at = NULL`, permanently revoking claim token.
  - Cancellation: requires valid token if lease is active; revokes lease fields and marks terminal.
  - No Operator Bypass: mutations on tasks with active leases strictly require the valid claim token; no caller can bypass an active lease by claiming to be an operator.
  - Plan Archival: `archive_plan` is the sole administrative exception that atomically revokes all active leases across all tasks in the plan, sets non-completed tasks to `cancelled`, and sets plan status to `archived`.
  - Completed / Archived Plans: any mutation on a task in a completed or archived plan is strictly rejected with `PlanNotActiveError`.
  - Stale Token Rejection: any mutation presenting an expired, revoked, or mismatched token fails with `StaleClaimTokenError`.
  - Canonical predicate for `list_ready_tasks`:
    - Plan is `active` in active project.
    - Task is not `completed`, `cancelled`, or `blocked`.
    - All prerequisite dependencies in DAG are `completed`.
    - Task is either `ready` OR has an expired lease (`status IN ('claimed', 'in_progress', 'in_review') AND lease_expires_at < now()`).
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

- [ ] `AC-PLAN-1` (`bcfa212d-eae5-42c6-b98a-7ba78cbfcb75`): Plan and task DAG creation rejects cycles, self-dependencies, cross-plan, and cross-project references, enforcing database composite foreign keys and section validation on plan_task_requirements.
- [ ] `AC-PLAN-2` (`911bab97-9662-4acb-8efe-4cece2aeab7c`): Ready-task discovery returns only tasks whose prerequisites are complete and lease is unacquired or expired.
- [ ] `AC-PLAN-3` (`42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b`): Task completion and plan completion never mutate requirement status or bypass evidence close gate.
- [ ] `AC-PLAN-4` (`8fc004f9-b782-4158-afa5-7ceb693a4315`): Atomic task claim issues unique ephemeral token and rejects concurrent claim race.
- [ ] `AC-PLAN-5` (`05f02bf6-ab90-4f28-9002-2e88d69a07a1`): Task heartbeat, release, and reclaim enforce lease validity and reject invalid or stale tokens.
- [ ] `AC-PLAN-6` (`e671ec47-f6b3-4e18-8fbf-5606f5afe90b`): Every plan task mutation appends an immutable event with structured payload diff and preserves complete queryable task history.
- [ ] Database composite FKs strictly prevent inserting cross-plan and cross-project dependencies.
- [ ] Linking a non-requirement entry (e.g. bug, focus, decision) to `plan_task_requirements` fails at both service validation and database check/FK constraint.
- [ ] Stale token rejected after task release.
- [ ] Stale token rejected after task reclaim.
- [ ] Expired lease in `in_review` appears in `list_ready_tasks` and can be reclaimed atomically to `claimed`.
- [ ] Unexpired lease in `in_review` rejects concurrent claim attempts with 409 Conflict.
- [ ] Heartbeat on `claimed` task keeps status `claimed` and does not transition to `in_progress`.
- [ ] Mutating task with active lease without valid token (or claiming operator status) is rejected.
- [ ] Transitioning task to `blocked` revokes active lease; `blocked -> ready` leaves no active token.
- [ ] Cancelling a claimed/in-progress task revokes active lease.
- [ ] `archive_plan` atomically revokes all active leases on plan tasks.
- [ ] Claim, heartbeat, and status mutations on completed or archived plans are rejected.
- [ ] Migration upgrades cleanly from prior integrated head on PostgreSQL and downgrades cleanly.
- [ ] Concurrency tests verify that two concurrent `claim_task` calls on the same ready task result in exactly one claim and one conflict rejection.
- [ ] Strict typecheck (`mypy --strict`), ruff format/lint, and focused tests pass.
- [ ] `just check` passes at repo root.
- [ ] Task handoff documents schema, service API seams for T24, migration revision, and verification results.

## Required evidence

- Unit, concurrency, and migration tests in `server/tests/test_planning_core.py`.
- Independent review required for `AC-PLAN-3` (Requirement independence / D4).

## Verification

```bash
cd server && uv run pytest tests/test_planning_core.py -v
just check
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T23-plan-task-core`
- **What was done:**
  - ...
- **Schema & Migration:**
  - Migration revision: `...`
  - Down revision: `...`
  - Tables: `plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, `plan_task_events`
- **Database Isolation:**
  - Composite FKs for dependencies: `(task_id, plan_id, project_id)`
  - Composite FKs for requirements: `(requirement_id, requirement_section)`
- **Service API seams for T24:**
  - `create_plan`, `create_plan_with_tasks`
  - `get_plan`, `list_plans`, `update_plan`, `archive_plan`, `activate_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`
  - `list_ready_tasks`, `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`, `get_task_history`
- **Verification:**
  - PostgreSQL test suite output
  - `just check` result
- **Deviations:** None
```
