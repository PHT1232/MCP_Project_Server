# T23 — Plan & Task core model and service

**Branch:** `task/T23-plan-task-core` · **Depends on:** T22 · **Blocks:** T24

## Goal

Implement the foundational planning domain model, database migrations, and deterministic Python service in `pcs.planning` for plans, plan tasks, DAG dependencies, atomic claim leases, and immutable task event history with strict project isolation.

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

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-2` (`fdab6d29-f527-4d13-91c2-6510a3309f2d`): Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4).
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.
- `INV-PLAN-4` (`d196d5d6-20fc-4771-ad07-f80397eda510`): Every plan task mutation appends an immutable event recording author, event type, prior state, new state, and timestamp; events are never updated or deleted.

## Requirements

- Create PostgreSQL tables `plans`, `plan_tasks`, `task_dependencies`, and `plan_task_events` via an Alembic migration with clean upgrade/downgrade.
- Implement strict composite foreign keys and check constraints enforcing project and plan isolation.
- Implement deterministic planning service methods in `pcs.planning.service`:
  - `create_plan` and atomic `create_plan_with_tasks`.
  - `get_plan`, `list_plans`, `update_plan`, `archive_plan`, `activate_plan`.
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`.
  - `list_ready_tasks`: returns tasks whose prerequisites are all completed and that have no active unexpired lease.
  - `claim_task`: atomically claims a ready task, generates a cryptographically random secret token, stores its SHA-256 hash, and sets `lease_expires_at`. Returns raw token once.
  - `heartbeat_task`: extends active lease when presented with valid current claim token.
  - `release_task`: voluntarily yields active claim lease back to ready status.
  - `set_task_status`: transitions task status, validating allowed state graph and claim token.
  - `complete_task`: marks task completed, unlocks dependent tasks, and leaves requirement status unchanged (D4, D19).
  - `complete_plan`: marks plan completed only when all non-cancelled tasks are completed.
- Detect and reject dependency cycles using Kahn's algorithm or DFS before saving.
- Every task mutation appends an immutable row to `plan_task_events` with author and state transition.
- Use strict Pydantic typed views for all return types.

## Acceptance checklist

- [ ] `AC-PLAN-1` (`bcfa212d-eae5-42c6-b98a-7ba78cbfcb75`): Plan and task DAG creation rejects cycles, self-dependencies, cross-plan, and cross-project references.
- [ ] `AC-PLAN-2` (`911bab97-9662-4acb-8efe-4cece2aeab7c`): Ready-task discovery returns only tasks whose prerequisites are complete and lease is unacquired or expired.
- [ ] `AC-PLAN-3` (`42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b`): Task completion and plan completion never mutate requirement status or bypass evidence close gate.
- [ ] `AC-PLAN-4` (`8fc004f9-b782-4158-afa5-7ceb693a4315`): Atomic task claim issues unique ephemeral token and rejects concurrent claim race.
- [ ] `AC-PLAN-5` (`05f02bf6-ab90-4f28-9002-2e88d69a07a1`): Task heartbeat, release, and reclaim enforce lease validity and reject invalid or stale tokens.
- [ ] `AC-PLAN-6` (`e671ec47-f6b3-4e18-8fbf-5606f5afe90b`): Every plan task mutation appends an immutable event and preserves complete queryable task history.
- [ ] Migration upgrades cleanly from prior integrated head and downgrades cleanly.
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
- **Service API seams for T24:**
  - `create_plan`, `create_plan_with_tasks`
  - `get_plan`, `list_plans`, `update_plan`, `activate_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`
  - `list_ready_tasks`, `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`
  - `get_task_history`
- **Verification:**
  - Focused tests output
  - `just check` result
- **Deviations:** None
```
