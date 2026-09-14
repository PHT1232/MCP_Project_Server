# Plan & Task Orchestration — Implementation Plan

**Requirement:** `R-086` (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`)
**Contract:** `INV-PLAN-1..7`, `AC-PLAN-1..13`

## 1. Problem Statement

While PCS provides shared project context, full-codebase search, and compact requirement contracts, agent work across non-trivial milestones remains fragmented:

1. **No structured work decomposition:** Multi-agent workflows rely on free-form prompts or external text checklists without machine-verifiable task boundaries or prerequisite tracking.
2. **Missing dependency ordering:** Complex milestones require execution order (e.g. core model before API before frontend). Without deterministic DAG constraints, agents attempt downstream tasks prematurely.
3. **Coordination races:** Concurrent agent sessions attempting the same project lack concurrency-safe claim mechanisms, causing duplicate work or colliding changes.
4. **Context loss during handoff:** Spawning an agent for a task requires manually assembling context, dependencies, relevant requirement contracts, and guidelines into a bespoke prompt.
5. **No audit trail of execution:** Operational task transitions (who claimed what, when, and how it completed) are unrecorded, making multi-session coordination opaque.

## 2. Product Outcome

Turn PCS into a deterministic plan and task orchestration hub that coordinates human and AI agent execution without becoming a bloated runtime worker:

- **Deterministic DAG Plans:** Plans decompose milestones into ordered tasks with acyclic prerequisite dependencies and strict project isolation.
- **Atomic Claim Leases:** Workers claim ready tasks via atomic time-bounded leases with ephemeral one-time tokens, preventing race conditions and permitting expired task reclamation.
- **Append-Only History:** All task mutations record immutable event audit records.
- **Self-Contained Handoffs:** `prepare_task(task_id=...)` generates role-neutral, token-bounded Markdown prompts containing task objectives, acceptance criteria, dependency state, and contract rules.
- **Advisory AI Plan Generation:** AI draft generation proposes candidate task DAGs using secure T20 settings without persisting database records until explicit human review and approval.
- **Plans Web Interface:** A dedicated `/projects/:project/plans` interface renders task DAGs, tracks lease states, filters ready tasks, and facilitates draft reviews using `DESIGN.md` tokens.
- **Preservation of D4:** Task and plan completion track operational progress and never automatically modify requirement verification status.

## 3. Locked Decisions

| Decision | Summary |
|---|---|
| **D18** | **Deterministic Plan & Task DAG:** Plans contain tasks with explicit DAG dependencies. Self-dependencies, dependency cycles, cross-plan, and cross-project links are rejected by service validation and database constraints. |
| **D19** | **Requirement Independence (Preserve D4):** Task completion never mutates requirement status or close-gate state. Tasks track operational execution; requirements represent verified product contracts governed strictly by the evidence ledger and close gate. |
| **D20** | **Atomic Exclusive Leases & Ephemeral Tokens:** Claiming a task atomically allocates an expiring lease with TTL and returns a cryptographically random one-time secret token. Mutating a claimed task requires presenting the valid token. Expired leases can be reclaimed safely. |
| **D21** | **Immutable Task Event Audit Trail:** Every task mutation (creation, claim, heartbeat, release, status change, completion) appends an immutable event row recording author, event type, prior state, new state, and timestamp (mirroring D5). |
| **D22** | **Bounded Role-Neutral Task Handoff Prompt:** `prepare_task(task_id=...)` returns a token-budgeted Markdown prompt containing task objective, acceptance criteria, dependency state, and linked requirement contracts without emitting secrets, tokens, or raw diffs. |
| **D23** | **Advisory AI Plan Generation with Human Approval:** `generate_plan_draft` is strictly read-only and creates zero database entities. Persisting an AI proposal requires explicit caller review and approval via atomic `create_plan_with_tasks`. |
| **D24** | **Milestone Execution Boundaries (Non-goals):** Agent process spawning/dispatch, local shell or container execution, Git worktree orchestration, GitHub issue/PR sync, and fine-grained authorization are non-goals for this milestone. |

## 4. Non-Goals

- **No process supervisor or task execution worker:** PCS does not spawn subagents, manage container runtimes, supervise shell sessions, or execute shell commands.
- **No Git worktree or branch manager:** PCS does not create worktrees, checkout branches, or automate git commits.
- **No external issue tracker sync:** No bidirectional sync with GitHub Issues, Jira, or Linear in this milestone.
- **No fine-grained multi-user authorization:** Single-user/tailnet security model (D2) is preserved; no per-agent ACLs or role-based access control.

## 5. Delivery Sequence & Dependency Graph

```text
T22 (Product contract & briefs)
 └── T23 (Plan & task core model and service)
      └── T24 (Planning MCP tools & HTTP API)
           ├── T25 (Planned task handoff & prompt generation)
           ├── T26 (Advisory AI plan draft generation) [also depends on T20]
           └── T27 (Plans frontend view & components)
                └── T28 (AI planning UI & draft review modal) [depends on T25, T26, T27]
                     └── T29 (Integration, migration roundtrip, release gate) [depends on T25-T28]
```

### Integration Dependencies Note
- **T20 (Admin-managed AI provider settings):** Currently implemented on branch `task/T20-ai-provider-settings` (commit `6b85747`) and under review. T26 depends on T20's persisted summary-provider settings and validated endpoint security.
- **T21 (Semantic query runtime fallback):** Implemented on branch `task/T21-semantic-runtime-fallback` (commit `eecda22`) and under review. Independent of planning tasks.
- **T17 (Codebase Guide frontend):** Implemented on branch `task/T17-codebase-guide-ui` (commit `14c3437`) and under review. Independent of planning tasks.
- **T18 (Integration orchestrator):** Not started. Planning tasks do not depend on T18.

## 6. Data Model & Database Architecture

All planning tables live in PostgreSQL under the standard schema with composite foreign keys enforcing strict project isolation:

### `plans` Table
- `id` (UUID, PK)
- `project_id` (UUID, FK -> `projects.id` ON DELETE CASCADE)
- `title` (VARCHAR(160), NOT NULL)
- `goal` (TEXT, NOT NULL, max 8000 chars)
- `status` (VARCHAR(32), NOT NULL, default `'draft'`): `draft`, `active`, `completed`, `archived`
- `created_at` (TIMESTAMPTZ, NOT NULL)
- `updated_at` (TIMESTAMPTZ, NOT NULL)
- `author` (VARCHAR(120), NOT NULL)

### `plan_tasks` Table
- `id` (UUID, PK)
- `plan_id` (UUID, FK -> `plans.id` ON DELETE CASCADE)
- `project_id` (UUID, FK -> `projects.id` ON DELETE CASCADE)
- `local_task_id` (VARCHAR(32), NOT NULL): Unique local slug or key within the plan (e.g. `T01`, `T02`)
- `title` (VARCHAR(160), NOT NULL)
- `objective` (TEXT, NOT NULL, max 8000 chars)
- `acceptance_criteria` (JSONB, NOT NULL, list of strings)
- `linked_files` (JSONB, NOT NULL, list of strings)
- `requirement_ids` (JSONB, NOT NULL, list of requirement UUIDs verified against `context_entries.id`)
- `priority` (INT, NOT NULL, default 0)
- `status` (VARCHAR(32), NOT NULL, default `'pending'`): `pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`
- `claim_token_hash` (VARCHAR(64), NULL): SHA-256 hash of the current active claim token
- `claimed_by` (VARCHAR(120), NULL): Identity of worker holding the lease
- `lease_expires_at` (TIMESTAMPTZ, NULL): Expiration timestamp of active claim lease
- `created_at` (TIMESTAMPTZ, NOT NULL)
- `updated_at` (TIMESTAMPTZ, NOT NULL)
- Composite Unique Constraint: `(plan_id, local_task_id)`

### `task_dependencies` Table
- `plan_id` (UUID, NOT NULL)
- `task_id` (UUID, FK -> `plan_tasks.id` ON DELETE CASCADE)
- `depends_on_task_id` (UUID, FK -> `plan_tasks.id` ON DELETE CASCADE)
- Composite PK: `(task_id, depends_on_task_id)`
- Constraints: `task_id != depends_on_task_id`; both tasks must belong to the same `plan_id`.

### `plan_task_events` Table (Append-Only)
- `id` (UUID, PK)
- `task_id` (UUID, FK -> `plan_tasks.id` ON DELETE CASCADE)
- `plan_id` (UUID, NOT NULL)
- `project_id` (UUID, NOT NULL)
- `event_type` (VARCHAR(40), NOT NULL): `created`, `status_change`, `claimed`, `heartbeat`, `released`, `reclaimed`, `completed`, `cancelled`
- `from_status` (VARCHAR(32), NULL)
- `to_status` (VARCHAR(32), NULL)
- `author` (VARCHAR(120), NOT NULL)
- `detail` (TEXT, NULL, max 2000 chars)
- `created_at` (TIMESTAMPTZ, NOT NULL)
- Trigger: `BEFORE UPDATE OR DELETE` raises exception to enforce append-only immutability.

## 7. Product Contract Specification

The milestone contract is registered in PCS under product requirement **`R-086`** (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`):

