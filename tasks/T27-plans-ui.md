# T27 — Plans and Tasks Web UI

**Branch:** `task/T27-plans-ui` · **Depends on:** T24 · **Blocks:** T28, T29

## Goal

Build a deterministic, accessible, and reactive web UI for plans and task orchestration at `/projects/:project/plans`, supporting plan listing and detail, manual plan/task creation, plan update and archive actions, dependency visualization, ready-task filtering, lease-aware claim/heartbeat/release controls via nested API routes, task status transitions, conflict feedback, and structured audit history drill-down.

## Owned files/modules

- `web/src/views/PlansView.tsx` (base plans view)
- `web/src/components/plans/` (all plan-specific presentational and control components)
- `web/src/api/planning.ts` (typed API client functions, query keys, and TanStack Query mutation hooks)
- `web/src/types/planning.ts` (TypeScript interfaces matching T24 HTTP schemas)
- Minimal route/navigation additions in `web/src/routes.ts`, `web/src/App.tsx`, and sidebar/nav component
- `web/src/views/PlansView.test.tsx` and `web/src/components/plans/*.test.tsx`
- `tasks/T27-plans-ui.md`

*Sequenced Shared Integration Seam:* T27 establishes the base Plans view (`PlansView.tsx`) and planning API client (`planning.ts`). Downstream task T28 will sequentially branch from merged T27 to add the AI draft modal and draft mutation hooks without altering base plan components.

Do not touch AI plan draft generation (owned by T28), backend server code (owned by T23/T24/T25/T26), or existing non-planning views.

## Non-goals

- Implementing AI draft generation modal/actions (owned by T28).
- Inventing unmerged backend endpoints; if T25 is not yet merged, isolate prompt preparation behind a typed seam with graceful feature detection.
- Optimistic state updates that mask backend failures or concurrency conflicts.
- Using untyped `fetch`, raw `any` types, or literal styling values that violate `DESIGN.md`.

## Invariants

- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Web UI operations reflect server-confirmed truth without speculative optimistic writes; mutations invalidate project queries; DESIGN.md tokens are followed.

## Requirements

- Add route `/projects/:project/plans` and a corresponding nav item labeled "Plans" in the project navigation bar.
- Provide Plan List view:
  - Displays all plans in active project with title, goal, status (`draft`, `active`, `completed`, `archived`), task progress counter (`completed / total`), and created timestamp.
  - Action to manually create a new plan (title, goal).
  - Status filter to view active vs archived plans.
- Provide Plan Detail view:
  - Header with plan title, goal, lifecycle status badge, progress bar, and lifecycle controls:
    - `activate_plan` (transitions draft -> active via `POST /api/projects/{project}/plans/{plan_id}/activate`)
    - `complete_plan` (transitions active -> completed via `POST /api/projects/{project}/plans/{plan_id}/complete`)
    - `archive_plan` (transitions plan to archived state via `POST /api/projects/{project}/plans/{plan_id}/archive`)
    - `update_plan` (modal/form to edit title and goal via `PATCH /api/projects/{project}/plans/{plan_id}`)
  - Action to add tasks to plan (title, objective, acceptance criteria, linked files, requirement IDs).
  - Dependency management control: add dependency between tasks within the same plan.
  - DAG / Dependency visualizer showing prerequisite task chains and blocking relationships.
  - Filter toggle for "Ready Tasks" (tasks matching canonical ready predicate: active plan, prerequisites completed, status is `ready` or lease is expired [`lease_expires_at <= now()`] across `claimed`, `in_progress`, or `in_review`).
  - Task item card displaying: local ID, title, status badge (`pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`), assignee / `claimed_by`, lease expiration countdown/indicator ("Expired - Reclaimable" when `lease_expires_at <= now()` for `claimed`, `in_progress`, or `in_review` tasks), and linked requirement tags.
- Task orchestration controls using nested endpoints:
  - `claim_task`: Prompts for `claimed_by` name, lease seconds; calls `POST .../plans/{plan_id}/tasks/{task_id}/claim`; stores returned one-time claim token in local session storage. Supports initial claim on `ready` tasks and atomic reclaim on expired (`lease_expires_at <= now()`) `claimed`, `in_progress`, or `in_review` tasks.
  - `heartbeat_task`: Extends active lease for currently claimed task via `POST .../plans/{plan_id}/tasks/{task_id}/heartbeat` using stored token; strictly preserves current task status (`claimed` remains `claimed`, `in_progress` remains `in_progress`).
  - `release_task`: Relinquishes active claim lease back to `ready` via `POST .../plans/{plan_id}/tasks/{task_id}/release`, clearing stored token.
  - `set_task_status`: Transitions task status (e.g. `claimed -> in_progress`, `in_progress -> in_review`, `in_progress -> blocked`) via `POST .../plans/{plan_id}/tasks/{task_id}/status` using active token.
  - `complete_task`: Transitions task to `completed` via `POST .../plans/{plan_id}/tasks/{task_id}/complete` using active token (or tokenless only if no active lease / lease has expired [`lease_expires_at <= now()`]).
  - Active lease token enforcement: Mutations on tasks with active leases (`lease_expires_at > now()`) strictly require the valid stored claim token; the UI provides no "operator bypass" toggle. Attempting a mutation without a valid token on an active lease displays a conflict banner and disables the action.
  - Visual error/conflict banner when a mutation fails due to lease expiry (409 Conflict), stale token (409 Conflict), or concurrent claiming. On stale token, clears invalid session token.
