# T29 — Plan and Task Orchestration Integration and Release Gate

**Branch:** `task/T29-plan-task-integration` · **Depends on:** T25, T26, T27, T28 · **Blocks:** None (Milestone Release)

## Goal

Execute end-to-end cross-layer verification for Phase 4 Plan & Task Orchestration, update public reference documentation (`docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `README.md`), verify migration upgrade/downgrade from scratch on PostgreSQL, record final compliance evidence, and pass the PCS release close gate for requirement `R-086`.

## Owned files/modules

- `server/tests/test_planning_integration.py` (cross-layer integration, concurrency, security, and performance test suite)
- `docs/mcp-reference.md` (documentation of all new planning MCP tools)
- `docs/http-api.md` (documentation of all new planning HTTP routes)
- `docs/architecture.md` (data model diagrams, lease lifecycle, and DAG resolution mechanics)
- `README.md` (updated feature overview and workflow guide)
- `ROADMAP.md` (status updates for completed Phase 4 tasks)
- `tasks/T29-plan-task-integration.md`
- Minimal cross-task fixes strictly demonstrated by failing integration tests (must be documented in handoff)

Do not add new unsolicited feature endpoints, alter existing requirements contracts, or introduce unverified dependencies.

## Non-goals

- Agent dispatch, background execution workers, or Git worktree automation (D24).
- Modifying earlier merged task architecture without clear failing integration tests.
- Weakening checks, adding `# type: ignore`, or bypassing the close gate.

## Invariants

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; dependency graph is strictly acyclic; requirement links use normalized plan_task_requirements with composite foreign keys; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-2` (`fdab6d29-f527-4d13-91c2-6510a3309f2d`): Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4).
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.
- `INV-PLAN-4` (`d196d5d6-20fc-4771-ad07-f80397eda510`): Every plan task mutation appends an immutable event recording author, event type, prior state, new state, timestamp, and structured payload; events are never updated or deleted.
- `INV-PLAN-5` (`d55a6164-1772-49c2-b390-be8f988e203b`): Planned task handoff produces bounded, role-neutral prompts linking task contracts and retrieval context without exposing secrets.
- `INV-PLAN-6` (`56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`): AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks.
- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Web UI operations reflect server-confirmed truth without speculative optimistic writes; mutations invalidate project queries; DESIGN.md tokens are followed.

## Requirements

- End-to-end workflow verification:
  - Create draft plan manually and via approved AI draft.
  - Activate plan and discover initial ready tasks.
  - Two concurrent agents attempt claiming the same task: exactly one succeeds with a valid claim token; the second receives a 409 Conflict.
  - Heartbeat extends lease; expired lease allows another agent to reclaim.
  - Stale claim token is rejected when attempting to update or complete a reclaimed task.
  - Completing task unlocks downstream dependent tasks in `list_ready_tasks`.
  - Task completion preserves requirement status unchanged (D4).
  - Attempting to complete plan with incomplete required tasks fails with validation error.
  - Task event history contains complete, chronologically ordered audit trail with structured payload data.
  - Cross-project requests cannot access or mutate plans/tasks.
  - `prepare_task(task_id=...)` outputs complete Markdown prompt without secrets or claim tokens.
  - Cancelled or rejected AI draft leaves zero rows in all planning tables.
  - Web UI accurately reflects server-confirmed state following mutations and page refreshes.
- Database and PostgreSQL migration verification:
  - Run database migration from completely empty PostgreSQL database (`just migrate`).
  - Verify migration upgrade from existing integrated schema to planning head.
  - Verify migration downgrade (`uv run alembic downgrade -1`) and re-upgrade (`uv run alembic upgrade head`) on PostgreSQL.
- Security and audit verification:
  - Structured logs contain no claim tokens, authorization tokens, or raw secrets.
  - All public tool and route responses redact claim tokens on read operations.
- Documentation updates:
  - Update `docs/mcp-reference.md` with complete documentation of all planning MCP tools (including `update_plan` and `archive_plan`).
  - Update `docs/http-api.md` with endpoints, request/response schemas, and status codes.
  - Update `docs/architecture.md` with planning domain architecture and sequence diagrams.
  - Update `README.md` with Phase 4 orchestration capabilities.
- Compliance and Close Gate:
  - Author and attach test evidence for all acceptance criteria `AC-PLAN-1` through `AC-PLAN-13` referencing final commit SHA.
  - Conduct independent review on all criteria requiring review (`AC-PLAN-3`, `AC-PLAN-7`, `AC-PLAN-8`, `AC-PLAN-9`, `AC-PLAN-12`).
  - Run `review_requirement_compliance` and `evaluate_close_gate` via PCS MCP.
  - Only transition requirement `R-086` to `done` after close gate passes cleanly.

## Acceptance checklist

- [ ] `AC-PLAN-13` (`c89b24eb-9e64-4e8f-ac83-022f42bd7d14`): End-to-end integration verifies full planning lifecycle, migration clean from empty PostgreSQL DB, and just check pass (T29).
- [ ] End-to-end integration test suite passes in `server/tests/test_planning_integration.py`.
- [ ] Concurrency and lease collision tests pass reliably under parallel execution.
- [ ] Database migration cleanly runs on blank PostgreSQL target and upgrades from integrated head.
- [ ] Downgrade to down_revision and upgrade back to head verified without data corruption.
- [ ] Zero secret leaks verified in logs and API read endpoints.
- [ ] `docs/mcp-reference.md` and `docs/http-api.md` updated with all planning endpoints.
- [ ] `docs/architecture.md` updated with planning and leasing mechanics.
- [ ] Full repo test suite and `just check` fully green.
- [ ] All evidence recorded with valid final git SHA and independent review attached.
- [ ] `evaluate_close_gate` returns `passed=true` for requirement `R-086`.

## Required evidence

- Complete test suite output from `server/tests/test_planning_integration.py`.
- Migration run logs verifying upgrade, downgrade, and clean database bootstrap on PostgreSQL.
- Independent review verification on security, concurrency, and D4 compliance.
- PCS evidence recorded for criteria `AC-PLAN-1` through `AC-PLAN-13`.
- Close gate report demonstrating zero violations.

## Verification

```bash
just test
just check
cd server && uv run pytest tests/test_planning_integration.py -v
cd server && uv run alembic downgrade -1 && uv run alembic upgrade head
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T29-plan-task-integration`
- **What was done:**
  - Implemented end-to-end integration test suite covering planning workflows
  - Verified migration upgrade/downgrade/upgrade from blank PostgreSQL database
  - Updated reference documentation (`docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `README.md`)
  - Recorded contract compliance evidence for all Phase 4 criteria
  - Evaluated release close gate for requirement `R-086`
- **Verification:**
  - Full `just check` result
  - Integration test suite output
  - Close gate output: `passed=true`, 0 blockers
- **Deviations:** None
```
