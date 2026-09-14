# T24 — Plan & Task MCP and HTTP API surface

**Branch:** `task/T24-plan-task-api` · **Depends on:** T23 · **Blocks:** T25, T26, T27

## Goal

Expose the planning domain via audited, typed MCP tools and Starlette HTTP endpoints mounted through FastMCP, with nested task routes, strict URL-plan-task verification, stable HTTP status mappings, and token redaction, delegating all business logic to `pcs.planning.service`.

## Owned files/modules

- New `server/src/pcs/mcp/planning_tools.py` (`register_planning_tools(mcp: FastMCP)`)
- New `server/src/pcs/web_api/planning_routes.py` (`register_planning_routes(mcp: FastMCP)`)
- Minimal registration additions in `server/src/pcs/mcp/server.py` (`register_planning_tools(mcp)`, `register_planning_routes(mcp)`)
- `server/tests/test_planning_api.py`
- `tasks/T24-plan-task-api.md`

*Sequenced Shared Integration Seam:* T24 establishes base `planning_tools.py` and `planning_routes.py`. Downstream task T26 branches sequentially from merged T24 to append AI draft generation endpoints without altering base planning tools/routes.

Do not touch `pcs.index.retrieval`, frontend code, or AI generators. Do not invent non-existent `router.py` or `app.py` modules.

## Non-goals

- Implementing domain models, migrations, or database queries (owned by T23).
- Modifying `prepare_task` or index retrieval (owned by T25).
- Implementing AI draft generation logic (owned by T26).
- Building frontend views or components (owned by T27).

## Invariants

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; task dependencies and requirement links enforce tenant and plan isolation via database composite foreign keys; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.

## Requirements

- Expose typed, audited MCP tools in `pcs.mcp.planning_tools`:
  - `create_plan(project, title, goal)`
  - `create_plan_with_tasks(project, title, goal, tasks, dependencies)`
  - `list_plans(project, status=None)`
  - `get_plan(project, plan_id)`
  - `update_plan(project, plan_id, title=None, goal=None)`
  - `archive_plan(project, plan_id)`
  - `activate_plan(project, plan_id)`
  - `add_plan_task(project, plan_id, local_task_id, title, objective, acceptance_criteria, linked_files=None, requirement_ids=None, priority=0)`
  - `update_plan_task(project, plan_id, task_id, title=None, objective=None, acceptance_criteria=None, linked_files=None, requirement_ids=None, priority=None)`
  - `add_task_dependency(project, plan_id, task_id, depends_on_task_id)`
  - `list_ready_tasks(project, plan_id=None)`
  - `claim_task(project, plan_id, task_id, claimed_by, lease_seconds=1800)`
  - `heartbeat_task(project, plan_id, task_id, claim_token, lease_seconds=1800)`
  - `release_task(project, plan_id, task_id, claim_token)`
  - `set_task_status(project, plan_id, task_id, status, claim_token=None, reason=None)`
  - `complete_task(project, plan_id, task_id, claim_token=None)`
  - `complete_plan(project, plan_id)`
  - `get_task_history(project, plan_id, task_id)`