### Invariants

| Key | ID | Kind | Risk | Statement |
|---|---|---|---|---|
| **INV-PLAN-1** | `952fcb34-050f-42d5-860b-d3c421131c26` | `architecture` | `high` | Tasks belong to one plan and one project; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected. |
| **INV-PLAN-2** | `fdab6d29-f527-4d13-91c2-6510a3309f2d` | `data-boundary` | `high` | Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4). |
| **INV-PLAN-3** | `c212e6cb-a1e5-4e81-8301-4c6febae6739` | `data-boundary` | `high` | Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed. |
| **INV-PLAN-4** | `d196d5d6-20fc-4771-ad07-f80397eda510` | `architecture` | `medium` | Every plan task mutation appends an immutable event recording author, event type, prior state, new state, and timestamp; events are never updated or deleted. |
| **INV-PLAN-5** | `d55a6164-1772-49c2-b390-be8f988e203b` | `data-boundary` | `high` | Task preparation with task_id returns a role-neutral, token-bounded prompt with task details, dependency status, and linked contract rules; claim tokens, provider keys, and raw diffs are never emitted. |
| **INV-PLAN-6** | `56ca7dc0-e3f0-4270-b1ce-48a915fb09b7` | `behavior` | `high` | AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks. |
| **INV-PLAN-7** | `78c2bf3b-1e07-4a6b-b80f-3272f56200b9` | `architecture` | `high` | Plans UI strictly uses DESIGN.md tokens with no literal visual values; mutations update UI only after server confirmation; zero false-success states. |

