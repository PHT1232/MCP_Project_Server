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

- **Deterministic DAG Plans:** Plans decompose milestones into ordered tasks with acyclic prerequisite dependencies and strict database-level project and plan isolation.
- **Normalized Requirement Links:** Tasks link to project requirements via a dedicated junction table (`plan_task_requirements`) enforcing database-level composite foreign key integrity and verifying the `requirements` section discriminator.
- **Atomic Claim Leases:** Workers claim ready tasks via atomic time-bounded leases with ephemeral one-time tokens, preventing race conditions and permitting expired task reclamation.
- **Append-Only History:** All task mutations record immutable event audit records with structured, bounded, and redacted payload data across 10 discrete event types.
- **Self-Contained Handoffs:** `prepare_task(task_id=...)` generates role-neutral, token-bounded Markdown prompts containing task objectives, acceptance criteria, dependency state, and contract rules.
- **Advisory AI Plan Generation:** AI draft generation proposes candidate task DAGs using secure T20 settings without persisting database records until explicit human review and approval.
- **Plans Web Interface:** A dedicated `/projects/:project/plans` interface renders task DAGs, tracks lease states, filters ready tasks, facilitates draft reviews, and enables updating and archiving plans using `DESIGN.md` tokens.
- **Preservation of D4:** Task and plan completion track operational progress and never automatically modify requirement verification status.

## 3. Locked Decisions

| Decision | Summary |
|---|---|
| **D18** | **Deterministic Plan & Task DAG:** Plans contain tasks with explicit DAG dependencies. Self-dependencies, dependency cycles, cross-plan, and cross-project links are rejected by service validation and database composite foreign key constraints. (FR43–FR45) |
| **D19** | **Requirement Independence (Preserve D4):** Task completion never mutates requirement status or close-gate state. Tasks track operational execution; requirements represent verified product contracts governed strictly by the evidence ledger and close gate. (FR53) |
| **D20** | **Atomic Exclusive Leases & Ephemeral Tokens:** Claiming a task atomically allocates an expiring lease with TTL and returns a cryptographically random one-time secret token. Mutating a task with an active lease strictly requires presenting the valid token; no caller can bypass an active lease as an "operator". Expired leases across claimed, in-progress, or in-review tasks can be reclaimed safely. Archiving a plan atomically revokes all active leases as a trusted administrative exception. (FR47) |
| **D21** | **Immutable Task Event Audit Trail:** Every task mutation (creation, update, dependency addition, claim, reclaim, heartbeat, release, status change, completion, cancellation) appends an immutable event row recording author, event type, prior state, new state, timestamp, and bounded, redacted structured payload (mirroring D5). (FR48) |
| **D22** | **Bounded Role-Neutral Task Handoff Prompt:** `prepare_task(task_id=...)` returns a token-budgeted Markdown prompt containing task objective, acceptance criteria, dependency state, and linked requirement contracts without emitting secrets, tokens, or raw diffs. (FR49) |
| **D23** | **Advisory AI Plan Generation with Human Approval:** `generate_plan_draft` is strictly read-only and creates zero database entities. Persisting an AI proposal requires explicit caller review and approval via atomic `create_plan_with_tasks`. (FR50–FR51) |
| **D24** | **Milestone Execution Boundaries (Non-goals):** Agent process spawning/dispatch, local shell or container execution, Git worktree orchestration, GitHub issue/PR sync, and fine-grained authorization are non-goals for this milestone. (FR43–FR53) |

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
                     └── T29 (Integration, PostgreSQL migration roundtrip, release gate) [depends on T25-T28]
