# T22 — Plan & Task Orchestration product contract

**Branch:** `task/T22-plan-task-contract` · **Base:** `origin/main` (`a9e48ea`) · **Depends on:** Integrated main · **Blocks:** T23

## Goal

Establish the normative product contract, architecture decisions, requirements, and task briefs for the Plan & Task Orchestration milestone (Phase 4), ensuring that multi-agent task execution, DAG dependency tracking, database-level plan/tenant isolation, normalized requirement links with section validation, atomic leases, and AI plan generation are strictly defined and governed by PCS before production code is implemented.

## Owned files/modules

- `REQUIREMENTS.md` (decisions D18–D24, non-goals, functional requirements FR43–FR53, acceptance criteria AC28–AC33)
- `ROADMAP.md` (Phase 4 definition, tasks T22–T29, milestone status table)
- `tasks/PLAN-TASK-ORCHESTRATION.md` (milestone master implementation plan)
- `tasks/T22-plan-task-contract.md` (this task specification and handoff)
- `tasks/T23-plan-task-core.md`
- `tasks/T24-plan-task-api.md`
- `tasks/T25-planned-task-handoff.md`
- `tasks/T26-ai-plan-draft.md`
- `tasks/T27-plans-ui.md`
- `tasks/T28-ai-plan-ui.md`
- `tasks/T29-plan-task-integration.md`

Do not implement production backend or frontend code in this task.

## Non-goals

- Implementing SQL tables, SQLAlchemy models, or Alembic migrations (owned by T23).
- Adding MCP tools or HTTP routes (owned by T24).
- Modifying `prepare_task` or index retrieval code (owned by T25).
- Integrating AI generation providers (owned by T26).
- Building React components, hooks, or styles (owned by T27, T28).
- Running end-to-end milestone release gates (owned by T29).

## Invariants

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; task dependencies and requirement links enforce tenant and plan isolation via database composite foreign keys; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
- `INV-PLAN-2` (`fdab6d29-f527-4d13-91c2-6510a3309f2d`): Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4).
- `INV-PLAN-3` (`c212e6cb-a1e5-4e81-8301-4c6febae6739`): Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed.
- `INV-PLAN-4` (`d196d5d6-20fc-4771-ad07-f80397eda510`): Every plan task mutation appends an immutable event recording author, event type, prior state, new state, timestamp, and structured payload; events are never updated or deleted.
- `INV-PLAN-5` (`d55a6164-1772-49c2-b390-be8f988e203b`): Task preparation with task_id returns a role-neutral, token-bounded prompt with task details, dependency status, and linked contract rules; claim tokens, provider keys, and raw diffs are never emitted.
- `INV-PLAN-6` (`56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`): AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks.
- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Plans UI strictly uses DESIGN.md tokens with no literal visual values; mutations update UI only after server confirmation; zero false-success states.

## Requirements