### Acceptance Criteria

| Key | ID | Invariant | Kind | Review | Statement |
|---|---|---|---|---|---|
| **AC-PLAN-1** | `bcfa212d-eae5-42c6-b98a-7ba78cbfcb75` | `INV-PLAN-1` | `test` | `not-required` | Plan and task DAG creation rejects cycles, self-dependencies, cross-plan, and cross-project references (T23) |
| **AC-PLAN-2** | `911bab97-9662-4acb-8efe-4cece2aeab7c` | `INV-PLAN-1` | `test` | `not-required` | Ready-task discovery returns only tasks whose prerequisites are complete and lease is unacquired or expired (T23) |
| **AC-PLAN-3** | `42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b` | `INV-PLAN-2` | `test` | `required` | Task completion and plan completion never mutate requirement status or bypass evidence close gate (T23) |
| **AC-PLAN-4** | `8fc004f9-b782-4158-afa5-7ceb693a4315` | `INV-PLAN-3` | `test` | `not-required` | Atomic task claim issues unique ephemeral token and rejects concurrent claim race (T23) |
| **AC-PLAN-5** | `05f02bf6-ab90-4f28-9002-2e88d69a07a1` | `INV-PLAN-3` | `test` | `not-required` | Task heartbeat, release, and reclaim enforce lease validity and reject invalid or stale tokens (T23) |
| **AC-PLAN-6** | `e671ec47-f6b3-4e18-8fbf-5606f5afe90b` | `INV-PLAN-4` | `test` | `not-required` | Every plan task mutation appends an immutable event and preserves complete queryable task history (T23) |
| **AC-PLAN-7** | `eeb30422-628b-4a3d-bd01-b267c42e8a2f` | `INV-PLAN-3` | `test` | `required` | Audited MCP and HTTP planning tools expose typed operations with token redaction and input validation (T24) |
| **AC-PLAN-8** | `eabc07be-3c22-4227-ae97-9b63bc2ea3f4` | `INV-PLAN-5` | `test` | `required` | prepare_task with task_id produces bounded role-neutral prompt with dependency and contract state without secrets (T25) |
| **AC-PLAN-9** | `f9d99c08-7383-48f9-932c-94e1a5c24b35` | `INV-PLAN-6` | `test` | `required` | generate_plan_draft uses secure T20 settings, validates structured schema, and persists zero database rows (T26) |
| **AC-PLAN-10** | `9521864a-18e2-498b-8b09-b24e180580d2` | `INV-PLAN-6` | `test` | `not-required` | AI draft persistence occurs only through explicit caller approval via atomic create_plan_with_tasks (T26, T28) |
| **AC-PLAN-11** | `98f519b5-6bed-491c-b2a7-ed4150118c91` | `INV-PLAN-7` | `test` | `not-required` | Plans frontend renders plans, DAG dependency status, ready filter, claim/lease controls, and history drill-down (T27) |
| **AC-PLAN-12** | `5187dff3-9823-49c8-9307-669b99b24976` | `INV-PLAN-7` | `test` | `required` | Plans UI strictly complies with DESIGN.md tokens without literal visual values and prevents false-success states (T27, T28) |
| **AC-PLAN-13** | `c89b24eb-9e64-4e8f-ac83-022f42bd7d14` | `INV-PLAN-1` | `command` | `not-required` | End-to-end integration verifies full planning lifecycle, migration clean from empty DB, and just check pass (T29) |