- Expose matching Starlette HTTP routes in `pcs.web_api.planning_routes` registered via `mcp.custom_route(path, methods)(handler)`:
  - `POST /api/projects/{project}/plans` (`create_plan`)
  - `POST /api/projects/{project}/plans/with-tasks` (`create_plan_with_tasks`)
  - `GET /api/projects/{project}/plans` (`list_plans`)
  - `GET /api/projects/{project}/plans/{plan_id}` (`get_plan`)
  - `PATCH /api/projects/{project}/plans/{plan_id}` (`update_plan`)
  - `POST /api/projects/{project}/plans/{plan_id}/archive` (`archive_plan`)
  - `POST /api/projects/{project}/plans/{plan_id}/activate` (`activate_plan`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks` (`add_plan_task`)
  - `PATCH /api/projects/{project}/plans/{plan_id}/tasks/{task_id}` (`update_plan_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/dependencies` (`add_task_dependency`)
  - `GET /api/projects/{project}/ready-tasks` (`list_ready_tasks` across all plans)
  - `GET /api/projects/{project}/plans/{plan_id}/ready-tasks` (`list_ready_tasks` plan-scoped)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/claim` (`claim_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/heartbeat` (`heartbeat_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/release` (`release_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/status` (`set_task_status`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/complete` (`complete_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/complete` (`complete_plan`)
  - `GET /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/history` (`get_task_history`)
- URL Hierarchy & Plan Verification:
  - Handlers verify that the task requested at `.../plans/{plan_id}/tasks/{task_id}/...` belongs to both `plan_id` and `project` in the URL; cross-plan mismatches return 404 (`TaskNotFoundError`).
- Request & Response Schemas:
  - `UpdatePlanRequest`: Optional `title` (1..160 chars), optional `goal` (1..8000 chars). Reject empty patches with 400.
  - `ArchivePlanResponse`: Returns updated plan with `status: "archived"`.
  - `TaskEventResponse`: `id`, `event_type`, `actor`, `old_status`, `new_status`, `payload` (JSON dict), `created_at`.
- Validation & Error Handling:
  - Delegate all business logic to `pcs.planning.service`.
  - Extract caller identity from header `x-pcs-caller` (defaulting to `"frontend"`).
  - Map `ProjectNotFoundError` -> 404 with available projects.
  - Map `PlanNotFoundError`, `TaskNotFoundError` -> 404.
  - Map `ValidationError`, empty patch, unknown fields, mismatched types -> 400.
  - Map `ClaimConflictError`, `StaleClaimTokenError`, `PlanNotActiveError` -> 409 Conflict.
  - Map `InvalidStateTransitionError` -> 400.
- Token Redaction & Audit Safety:
  - Emit structured audit log lines (`log_tool_call`) for every call recording tool, project, caller, and outcome (NFR6).
  - `claim_task` returns the raw ephemeral claim token exactly once in the response payload.
  - All other reads (`get_plan`, `list_plans`, `list_ready_tasks`, `get_task_history`) emit only `claimed_by` and `lease_expires_at`, never exposing the raw token or token hash.
  - Audit logs never include claim tokens or sensitive request payloads.

## Acceptance checklist

- [ ] `AC-PLAN-7` (`eeb30422-628b-4a3d-bd01-b267c42e8a2f`): Audited MCP and HTTP planning tools expose typed operations including update_plan and archive_plan with token redaction and input validation.
- [ ] Every MCP tool call emits structured audit log containing tool, project, caller, outcome (NFR6).
- [ ] `update_plan` successfully updates title and/or goal; empty patch returns 400.
- [ ] `archive_plan` transitions plan status to `archived` and revokes active leases.
- [ ] All task-level HTTP routes use nested `/plans/{plan_id}/tasks/{task_id}/...` structure.
- [ ] Request with mismatched `plan_id` in URL returns 404 / TaskNotFoundError.
- [ ] `claim_task` returns raw claim token exactly once; subsequent reads omit token and token hash.
- [ ] Stale or expired token on heartbeat/status/complete returns 409 / StaleClaimTokenError.
- [ ] Mutation on task in completed or archived plan returns 409 / PlanNotActiveError.
- [ ] Unknown fields, malformed JSON, and empty patch bodies return HTTP 400.
- [ ] Concurrent claim conflict returns clean 409 Conflict in MCP and HTTP.
- [ ] `get_task_history` returns structured, chronologically ordered task events with safe payloads across all 10 event types.
- [ ] MCP tools and HTTP routes return equivalent typed JSON response shapes.
- [ ] `just check` passes with zero lint, typecheck, or test failures.
- [ ] Task handoff documents tool signatures, route paths, and test results.

## Required evidence

- Integration tests in `server/tests/test_planning_api.py` covering MCP tool dispatch and HTTP route requests.
- Independent review required for `AC-PLAN-7` (token redaction and audit safety).

## Verification

```bash
cd server && uv run pytest tests/test_planning_api.py -v
just check
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T24-plan-task-api`
- **What was done:**
  - ...
- **Public MCP Tools:**
  - `create_plan`, `create_plan_with_tasks`, `list_plans`, `get_plan`, `update_plan`, `archive_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`, `activate_plan`
  - `list_ready_tasks`, `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`, `get_task_history`
- **Public HTTP Endpoints (Nested):**
  - `/api/projects/{project}/plans`
  - `/api/projects/{project}/plans/{plan_id}`
  - `/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/*`
  - `/api/projects/{project}/ready-tasks`
- **Verification:**
  - `test_planning_api.py` results
  - `just check` result
- **Deviations:** None
```