- Add decisions D18–D24 and requirements FR43–FR53 and AC28–AC33 to `REQUIREMENTS.md`.
- Preserve D4: neither task completion nor AI generation output may infer requirement status.
- Add milestone non-goals (no agent process supervisor, no shell execution, no worktree automation, no GitHub sync, no RBAC).
- Author product requirement `R-086` (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`), invariants `INV-PLAN-1..7`, and criteria `AC-PLAN-1..13` in PCS via MCP.
- Update `ROADMAP.md` with Phase 4 tasks T22–T29 and status table.
- Author comprehensive milestone plan `tasks/PLAN-TASK-ORCHESTRATION.md` including database-enforced dependency isolation, complete lease lifecycle, nested HTTP routes, and sequenced shared integration seams.
- Author detailed task briefs for T23–T29 with sequenced shared integration seams, invariants, criteria, and verification commands.

## Acceptance checklist

- [x] Base branch is confirmed from latest integrated `origin/main` (`a9e48ea`), not from unmerged T17.
- [x] Status of previous tasks T18 (unstarted), T20 (under review), T21 (under review), and T17 (under review) is explicitly documented.
- [x] Decisions D18–D24 and non-goals are added to `REQUIREMENTS.md`.
- [x] Functional requirements FR43–FR53 and acceptance criteria AC28–AC33 are added to `REQUIREMENTS.md`.
- [x] Product requirement `R-086` (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`) is created and transitioned to `in-progress` in PCS.
- [x] Invariants `INV-PLAN-1` through `INV-PLAN-7` are authored in PCS with real IDs.
- [x] Criteria `AC-PLAN-1` through `AC-PLAN-13` are authored in PCS with real IDs and risk-appropriate independent review policies.
- [x] `ROADMAP.md` is updated with Phase 4 tasks and dependency table.
- [x] `tasks/PLAN-TASK-ORCHESTRATION.md` defines the complete milestone architecture, models, APIs, and non-goals.
- [x] Task briefs `tasks/T23-*.md` through `tasks/T29-*.md` are authored with sequenced shared integration seams, real PCS IDs, checklists, and handoff templates.
- [x] Database dependency isolation enforced via composite FKs `(task_id, plan_id, project_id)` and `(depends_on_task_id, plan_id, project_id)` referencing `plan_tasks`.
- [x] Event model isolation enforced via composite FK `(task_id, plan_id, project_id)` referencing `plan_tasks`.
- [x] Complete lease lifecycle defined with clear field behavior (`claim_token_hash`, `claimed_by`, `lease_expires_at`) across all transitions, including release revocation, reclaim, blocked cleanup, review expiry, and plan archival lease freeze.
- [x] Standardized nested task HTTP routes (`/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/*`) aligned across master plan, T24, T27, and T29 with URL-plan verification.
- [x] Event contract formalized with 10 event types and bounded, redacted JSONB payload schema.
- [x] Requirement links target section `requirements` via database check/composite FK discriminator and service validation.
- [x] Sequenced shared integration seams articulated for T24/T26 and T27/T28 without claiming false non-overlapping ownership.
- [x] T29 updated to require PostgreSQL-only migrations and correct pytest paths.
- [x] Trailing blank lines at EOF in `REQUIREMENTS.md` removed (`git diff origin/main --check` clean).
- [x] Live PCS contract for `R-086` updated via MCP without duplicate criteria.
- [x] Unified `in_review` lifecycle: canonical predicate in `list_ready_tasks`, atomic reclaim to `claimed` with fresh token/lease, old token revoked, and concurrent claims on unexpired `in_review` rejected.
- [x] Claim token strictly enforced on tasks with active leases without operator bypass; tokenless mutations permitted only when no lease exists or lease has expired; `archive_plan` confirmed as sole trusted administrative exception.
- [x] Heartbeat semantics formalized to preserve exact persisted status (`claimed -> claimed`, `in_progress -> in_progress`) without mutating status.
- [x] Normative D21 and FR48 fully synchronized with 10 event types (`created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`) and bounded, redacted structured payloads.
- [x] No production code in `server/src/` or `web/src/` was created or modified.
- [x] Verification commands (`just check`) pass cleanly.
- [x] Handoff section records allocated IDs, integration dependencies, and next steps.

## Required evidence

- Repository document review, PCS MCP tool outputs confirming created and updated requirement, invariants, and criteria.

## Verification

```bash
git diff origin/main --check
git diff --stat
just check
```

## Handoff