```

### Integration Dependencies Note
- **T20 (Admin-managed AI provider settings):** Currently implemented on branch `task/T20-ai-provider-settings` (commit `6b85747`) and under review. T26 depends on T20's persisted summary-provider settings and validated endpoint security.
- **T21 (Semantic query runtime fallback):** Implemented on branch `task/T21-semantic-runtime-fallback` (commit `eecda22`) and under review. Independent of planning tasks.
- **T17 (Codebase Guide frontend):** Implemented on branch `task/T17-codebase-guide-ui` (commit `14c3437`) and under review. Independent of planning tasks.
- **T18 (Integration orchestrator):** Not started. Planning tasks do not depend on T18.

## 6. Plan Task State Machine & Complete Lease Lifecycle

### 6.1 States
The lifecycle of a `plan_task` is governed by 8 distinct states:
1. `pending`: The task is waiting for prerequisite tasks in the DAG to complete, or the plan is not yet active.
2. `ready`: Persisted state. All prerequisite dependencies are satisfied (`status == 'completed'`), and the task is eligible to be claimed.
3. `claimed`: An agent or human has acquired an exclusive, time-bounded lease via `claim_task` and holds a valid ephemeral claim token.
4. `in_progress`: The leaseholder has acknowledged and begun active work on the task (via `set_task_status(status='in_progress')`).
5. `blocked`: The task cannot proceed due to external impediments (flagged by the leaseholder or plan administrator).
6. `in_review`: Implementation is complete, and the task is awaiting review/verification.
7. `completed`: Terminal success state. All acceptance criteria have been implemented and verified. Downstream tasks in `pending` whose prerequisites are now all `completed` automatically transition to `ready`.
8. `cancelled`: Terminal cancellation state. The task was aborted or deemed unnecessary.

### 6.2 Lease Fields and Transition Matrix

Every `plan_task` maintains three lease-tracking fields:
- `claim_token_hash`: VARCHAR(64) NULL — SHA-256 hex digest of the active one-time claim token.
- `claimed_by`: VARCHAR(120) NULL — Actor holding the active lease.
- `lease_expires_at`: TIMESTAMPTZ NULL — Lease expiration timestamp.

| Transition | Operation / Trigger | Required Authorization / Token | `claim_token_hash` | `claimed_by` | `lease_expires_at` | Notes |
|---|---|---|---|---|---|---|
| `pending -> ready` | `activate_plan` or `complete_task` (unlock) | Service internal | NULL | NULL | NULL | Activated when all prerequisites are completed. |
| `ready -> claimed` | `claim_task(lease_seconds)` | Any worker | `sha256(token)` | `caller` | `now() + ttl` | Ephemeral secret token returned once in response. |
| `claimed -> in_progress` | `set_task_status(status='in_progress')` | Active claim token mandatory | **Retained** | **Retained** | **Retained** | Token remains valid; lease continues. |
| `claimed -> claimed` | `heartbeat_task(lease_seconds)` | Active claim token mandatory | **Retained** | **Retained** | `now() + ttl` | Extends expiration; exact status preserved. |
| `in_progress -> in_progress` | `heartbeat_task(lease_seconds)` | Active claim token mandatory | **Retained** | **Retained** | `now() + ttl` | Extends expiration; exact status preserved. |
| `claimed \| in_progress -> ready` | `release_task()` | Active claim token mandatory | **NULL** | **NULL** | **NULL** | Voluntary release; token permanently revoked. |
| `claimed \| in_progress \| in_review -> claimed` | `claim_task(lease_seconds)` (Reclaim) | Any worker (when `lease_expires_at < now()`) | `sha256(new_token)` | `new_caller` | `now() + ttl` | Reclaims expired lease; old token permanently revoked. |
| `in_progress -> in_review` | `set_task_status(status='in_review')` | Active claim token mandatory | **Retained** | **Retained** | **Retained** | Indicates work ready for review. |
| `in_review -> completed` | `complete_task()` | Active claim token (if active lease) OR tokenless (if expired/no lease) | **NULL** | `caller` | **NULL** | Token revoked; status terminal. |
| `claimed \| in_progress -> completed` | `complete_task()` | Active claim token mandatory | **NULL** | `caller` | **NULL** | Token revoked; unlocks downstream tasks. |
| `claimed \| in_progress -> blocked` | `set_task_status(status='blocked')` | Active claim token mandatory | **NULL** | **NULL** | **NULL** | Active lease revoked; blocked task cannot hold lease. |
| `blocked -> ready` | `set_task_status(status='ready')` | Allowed without token (no active lease) | NULL | NULL | NULL | Returns to pool; old token was already revoked. |
| `blocked -> in_progress` | `set_task_status(status='in_progress')` | Rejected without claim | - | - | - | Must transition to `ready` first and be claimed. |
| `* -> cancelled` | `set_task_status(status='cancelled')` | Active claim token (if active lease) OR tokenless (if expired/no lease) | **NULL** | **NULL** | **NULL** | Token revoked; terminal state. |

### 6.3 Special Lifecycle & Security Rules
1. **Unified Reclaim for Expired `in_review`:**
   - While `lease_expires_at >= now()`, a task in `in_review` has an exclusive review lease; another worker's attempt to claim or reclaim fails with HTTP 409 Conflict.
   - When `lease_expires_at < now()`, the review lease has elapsed:
     - The task appears in `list_ready_tasks` as reclaimable.
     - Any worker can call `claim_task` to atomically transition `in_review -> claimed`, receiving a fresh token and lease duration while permanently revoking the old token.
     - Persisted status does NOT automatically change prior to an explicit claim.
     - In the single-user tailnet model, trusted plan-level completion (`complete_task` without token) is also permitted on an expired `in_review` task if review passed after lease expiry.
2. **No Operator Bypass of Active Leases:**
   - Whenever a task has an active, unexpired lease (`lease_expires_at >= now()` and `claim_token_hash IS NOT NULL`), mutations (`set_task_status`, `complete_task`, direct cancellation) **strictly require** presenting the valid current claim token.
   - No caller can bypass an active lease by claiming operator or administrator status. Tokenless operations are rejected with HTTP 409 Conflict.
   - Tokenless mutations are permitted ONLY when:
     - The task has no active lease (`status IN ('pending', 'ready', 'blocked')` where lease fields are NULL); OR
     - The task's lease has expired (`lease_expires_at < now()`) AND the specific transition is permitted by contract (e.g. completing an expired `in_review` task, or cancelling an expired task).
3. **Plan Archival (`archive_plan`) Administrative Exception:**
   - `archive_plan` is the single trusted administrative exception permitted to override active leases.
   - It atomically revokes all active claim leases across all tasks in the plan (`claim_token_hash = NULL`, `claimed_by = NULL`, `lease_expires_at = NULL`), sets all non-completed tasks to `cancelled`, and sets plan status to `archived`.
4. **Plan Completion / Archival Freeze:**
   - Once a plan is `completed` or `archived`, all `claim_task`, `heartbeat_task`, and task status mutations are **strictly rejected** with `PlanNotActiveError` (HTTP 409).
5. **Stale Token Rejection:**
   - Every mutation presenting a claim token must verify:
     `task.claim_token_hash == sha256(token) AND task.lease_expires_at > now()`.
   - If the token does not match, or lease has expired, or task was released/reclaimed/completed/cancelled/archived, the operation fails with `StaleClaimTokenError` (HTTP 409 Conflict).
6. **Heartbeat Preserves Status:**
   - `heartbeat_task` validates the token and extends `lease_expires_at = now() + ttl`. It strictly preserves the task's current status (`claimed` remains `claimed`, `in_progress` remains `in_progress`), and never mutates a `claimed` task to `in_progress`.

### 6.4 Canonical Predicate for `list_ready_tasks`
A task is returned by `list_ready_tasks` if and only if:
1. `plan.status == 'active'` and belongs to the specified project.
2. `task.status NOT IN ('completed', 'cancelled', 'blocked')`.
3. All prerequisite tasks in `task_dependencies` have `status == 'completed'`.
4. The task is available for execution:
   - `task.status == 'ready'`, **OR**
   - `task.status IN ('claimed', 'in_progress', 'in_review')` AND `task.lease_expires_at IS NOT NULL` AND `task.lease_expires_at < :now` (expired lease eligible for reclamation).

## 7. Data Model & Database Architecture (PostgreSQL)

All planning tables live in PostgreSQL under the standard schema with composite foreign keys enforcing strict project and plan isolation:

### `plans` Table
- `id` (VARCHAR(36), PK)
- `project_id` (VARCHAR(36), FK -> `projects.id` ON DELETE CASCADE, index=True)
- `title` (VARCHAR(160), NOT NULL)
- `goal` (TEXT, NOT NULL, max 8000 chars)
- `status` (VARCHAR(32), NOT NULL, default `'draft'`): `draft`, `active`, `completed`, `archived`
- `created_at` (TIMESTAMPTZ, NOT NULL)
- `updated_at` (TIMESTAMPTZ, NOT NULL)
- `author` (VARCHAR(120), NOT NULL)
- Composite Unique Constraint: `UniqueConstraint("id", "project_id", name="uq_plans_id_project")`

### `plan_tasks` Table
- `id` (VARCHAR(36), PK)
- `plan_id` (VARCHAR(36), NOT NULL)
- `project_id` (VARCHAR(36), NOT NULL)
- `local_task_id` (VARCHAR(32), NOT NULL): Unique local slug within plan (e.g. `T01`, `T02`)
- `title` (VARCHAR(160), NOT NULL)
- `objective` (TEXT, NOT NULL, max 8000 chars)
- `acceptance_criteria` (JSONB, NOT NULL, default `'[]'::jsonb`): list of strings
- `linked_files` (JSONB, NOT NULL, default `'[]'::jsonb`): list of normalized relative paths
- `priority` (INT, NOT NULL, default 0)
- `status` (VARCHAR(32), NOT NULL, default `'pending'`): CheckConstraint for 8 valid states
- `claim_token_hash` (VARCHAR(64), NULL): SHA-256 hex digest of active claim token
- `claimed_by` (VARCHAR(120), NULL): Identity of worker holding the lease
- `lease_expires_at` (TIMESTAMPTZ, NULL): Expiration timestamp of active claim lease
- `created_at` (TIMESTAMPTZ, NOT NULL)
- `updated_at` (TIMESTAMPTZ, NOT NULL)
- Foreign Key: `ForeignKeyConstraint(["plan_id", "project_id"], ["plans.id", "plans.project_id"], ondelete="CASCADE", name="fk_plan_tasks_plan")`
- Composite Unique Constraints:
  - `UniqueConstraint("id", "plan_id", "project_id", name="uq_plan_tasks_id_plan_project")`
  - `UniqueConstraint("id", "project_id", name="uq_plan_tasks_id_project")`
  - `UniqueConstraint("plan_id", "local_task_id", name="uq_plan_tasks_plan_local_id")`
- Indexes: `(project_id, status)`, `(plan_id, status)`, `(lease_expires_at)`

### `task_dependencies` Table (Strict Dependency Isolation)
- `project_id` (VARCHAR(36), NOT NULL)
- `plan_id` (VARCHAR(36), NOT NULL)
- `task_id` (VARCHAR(36), NOT NULL)
- `depends_on_task_id` (VARCHAR(36), NOT NULL)
- `created_at` (TIMESTAMPTZ, NOT NULL)
- Primary Key: `(task_id, depends_on_task_id)`
- Composite Foreign Keys (enforces identical `plan_id` and `project_id` at DB level):
  - `ForeignKeyConstraint(["task_id", "plan_id", "project_id"], ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"], ondelete="CASCADE", name="fk_task_deps_task")`
  - `ForeignKeyConstraint(["depends_on_task_id", "plan_id", "project_id"], ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"], ondelete="CASCADE", name="fk_task_deps_depends_on")`
- CheckConstraint: `task_id != depends_on_task_id` (no self-dependencies)

### `plan_task_requirements` Table (Normalized Requirement Links)
- `project_id` (VARCHAR(36), NOT NULL)
- `plan_task_id` (VARCHAR(36), NOT NULL)
- `requirement_id` (VARCHAR(36), NOT NULL)
- `requirement_section` (VARCHAR(32), NOT NULL, server_default="requirements")
- `created_at` (TIMESTAMPTZ, NOT NULL)
- Primary Key: `(plan_task_id, requirement_id)`
- CheckConstraint: `requirement_section = 'requirements'` (enforces target is in requirements section)
- Composite Foreign Keys:
  - `ForeignKeyConstraint(["plan_task_id", "project_id"], ["plan_tasks.id", "plan_tasks.project_id"], ondelete="CASCADE", name="fk_plan_task_reqs_task")`
  - `ForeignKeyConstraint(["requirement_id", "project_id"], ["context_entries.id", "context_entries.project_id"], ondelete="CASCADE", name="fk_plan_task_reqs_req_project")`
  - `ForeignKeyConstraint(["requirement_id", "requirement_section"], ["context_entries.id", "context_entries.section"], ondelete="CASCADE", name="fk_plan_task_reqs_req_section")`
- Indexes: `(project_id, requirement_id)`, `(plan_task_id)`
- Service Validation: Service also explicitly validates that `requirement_id` points to an entry where `section == 'requirements'`, rejecting focus/decision/glossary/bug entries with `ValidationError`.

### `plan_task_events` Table (Append-Only Audit History)
- `id` (VARCHAR(36), PK)
- `project_id` (VARCHAR(36), NOT NULL)
- `plan_id` (VARCHAR(36), NOT NULL)
- `task_id` (VARCHAR(36), NOT NULL)
- `event_type` (VARCHAR(32), NOT NULL): Enum of 10 types:
  `created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`
- `actor` (VARCHAR(120), NOT NULL)
- `old_status` (VARCHAR(32), NULL)
- `new_status` (VARCHAR(32), NULL)
- `payload` (JSONB, NOT NULL, default `'{}'::jsonb`): Bounded, redacted structured dictionary defined per event type.
- `created_at` (TIMESTAMPTZ, NOT NULL)
- Composite Foreign Key:
  `ForeignKeyConstraint(["task_id", "plan_id", "project_id"], ["plan_tasks.id", "plan_tasks.plan_id", "plan_tasks.project_id"], ondelete="CASCADE", name="fk_plan_task_events_task_plan_project")`
- Immutability: Read-only model without updates or deletions.

#### Structured Event Payloads:
- `created`: `{"local_task_id": "T01", "title": "...", "priority": 0}`
- `updated`: `{"updated_fields": ["title", "objective"]}` (field names only, no raw diffs or secrets)
- `dependency_added`: `{"depends_on_task_id": "<uuid>", "depends_on_local_id": "T01"}`
- `claimed`: `{"claimed_by": "agent-1", "lease_seconds": 1800}` (never contains token or token hash)
- `reclaimed`: `{"claimed_by": "agent-2", "prior_claimant": "agent-1", "lease_seconds": 1800}`
- `heartbeat`: `{"lease_seconds": 1800, "new_expiry": "2026-09-14T..."}`
- `released`: `{"reason": "voluntary_release"}`
- `status_changed`: `{"reason": "blocked_by_ci", "old_status": "in_progress", "new_status": "blocked"}` (bounded reason, max 200 chars)
- `completed`: `{"completed_by": "agent-1"}`
- `cancelled`: `{"reason": "plan_archived"}`

## 8. Web API & MCP Framework Architecture

The server adheres to repository standards using **Starlette** and **FastMCP**:
- **MCP Tools:** Defined in `server/src/pcs/mcp/planning_tools.py` and registered onto FastMCP in `server/src/pcs/mcp/server.py` via `register_planning_tools(mcp)`.
- **HTTP Routes:** Defined in `server/src/pcs/web_api/planning_routes.py` and registered onto the Starlette application in `server/src/pcs/mcp/server.py` via `register_planning_routes(mcp)`, using `mcp.custom_route(path, methods)(handler)`.
- Handlers delegate directly to `pcs.planning.service`, enforcing DRY validation and unified error mapping.
- Caller identity is extracted from header `x-pcs-caller` (defaults to `"frontend"`).

### Standardized Nested Operations Surface:
1. `create_plan(project, title, goal)`
   - `POST /api/projects/{project}/plans`
2. `create_plan_with_tasks(project, title, goal, tasks, dependencies)`
   - `POST /api/projects/{project}/plans/with-tasks`
3. `list_plans(project, status=None)`
   - `GET /api/projects/{project}/plans`
4. `get_plan(project, plan_id)`
   - `GET /api/projects/{project}/plans/{plan_id}`
5. `update_plan(project, plan_id, title=None, goal=None)`
   - `PATCH /api/projects/{project}/plans/{plan_id}`
6. `archive_plan(project, plan_id)`
   - `POST /api/projects/{project}/plans/{plan_id}/archive`
7. `activate_plan(project, plan_id)`
   - `POST /api/projects/{project}/plans/{plan_id}/activate`
8. `add_plan_task(project, plan_id, local_task_id, title, objective, acceptance_criteria, linked_files=None, requirement_ids=None, priority=0)`
   - `POST /api/projects/{project}/plans/{plan_id}/tasks`
9. `update_plan_task(project, plan_id, task_id, title=None, objective=None, acceptance_criteria=None, linked_files=None, requirement_ids=None, priority=None)`
   - `PATCH /api/projects/{project}/plans/{plan_id}/tasks/{task_id}`
10. `add_task_dependency(project, plan_id, task_id, depends_on_task_id)`
    - `POST /api/projects/{project}/plans/{plan_id}/dependencies`
11. `list_ready_tasks(project, plan_id=None)`
    - `GET /api/projects/{project}/ready-tasks` (across all active plans)
    - `GET /api/projects/{project}/plans/{plan_id}/ready-tasks` (scoped to plan)
12. `claim_task(project, plan_id, task_id, claimed_by, lease_seconds=1800)`
    - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/claim`
13. `heartbeat_task(project, plan_id, task_id, claim_token, lease_seconds=1800)`
    - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/heartbeat`
14. `release_task(project, plan_id, task_id, claim_token)`
    - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/release`
15. `set_task_status(project, plan_id, task_id, status, claim_token=None, reason=None)`
    - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/status`
16. `complete_task(project, plan_id, task_id, claim_token=None)`
    - `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/complete`
17. `complete_plan(project, plan_id)`
    - `POST /api/projects/{project}/plans/{plan_id}/complete`
18. `get_task_history(project, plan_id, task_id)`
    - `GET /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/history`
19. `generate_plan_draft(project, goal, constraints=None, max_tasks=10)` (T26)
    - `POST /api/projects/{project}/plans/generate-draft`

*Note on Route Validation:* All nested route handlers verify that the requested task actually belongs to both the `plan_id` and `project` in the URL; cross-plan or cross-project attempts fail with 404 (`TaskNotFoundError`).

## 9. Product Contract Specification

The milestone contract is registered in PCS under product requirement **`R-086`** (`f5abbe7d-fbe4-438e-a0ac-d2b0e88f9453`):

### Invariants

| Key | ID | Kind | Risk | Statement |
|---|---|---|---|---|
| **INV-PLAN-1** | `952fcb34-050f-42d5-860b-d3c421131c26` | `architecture` | `high` | Tasks belong to one plan and one project; task dependencies and requirement links enforce tenant and plan isolation via database composite foreign keys; dependency graph is strictly acyclic; self-dependencies, cycles, cross-plan, and cross-project references are rejected. |
| **INV-PLAN-2** | `fdab6d29-f527-4d13-91c2-6510a3309f2d` | `data-boundary` | `high` | Task and plan completion never mutate requirement status or close-gate state; requirement verification remains governed strictly by evidence (D4). |
| **INV-PLAN-3** | `c212e6cb-a1e5-4e81-8301-4c6febae6739` | `data-boundary` | `high` | Claiming a task atomically allocates an expiring lease and returns an ephemeral one-time secret token; stale or invalid tokens cannot modify claimed tasks; expired leases can be safely reclaimed. |
| **INV-PLAN-4** | `d196d5d6-20fc-4771-ad07-f80397eda510` | `architecture` | `medium` | Every plan task mutation appends an immutable event recording author, event type, prior state, new state, timestamp, and structured payload; events are never updated or deleted. |
| **INV-PLAN-5** | `d55a6164-1772-49c2-b390-be8f988e203b` | `data-boundary` | `high` | Task preparation with task_id returns a role-neutral, token-bounded prompt with task details, dependency status, and linked contract rules; claim tokens, provider keys, and raw diffs are never emitted. |
| **INV-PLAN-6** | `56ca7dc0-e3f0-4270-b1ce-48a915fb09b7` | `behavior` | `high` | AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks. |
| **INV-PLAN-7** | `78c2bf3b-1e07-4a6b-b80f-3272f56200b9` | `architecture` | `high` | Plans UI strictly uses DESIGN.md tokens with no literal visual values; mutations update UI only after server confirmation; zero false-success states. |

### Acceptance Criteria

| Key | ID | Invariant | Kind | Review | Statement |
|---|---|---|---|---|---|
| **AC-PLAN-1** | `bcfa212d-eae5-42c6-b98a-7ba78cbfcb75` | `INV-PLAN-1` | `test` | `not-required` | Plan and task DAG creation rejects cycles, self-dependencies, cross-plan, and cross-project references, enforcing database composite foreign keys and section validation on plan_task_requirements (T23) |
| **AC-PLAN-2** | `911bab97-9662-4acb-8efe-4cece2aeab7c` | `INV-PLAN-1` | `test` | `not-required` | Ready-task discovery returns only tasks whose prerequisites are complete and lease is unacquired or expired (T23) |
| **AC-PLAN-3** | `42dfcafc-db94-4bc4-bcc3-9ff1e0091f9b` | `INV-PLAN-2` | `test` | `required` | Task completion and plan completion never mutate requirement status or bypass evidence close gate (T23) |
| **AC-PLAN-4** | `8fc004f9-b782-4158-afa5-7ceb693a4315` | `INV-PLAN-3` | `test` | `not-required` | Atomic task claim issues unique ephemeral token and rejects concurrent claim race (T23) |
| **AC-PLAN-5** | `05f02bf6-ab90-4f28-9002-2e88d69a07a1` | `INV-PLAN-3` | `test` | `not-required` | Task heartbeat, release, and reclaim enforce lease validity and reject invalid or stale tokens (T23) |
| **AC-PLAN-6** | `e671ec47-f6b3-4e18-8fbf-5606f5afe90b` | `INV-PLAN-4` | `test` | `not-required` | Every plan task mutation appends an immutable event with structured payload diff and preserves complete queryable task history (T23) |
| **AC-PLAN-7** | `eeb30422-628b-4a3d-bd01-b267c42e8a2f` | `INV-PLAN-3` | `test` | `required` | Audited MCP and HTTP planning tools expose typed operations including update_plan and archive_plan with token redaction and input validation (T24) |
| **AC-PLAN-8** | `eabc07be-3c22-4227-ae97-9b63bc2ea3f4` | `INV-PLAN-5` | `test` | `required` | prepare_task with task_id produces bounded role-neutral prompt with dependency and contract state without secrets (T25) |
| **AC-PLAN-9** | `f9d99c08-7383-48f9-932c-94e1a5c24b35` | `INV-PLAN-6` | `test` | `required` | generate_plan_draft uses secure T20 settings, validates structured schema, and persists zero database rows (T26) |
| **AC-PLAN-10** | `9521864a-18e2-498b-8b09-b24e180580d2` | `INV-PLAN-6` | `test` | `not-required` | AI draft persistence occurs only through explicit caller approval via atomic create_plan_with_tasks (T26, T28) |
| **AC-PLAN-11** | `98f519b5-6bed-491c-b2a7-ed4150118c91` | `INV-PLAN-7` | `test` | `not-required` | Plans frontend renders plans, DAG dependency status, ready filter, claim/lease controls, and history drill-down (T27) |
| **AC-PLAN-12** | `5187dff3-9823-49c8-9307-669b99b24976` | `INV-PLAN-7` | `test` | `required` | Plans UI strictly complies with DESIGN.md tokens without literal visual values and prevents false-success states (T27, T28) |
| **AC-PLAN-13** | `c89b24eb-9e64-4e8f-ac83-022f42bd7d14` | `INV-PLAN-1` | `command` | `not-required` | End-to-end integration verifies full planning lifecycle, migration clean from empty PostgreSQL DB, and just check pass (T29) |

## 10. Task Ownership Matrix & Sequenced Shared Integration Seams

To allow parallel progression where possible while preventing merge conflicts, file ownership is managed through **sequenced shared integration seams**:
- Tasks execute in topological order: T23 -> T24 -> (T25, T26, T27) -> T28 -> T29.
- Shared modules are modified sequentially:
  - T24 establishes `planning_tools.py` and `planning_routes.py`. T26 branches only from merged/rebased T24 and appends AI generator endpoints without modifying base planning routes.
  - T27 establishes `web/src/api/planning.ts` and `web/src/views/PlansView.tsx`. T28 branches only from merged/rebased T27 and adds the AI draft modal hook and UI trigger without rewriting base plan components.

| Task | Branch | Base / Depends On | Owned Files & Integration Seams | Primary Criteria |
|---|---|---|---|---|
| **T23** | `task/T23-plan-task-core` | T22 merged | `server/src/pcs/planning/__init__.py`, `models.py`, `service.py`, `types.py`, `errors.py`, ORM registration in `server/src/pcs/db/models.py`, Alembic migration, `server/tests/test_planning_core.py`, `tasks/T23-plan-task-core.md` | `AC-PLAN-1`..`6` |
| **T24** | `task/T24-plan-task-api` | T23 merged | `server/src/pcs/mcp/planning_tools.py` (base tools), `server/src/pcs/web_api/planning_routes.py` (base routes), registration in `pcs/mcp/server.py`, `server/tests/test_planning_api.py`, `tasks/T24-plan-task-api.md` | `AC-PLAN-7` |
| **T25** | `task/T25-planned-task-handoff` | T24 merged | `server/src/pcs/planning/handoff.py`, `server/src/pcs/index/retrieval.py`, `server/src/pcs/mcp/index_tools.py`, `server/src/pcs/web_api/index_routes.py`, `server/tests/test_planned_task_handoff.py`, `tasks/T25-planned-task-handoff.md` | `AC-PLAN-8` |
| **T26** | `task/T26-ai-plan-draft` | T20 merged, T24 merged | `server/src/pcs/planning/generator.py`, `schemas.py`, *Seam:* appends `generate_plan_draft` to `planning_tools.py` & `planning_routes.py`, `server/tests/test_ai_plan_draft.py`, `tasks/T26-ai-plan-draft.md` | `AC-PLAN-9`, `AC-PLAN-10` |
| **T27** | `task/T27-plans-ui` | T24 merged | `web/src/routes.ts`, `web/src/App.tsx`, `web/src/types/planning.ts`, `web/src/api/planning.ts` (base client/hooks), `web/src/views/PlansView.tsx` (base view), `web/src/components/plans/*`, `web/src/views/PlansView.test.tsx`, `tasks/T27-plans-ui.md` | `AC-PLAN-11`, `AC-PLAN-12` |
| **T28** | `task/T28-ai-plan-ui` | T25, T26, T27 merged | `web/src/components/plans/AiPlanDraftModal.tsx`, *Seam:* adds draft query hook in `planning.ts` and draft trigger button in `PlansView.tsx`, `web/src/components/plans/AiPlanDraftModal.test.tsx`, `tasks/T28-ai-plan-ui.md` | `AC-PLAN-10`, `AC-PLAN-12` |
| **T29** | `task/T29-plan-task-integration` | T25–T28 merged | `server/tests/test_planning_integration.py`, `docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `README.md`, `tasks/T29-plan-task-integration.md` | `AC-PLAN-13` |
