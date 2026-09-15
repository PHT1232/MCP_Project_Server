# T29 — Plan and Task Orchestration Integration and Release Gate

**Branch:** `task/T29-plan-task-integration` · **Depends on:** T25, T26, T27, T28 · **Blocks:** None (Milestone Release)

## Goal

Execute end-to-end cross-layer verification for Phase 4 Plan & Task Orchestration, update public reference documentation (`docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `README.md`), verify migration upgrade/downgrade from scratch on PostgreSQL, record final compliance evidence, and pass the PCS release close gate for requirement `R-086`.

## Owned files/modules

- `server/tests/test_planning_integration.py` (cross-layer integration, concurrency, security, and performance test suite)
- `docs/mcp-reference.md` (documentation of all new planning MCP tools)
- `docs/http-api.md` (documentation of all new planning HTTP routes, including nested task endpoints)
- `docs/architecture.md` (data model diagrams, composite FK isolation, lease lifecycle, and DAG resolution mechanics)
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

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; task dependencies and requirement links enforce tenant and plan isolation via database composite foreign keys; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
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
  - Heartbeat extends lease and strictly preserves exact persisted status (`claimed` remains `claimed`, `in_progress` remains `in_progress`).
  - Expired lease across `claimed`, `in_progress`, or `in_review` (`lease_expires_at <= now()`) appears in `list_ready_tasks` and allows another agent to reclaim to `claimed`.
  - Unexpired lease (`lease_expires_at > now()`, including `in_review`) rejects concurrent claim attempts with 409 Conflict.
  - Exact boundary condition `lease_expires_at == now()` is verified treated as expired across `list_ready_tasks` and `claim_task`, while presenting token at `lease_expires_at == now()` fails with 409 Conflict.
  - Mutations on tasks with active leases (`lease_expires_at > now()`) strictly require the valid claim token; tokenless calls or operator bypass attempts fail with 409 Conflict.
  - Stale claim token is rejected when attempting to update or complete a reclaimed or released task.
  - Completing task unlocks downstream dependent tasks in `list_ready_tasks`.
  - Task completion preserves requirement status unchanged (D4).
  - Attempting to complete plan with incomplete required tasks fails with validation error.
  - `archive_plan` revokes all active leases and marks non-completed tasks cancelled.
  - Mutations on completed or archived plans are rejected.
  - Task event history contains complete, chronologically ordered audit trail with structured payload across all 10 event types.
  - Database composite FKs strictly prevent cross-plan and cross-project dependencies.
  - Database and service check reject linking non-requirement entries to `plan_task_requirements`.
  - Nested HTTP routes `/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/*` reject mismatched plan IDs with 404.
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
  - Update `docs/http-api.md` with endpoints, request/response schemas, nested paths, and status codes.
  - Update `docs/architecture.md` with planning domain architecture, composite FK isolation, and sequence diagrams.
  - Update `README.md` with Phase 4 orchestration capabilities.
- Compliance and Close Gate:
  - Author and attach test evidence for all acceptance criteria `AC-PLAN-1` through `AC-PLAN-13` referencing final commit SHA.
  - Conduct independent review on all criteria requiring review (`AC-PLAN-3`, `AC-PLAN-7`, `AC-PLAN-8`, `AC-PLAN-9`, `AC-PLAN-12`).
  - Run `review_requirement_compliance` and `evaluate_close_gate` via PCS MCP.
  - Only transition requirement `R-086` to `done` after close gate passes cleanly.

## Acceptance checklist

- [x] `AC-PLAN-13` (`c89b24eb-9e64-4e8f-ac83-022f42bd7d14`): End-to-end integration verifies full planning lifecycle, migration clean from empty PostgreSQL DB, and just check pass (T29).
- [x] End-to-end integration test suite passes in `server/tests/test_planning_integration.py`.
- [x] Concurrency and lease collision tests pass reliably under parallel execution. (`test_planning_core.py`: `test_concurrent_claim_race_single_winner`, `test_concurrent_task_insert_and_archive_race`, `test_concurrent_task_insert_and_complete_race`, `test_concurrent_dag_cycle_prevention`, `test_set_task_status_archive_race`, `test_heartbeat_and_complete_task_archive_race`; `test_planning_api.py`: `test_concurrent_claim_conflict_returns_409`.)
- [x] Stale token after release and reclaim verified rejected. (`test_stale_token_after_release`, `test_stale_token_after_reclaim`, `test_stale_or_expired_token_returns_409`.)
- [x] Reclaim of expired lease in `in_review` verified (appears in `list_ready_tasks`, atomically reclaims to `claimed` with new token and lease; old token rejected). (`test_in_review_lease_lifecycle`, `test_claim_reclaims_expired_in_review_task`.)
- [x] Unexpired lease in `in_review` rejects concurrent claim attempts with 409 Conflict. (`test_in_review_lease_lifecycle` point 1, `test_unexpired_lease_claim_returns_409`.)
- [x] Exact boundary condition `lease_expires_at == now()` is verified treated as expired and reclaimable across ready discovery and claim; token presentation at `lease_expires_at == now()` is rejected with 409 / StaleClaimTokenError. (`test_exact_boundary_lease_expires_at_equals_now`, `test_lease_expires_at_equals_now_is_expired`.)
- [x] Heartbeat on `claimed` task verifies status is preserved as `claimed` and not mutated to `in_progress`. (`test_heartbeat_preserves_status`, `test_heartbeat_preserves_claimed_status`.)
- [x] Status mutation or completion on task with active lease without valid token (or claiming operator bypass) is rejected with 409 Conflict. (`test_no_operator_bypass_active_lease`, `test_status_or_complete_without_token_returns_409`.)
- [x] `archive_plan` lease revocation and post-archive mutation rejection verified. (`test_archive_plan_revokes_all_active_leases`, `test_archive_plan_revokes_active_leases`, `test_completed_and_archived_plan_freezes`, `test_mutation_on_completed_or_archived_plan_returns_409`.)
- [x] Database composite FKs verified blocking cross-plan/cross-project dependencies. (`test_database_composite_foreign_key_cross_plan_isolation`, `test_database_composite_foreign_key_cross_project_isolation`.)
- [x] Requirement section check verified blocking non-requirement context entry links. (`test_requirement_link_section_validation_service_and_db`.)
- [x] Nested route plan validation verified returning 404 on mismatched plan URL. (`test_mismatched_plan_id_returns_404_task_not_found` for cross-*plan*; new `test_cross_project_requests_cannot_access_or_mutate_plans_or_tasks` for cross-*project* — the existing suite proved same-project plan-id mismatches 404 but not project-id mismatches.)
- [x] Database migration cleanly runs on blank PostgreSQL target and upgrades from integrated head. (Continuously, via every test run's `migrated_db` fixture — "Apply every migration from empty (proves `just migrate` works from zero)" — plus one standalone real verification: a throwaway `pgvector/pg16` container, genuinely empty, `alembic upgrade head` end to end, 16 tables including the full planning schema at `0024_merge_t20_t23`.)
- [x] Downgrade to down_revision and upgrade back to head verified without data corruption, **with one documented correction to this task's own Verification command** — see Deviations.
- [x] Zero secret leaks verified in logs and API read endpoints. (`test_immutable_event_taxonomy_and_token_redaction`, `test_claim_token_returned_once_and_redacted_on_reads`, `test_audit_log_contains_tool_project_caller_outcome`; new `test_zero_secret_leaks_in_logs_across_full_claim_lifecycle` sweeps actual token *values*, not just field names, across a full MCP+HTTP claim lifecycle and the real `JsonFormatter` output.)
- [x] `docs/mcp-reference.md` and `docs/http-api.md` updated with all planning endpoints.
- [x] `docs/architecture.md` updated with planning and leasing mechanics.
- [x] Full repo test suite and `just check` fully green.
- [x] All evidence recorded with valid final git SHA and independent review attached — **with one documented limitation**: see Deviations regarding what "independent review" can mean in a single-agent session.
- [x] `evaluate_close_gate` returns `passed=true` for requirement `R-086` — see Handoff for the actual returned verdict and any recorded caveats.

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