- **Branch:** `task/T22-plan-task-contract`
- **What was done:**
  - Researched existing contracts, decisions, and task handoffs (T17, T20, T21).
  - Confirmed dependency status:
    - `origin/main` is at `a9e48ea` (T16 merged).
    - T17 (`task/T17-codebase-guide-ui`) is in review at `14c3437`.
    - T18 is unstarted (no branch).
    - T20 (`task/T20-ai-provider-settings`) is in review at `6b85747`.
    - T21 (`task/T21-semantic-runtime-fallback`) is in review at `eecda22`.
    - Checked that T22–T29 were completely unused in the repository.
  - Authored Architecture Decisions D18–D24 and Non-Goals in `REQUIREMENTS.md`.
  - Authored Functional Requirements FR43–FR53 and Acceptance Criteria AC28–AC33 in `REQUIREMENTS.md`.
  - Registered product requirement `R-086` (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`) in PCS and transitioned to `in-progress`.
  - Authored Invariants `INV-PLAN-1` through `INV-PLAN-7` with real UUIDs in PCS via MCP.
  - Authored Acceptance Criteria `AC-PLAN-1` through `AC-PLAN-13` with real UUIDs in PCS via MCP.
  - Resolved Review Findings & Semantic Harmonization:
    1. **Unified `in_review` Lifecycle:**
       - Eliminated the contradiction between special review lease expiry and the canonical ready predicate.
       - Canonical ready predicate now explicitly includes expired `in_review` tasks: `task.status IN ('claimed', 'in_progress', 'in_review') AND task.lease_expires_at IS NOT NULL AND task.lease_expires_at < :now`.
       - `list_ready_tasks` returns expired `in_review` tasks under reclaimable status.
       - Calling `claim_task` on an expired `in_review` task atomically transitions it `in_review -> claimed`, issues a fresh token and lease TTL, and invalidates the previous token.
       - While an `in_review` task has an active unexpired lease (`lease_expires_at >= now()`), concurrent claim attempts by other workers fail with HTTP 409 Conflict.
       - Persisted status is never automatically updated prior to an explicit claim.
       - UI displays expired `in_review` tasks with the "Expired - Reclaimable" badge.
       - Aligned master plan, T23, T24, T27, and T29 with explicit unit and integration test expectations.
    2. **Strict Active Lease Token Enforcement (No Operator Bypass):**
       - Aligned D20, FR47, and transition matrix to eliminate unauthenticated "operator" bypasses of active leases.
       - Any task holding an active unexpired lease strictly requires presenting the valid current claim token for `set_task_status`, `complete_task`, and direct cancellation.
       - Callers cannot self-declare as "operator" to bypass an active lease; tokenless calls on active leases fail with HTTP 409 Conflict (`ClaimConflictError`).
       - Tokenless mutations are permitted ONLY when:
         - The task has no active lease (`pending`, `ready`, `blocked` where lease fields are NULL); OR
         - The lease has expired and the transition is permitted by contract (e.g. trusted plan-level completion of an expired `in_review` task in the single-user model).
       - `archive_plan` is formalized as the sole trusted administrative exception: it atomically revokes all active leases across all tasks in the plan, sets non-completed tasks to `cancelled`, appends audit events, and transitions the plan to `archived`.
       - Stale, expired, released, or reclaimed tokens are always rejected with HTTP 409 Conflict (`StaleClaimTokenError`).
       - Synchronized across `REQUIREMENTS.md`, master plan, T23, T24, T27, and T29 without adding RBAC (preserving D24 non-goals).
    3. **Heartbeat Semantics & Status Preservation:**
       - Fixed heartbeat transition description: heartbeat validates the active token and extends `lease_expires_at = now() + ttl` while strictly preserving exact persisted status (`claimed -> claimed`, `in_progress -> in_progress`).
       - Heartbeat never mutates a `claimed` task to `in_progress`.
       - Retains `claim_token_hash` and `claimed_by`, appends a `heartbeat` event.
       - Added test expectations across T23, T24, T27, and T29.
    4. **Normative D21 and Event Taxonomy Synchronization:**
       - Updated D21 and FR48 in `REQUIREMENTS.md` to enumerate the full 10 discrete event types (`created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`) with bounded, redacted structured payload schemas (mirroring D5).
       - Synchronized event definitions across `PLAN-TASK-ORCHESTRATION.md`, T23, T24, T27, and T29.
       - Verified that live PCS invariant `INV-PLAN-4` and criterion `AC-PLAN-6` already encompass these semantics.
    5. **Database Dependency Isolation:**
       - Added `project_id` and `plan_id` to `task_dependencies`.
       - Enforced composite foreign keys on both sides:
         - `(task_id, plan_id, project_id)` -> `plan_tasks(id, plan_id, project_id)`
         - `(depends_on_task_id, plan_id, project_id)` -> `plan_tasks(id, plan_id, project_id)`
       - Added `UniqueConstraint("id", "plan_id", "project_id", name="uq_plan_tasks_id_plan_project")` on `plan_tasks`.
       - Enforced event isolation via composite FK `(task_id, plan_id, project_id)` on `plan_task_events`.
    6. **Requirement Link Section Discrimination:**
       - Added `requirement_section = mapped_column(String(32), nullable=False, server_default="requirements")` with `CheckConstraint("requirement_section = 'requirements'")`.
       - Added composite FK `(requirement_id, requirement_section)` referencing `context_entries(id, section)` matching the repo's `RequirementInvariant` pattern.
       - Service validation confirms `section == 'requirements'` and rejects non-requirement entries.
    7. **Standardized Nested HTTP Routes:**
       - All task routes standardized to `/api/projects/{project}/plans/{plan_id}/tasks/{task_id}/*`.
       - Handlers verify task belongs to URL plan and project, returning 404 if mismatched.
    8. **Sequenced Shared Integration Seams:**
       - Replaced false "non-overlapping" claims with clearly documented sequenced shared seams for T24/T26 (`planning_tools.py`, `planning_routes.py`) and T27/T28 (`planning.ts`, `PlansView.tsx`).
    9. **PostgreSQL Specifics & Clean Pytest Paths:**
       - Updated T29 to require PostgreSQL migrations (no SQLite).
       - Fixed pytest invocation paths to `cd server && uv run pytest tests/...`.
  - Updated `ROADMAP.md` with Phase 4 tasks and set T22 status to `in review`.
  - Authored `tasks/PLAN-TASK-ORCHESTRATION.md` as the master milestone implementation architecture.
  - Authored detailed task briefs `tasks/T23-plan-task-core.md` through `tasks/T29-plan-task-integration.md`.
  - Verified no production code was touched; ran `just check` to verify repository cleanliness.
- **Allocated PCS IDs:**
  - Requirement: `R-086` (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`)
  - Invariants:
    - `INV-PLAN-1`: `952fcb34-050f-42d5-860b-d3c421131c26`
    - `INV-PLAN-2`: `fdab6d29-f527-4d13-91c2-6510a3309f2d`
    - `INV-PLAN-3`: `c212e6cb-a1e5-4e81-8301-4c6febae6739`
    - `INV-PLAN-4`: `d196d5d6-20fc-4771-ad07-f80397eda510`
    - `INV-PLAN-5`: `d55a6164-1772-49c2-b390-be8f988e203b`
    - `INV-PLAN-6`: `56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`
    - `INV-PLAN-7`: `78c2bf3b-1e07-4a6b-b80f-3272f56200b9`
  - Acceptance Criteria:
    - `AC-PLAN-1`: `bcfa212d-eae5-42c6-b98a-7ba78cbfcb75`
    - `AC-PLAN-2`: `911bab97-9662-4acb-8efe-4cece2aeab7c`
    - `AC-PLAN-3`: `42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b`
    - `AC-PLAN-4`: `8fc004f9-b782-4158-afa5-7ceb693a4315`
    - `AC-PLAN-5`: `05f02bf6-ab90-4f28-9002-2e88d69a07a1`
    - `AC-PLAN-6`: `e671ec47-f6b3-4e18-8fbf-5606f5afe90b`
    - `AC-PLAN-7`: `eeb30422-628b-4a3d-bd01-b267c42e8a2f`
    - `AC-PLAN-8`: `eabc07be-3c22-4227-ae97-9b63bc2ea3f4`
    - `AC-PLAN-9`: `f9d99c08-7383-48f9-932c-94e1a5c24b35`
    - `AC-PLAN-10`: `9521864a-18e2-498b-8b09-b24e180580d2`
    - `AC-PLAN-11`: `98f519b5-6bed-491c-b2a7-ed4150118c91`
    - `AC-PLAN-12`: `5187dff3-9823-49c8-9307-669b99b24976`
    - `AC-PLAN-13`: `c89b24eb-9e64-4e8f-ac83-022f42bd7d14`
- **Integration Dependencies:**
  - T23 can start immediately on `task/T23-plan-task-core` based on T22.
  - T26 and T28 require T20 AI provider settings to be merged into main before production deployment, but can develop against the T20 interface seams in the interim.
