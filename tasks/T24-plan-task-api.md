# T24 — Plan & Task MCP and HTTP API surface

**Branch:** `task/T24-plan-task-api` · **Depends on:** T23 · **Blocks:** T25, T26, T27

## Goal

Expose the planning domain via audited, typed MCP tools and FastAPI HTTP endpoints with strict input validation, stable HTTP status mappings, and token redaction, delegating all business logic to `pcs.planning.service`.

## Owned files/modules

- New `server/src/pcs/mcp/planning_tools.py`
- New `server/src/pcs/web_api/planning_routes.py`
- Minimal registration in `server/src/pcs/mcp/server.py`
- Minimal router mount in `server/src/pcs/web_api/router.py` (or `app.py`)
- `server/tests/test_planning_api.py`
- `tasks/T24-plan-task-api.md`

Do not touch `pcs.index.retrieval`, frontend code, or AI generators.

## Non-goals

- Implementing domain models, migrations, or database queries (owned by T23).
- Modifying `prepare_task` or index retrieval (owned by T25).
- Implementing AI draft generation logic (owned by T26).
- Building frontend views or components (owned by T27).

## Invariants

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.

## Requirements

- Expose typed, audited MCP tools in `pcs.mcp.planning_tools`:
  - `create_plan`, `create_plan_with_tasks`, `list_plans`, `get_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`, `activate_plan`
  - `list_ready_tasks`, `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`, `get_task_history`
- Expose matching HTTP routes in `pcs.web_api.planning_routes` under `/api/projects/{project}/plans`:
  - `POST /api/projects/{project}/plans` (`create_plan`)
  - `POST /api/projects/{project}/plans/with-tasks` (`create_plan_with_tasks`)
  - `GET /api/projects/{project}/plans` (`list_plans`)
  - `GET /api/projects/{project}/plans/{plan_id}` (`get_plan`)
  - `POST /api/projects/{project}/plans/{plan_id}/tasks` (`add_plan_task`)
  - `PATCH /api/projects/{project}/plans/{plan_id}/tasks/{task_id}` (`update_plan_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/dependencies` (`add_task_dependency`)
  - `POST /api/projects/{project}/plans/{plan_id}/activate` (`activate_plan`)
  - `GET /api/projects/{project}/ready-tasks` (`list_ready_tasks`)
  - `POST /api/projects/{project}/tasks/{task_id}/claim` (`claim_task`)
  - `POST /api/projects/{project}/tasks/{task_id}/heartbeat` (`heartbeat_task`)
  - `POST /api/projects/{project}/tasks/{task_id}/release` (`release_task`)
  - `POST /api/projects/{project}/tasks/{task_id}/status` (`set_task_status`)
  - `POST /api/projects/{project}/tasks/{task_id}/complete` (`complete_task`)
  - `POST /api/projects/{project}/plans/{plan_id}/complete` (`complete_plan`)
  - `GET /api/projects/{project}/tasks/{task_id}/history` (`get_task_history`)
- Delegate all logic to `pcs.planning.service`; do not duplicate validation.
- Emit structured audit log lines (NFR6) recording tool, project, caller, and outcome without leaking claim tokens or request secrets.
- Map validation/conflict/not-found service exceptions to stable HTTP status codes (400, 404, 409, 422).
- Reject malformed JSON, unknown fields, type coercions, empty patch bodies, and cross-project IDs.
- Redact claim tokens: only `claim_task` response includes the raw token; all other reads emit only `claimed_by` and `lease_expires_at`.

## Acceptance checklist

- [ ] `AC-PLAN-7` (`eeb30422-628b-4a3d-bd01-b267c42e8a2f`): Audited MCP and HTTP planning tools expose typed operations with token redaction and input validation.
- [ ] Every MCP tool call emits structured audit log containing tool, project, caller, outcome (NFR6).
- [ ] `claim_task` returns raw claim token exactly once; subsequent reads of task detail and history omit token and token hash.
- [ ] Unknown fields, malformed JSON, and empty patch bodies return HTTP 400/422.
- [ ] Concurrent claim conflict returns clean 409 / ConflictError in MCP and HTTP.
- [ ] MCP tools and HTTP routes return identical typed JSON response envelopes.
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
  - `create_plan`, `create_plan_with_tasks`, `list_plans`, `get_plan`
  - `add_plan_task`, `update_plan_task`, `add_task_dependency`, `activate_plan`
  - `list_ready_tasks`, `claim_task`, `heartbeat_task`, `release_task`
  - `set_task_status`, `complete_task`, `complete_plan`, `get_task_history`
- **Public HTTP Endpoints:**
  - `/api/projects/{project}/plans/*`
  - `/api/projects/{project}/ready-tasks`
  - `/api/projects/{project}/tasks/{task_id}/*`
- **Verification:**
  - `test_planning_api.py` results
  - `just check` result
- **Deviations:** None
```