## 8. Task Ownership Matrix (T23–T29)

| Task | Branch | Exclusive Owned Files | Primary Invariants | Primary Criteria |
|---|---|---|---|---|
| **T23** | `task/T23-plan-task-core` | `server/src/pcs/planning/__init__.py`, `models.py`, `service.py`, `types.py`, `errors.py`, `server/src/pcs/db/models.py` (planning registration), Alembic migration, `server/tests/test_planning_core.py`, `tasks/T23-plan-task-core.md` | `INV-PLAN-1`, `INV-PLAN-2`, `INV-PLAN-3`, `INV-PLAN-4` | `AC-PLAN-1`, `AC-PLAN-2`, `AC-PLAN-3`, `AC-PLAN-4`, `AC-PLAN-5`, `AC-PLAN-6` |
| **T24** | `task/T24-plan-task-api` | `server/src/pcs/mcp/planning_tools.py`, `server/src/pcs/web_api/planning_routes.py`, registration in `pcs/mcp/server.py` & `pcs/web_api/router.py`, `server/tests/test_planning_api.py`, `tasks/T24-plan-task-api.md` | `INV-PLAN-1`, `INV-PLAN-3` | `AC-PLAN-7` |
| **T25** | `task/T25-planned-task-handoff` | `server/src/pcs/planning/handoff.py`, `server/src/pcs/index/retrieval.py`, `server/src/pcs/mcp/index_tools.py`, `server/src/pcs/web_api/index_routes.py`, `server/tests/test_planned_task_handoff.py`, `tasks/T25-planned-task-handoff.md` | `INV-PLAN-5` | `AC-PLAN-8` |
| **T26** | `task/T26-ai-plan-draft` | `server/src/pcs/planning/generator.py`, `server/src/pcs/planning/schemas.py`, `server/tests/test_ai_plan_draft.py`, `tasks/T26-ai-plan-draft.md` | `INV-PLAN-6` | `AC-PLAN-9`, `AC-PLAN-10` |
| **T27** | `task/T27-plans-ui` | `web/src/routes.ts`, `web/src/App.tsx`, `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/queryKeys.ts`, `web/src/hooks/usePlans.ts`, `web/src/views/PlansView.tsx`, `web/src/components/planning/*`, `web/src/views/PlansView.test.tsx`, `tasks/T27-plans-ui.md` | `INV-PLAN-7` | `AC-PLAN-11`, `AC-PLAN-12` |
| **T28** | `task/T28-ai-plan-ui` | `web/src/components/planning/GenerateDraftModal.tsx`, `web/src/hooks/useGeneratePlanDraft.ts`, `web/src/components/planning/GenerateDraftModal.test.tsx`, `tasks/T28-ai-plan-ui.md` | `INV-PLAN-6`, `INV-PLAN-7` | `AC-PLAN-10`, `AC-PLAN-12` |
| **T29** | `task/T29-plan-task-integration` | `server/tests/test_planning_integration.py`, `docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `README.md`, `tasks/T29-plan-task-integration.md` | `INV-PLAN-1..7` | `AC-PLAN-13` |