- Task history drill-down:
  - Modal or expandable drawer showing append-only `plan_task_events` from `GET .../plans/{plan_id}/tasks/{task_id}/history`:
    - Event type badge (`created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`).
    - Transition indicators (`old_status -> new_status`).
    - Actor identity and formatted timestamp.
    - Formatted display of structured `payload` details (e.g. updated fields, claimant, lease duration, transition reason).
- Prompt preparation integration seam:
  - Prepare/copy agent prompt button available on task cards; calls T25 endpoint if available or indicates dependency status.
- Strict adherence to `DESIGN.md`:
  - Use only CSS custom properties or Tailwind `@theme` tokens (colors, typography, radii, spacing).
  - No raw hex values, arbitrary pixel dimensions, or ad-hoc box shadows.
  - Follow keyboard accessibility and screen-reader standards (semantic HTML, unique IDs, ARIA attributes).
- State management:
  - Server state managed entirely via TanStack Query with project-scoped query keys (`['projects', project, 'plans', ...]`).
  - No optimistic mutations; UI transitions occur only upon server HTTP 2xx confirmation.
  - Mutation `onSuccess` invalidates relevant queries to fetch fresh server state.

## Acceptance checklist

- [ ] `AC-PLAN-11` (`98f519b5-6bed-491c-b2a7-ed4150118c91`): Plans UI provides manual creation, DAG visualization, ready-task filter, claim/heartbeat/release controls, and conflict feedback.
- [ ] `AC-PLAN-12` (`5187dff3-9823-49c8-9307-669b99b24976`): Frontend mutations only update state upon server confirmation and invalidate project queries without stale state.
- [ ] Navigation link to `/projects/:project/plans` renders correctly in sidebar/header.
- [ ] Plan list and detail views render correctly with progress counters, edit plan modal, and archive action.
- [ ] All task mutations use nested `/plans/{plan_id}/tasks/{task_id}/...` endpoints.
- [ ] Ready-task filter accurately filters tasks whose dependencies are satisfied, including expired `in_review` tasks (`lease_expires_at <= now()`).
- [ ] Expired lease display alerts user that task is available for reclamation ("Expired - Reclaimable") across `claimed`, `in_progress`, and `in_review` states when `lease_expires_at <= now()`.
- [ ] Exact boundary condition `lease_expires_at == now()` is rendered as expired ("Expired - Reclaimable") and included in Ready Tasks filter.
- [ ] Task claim modal captures lease duration, stores token, and updates UI to claimed state upon server confirmation.
- [ ] Reclaim of expired `in_review` task transitions UI to `claimed` with fresh lease.
- [ ] Heartbeat extends active lease while preserving exact task status (`claimed` stays `claimed`, `in_progress` stays `in_progress`).
- [ ] Mutations on tasks with active leases (`lease_expires_at > now()`) strictly require active claim token; missing or invalid token displays conflict banner.
- [ ] 409 Conflict / StaleClaimToken error displays clear conflict banner and resets stale local token.
- [ ] Task event history drawer displays chronologically ordered audit events with structured payload data across all event types.
- [ ] Independent UI review verifies compliance with `DESIGN.md` tokens (no raw hex/px/shadow).
- [ ] `just check` passes cleanly (ESLint, TypeScript `tsc --noEmit`, Vitest, Vite build).

## Required evidence

- Component and integration tests in `web/src/views/PlansView.test.tsx`.
- Vitest execution output covering routing, isolation, filters, edit/archive actions, nested routes, and lease conflict states.
- Independent UI review confirmation adhering to `DESIGN.md` normative guidelines.

## Verification

```bash
cd web && npm run test -- --run
cd web && npm run typecheck
cd web && npm run lint
cd web && npm run build
just check
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T27-plans-ui`
- **What was done:**
  - Added `/projects/:project/plans` route and Plans view
  - Implemented typed API client with nested task routes, query hooks, and domain components
  - Built DAG visualization, ready filter, edit/archive plan actions, and lease-aware claim controls
  - Created structured task history drawer and conflict handling banners
- **Design Review:**
  - Token audit: zero hex/px/shadow violations
  - Accessibility audit: ARIA tags and semantic HTML verified
- **Verification:**
  - Vitest test output
  - `just check` green result
- **Deviations:** None
```
