# T22 — Plan & Task Orchestration product contract

**Branch:** `task/T22-plan-task-contract` · **Base:** `origin/main` (`a9e48ea`) · **Depends on:** Integrated main · **Blocks:** T23

## Goal

Establish the normative product contract, architecture decisions, requirements, and task briefs for the Plan & Task Orchestration milestone (Phase 4), ensuring that multi-agent task execution, DAG dependency tracking, normalized requirement links, atomic leases, and AI plan generation are strictly defined and governed by PCS before production code is implemented.

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

- `INV-PLAN-1` (`952fcb34-050f-42d5-860b-d3c421131c26`): Tasks belong to one plan and one project; dependency graph is strictly acyclic; requirement links use normalized plan_task_requirements with composite foreign keys; self-dependencies, cycles, cross-plan, and cross-project references are rejected.
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
- Author comprehensive milestone plan `tasks/PLAN-TASK-ORCHESTRATION.md` including state machine, normalized requirement link schema, structured event history, and Starlette/FastMCP architecture.
- Author detailed task briefs for T23–T29 with strict non-overlapping file ownership, invariants, criteria, and verification commands.

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
- [x] Task briefs `tasks/T23-*.md` through `tasks/T29-*.md` are authored with non-overlapping module boundaries, real PCS IDs, checklists, and handoff templates.
- [x] Contract additions for `update_plan` and `archive_plan` incorporated into T24, T27, and master plan.
- [x] Plan task state machine formally defined with 8 states, transition matrix, actors, and canonical ready predicate across T23, T24, T26, T27, and master plan.
- [x] Normalized `plan_task_requirements` junction table specified with composite FKs and project isolation.
- [x] Starlette + FastMCP framework guidance aligned with repository patterns (no FastAPI, no `router.py`).
- [x] Task history specified with structured, redacted JSONB payload schema.
- [x] T29 updated to require PostgreSQL-only migrations and correct pytest paths.
- [x] Trailing blank lines at EOF in `REQUIREMENTS.md` removed (`git diff origin/main --check` clean).
- [x] Live PCS contract for `R-086` updated via MCP without duplicate criteria.
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
  - Resolved Review Findings 1–8:
    1. Added `update_plan` and `archive_plan` to T24 MCP tools, Starlette HTTP routes, schemas, and T27 UI controls.
    2. Formalized Plan Task State Machine: 8 states (`pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`), transition rules, actors, persisted vs derived eligibility, and single canonical ready predicate.
    3. Replaced loose JSONB requirement IDs with normalized `plan_task_requirements` junction table enforcing database-level composite foreign keys and project isolation.
    4. Corrected framework references to Starlette (`mcp.custom_route`) and FastMCP; removed all references to FastAPI, `router.py`, and `app.py`.
    5. Specified structured, redacted JSONB payload schema for `plan_task_events` and updated history APIs/UI.
    6. Refined T29 verification: removed SQLite; specified PostgreSQL clean migration, upgrade, and downgrade/re-upgrade; corrected pytest paths.
    7. Eliminated trailing blank lines at EOF in `REQUIREMENTS.md` (`git diff origin/main --check` clean).
    8. Updated live contract for `R-086` via PCS MCP tools (`update_requirement_invariant`, `update_acceptance_criterion`) without creating duplicate records or using raw SQL.
  - Updated `ROADMAP.md` with Phase 4 tasks and set T22 status to `in review`.
  - Authored `tasks/PLAN-TASK-ORCHESTRATION.md` as the master milestone implementation architecture.
  - Authored detailed task briefs `tasks/T23-plan-task-core.md` through `tasks/T29-plan-task-integration.md` with strictly non-overlapping file ownership and full checklists.
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
