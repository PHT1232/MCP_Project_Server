# T27 — Plans and Tasks Control Panel UI

**Branch:** `task/T27-plans-ui` · **Depends on:** T24 · **Blocks:** T28, T29

> **Retargeted 2026-09-15:** originally specified against `web/` (the old
> frontend) with strict `DESIGN.md` token compliance. Docker now serves
> `pcs-control-panel-project` instead of `web/` (see `deploy/Dockerfile.server`),
> so this task is retargeted there. `DESIGN.md` (the "Fey" dark terminal theme)
> governs only `web/` and does not apply — by explicit user decision, this task
> instead follows `pcs-control-panel-project`'s own established visual
> conventions (see "Design conventions" below), not `DESIGN.md`. Everything
> else in the original spec (functional requirements, lease/DAG/conflict
> semantics, acceptance criteria content) is unchanged.

## Goal

Build a deterministic, accessible, and reactive control-panel UI for plans and task orchestration at `/projects/:project/plans`, supporting plan listing and detail, manual plan/task creation, plan update and archive actions, dependency visualization, ready-task filtering, lease-aware claim/heartbeat/release controls via nested API routes, task status transitions, conflict feedback, and structured audit history drill-down.

## Owned files/modules

- `pcs-control-panel-project/lib/api-spec/openapi.yaml` (add the 19 T24 planning routes so orval can generate typed hooks for them — the client was last generated before T24 merged and has no planning coverage yet)
- `pcs-control-panel-project/lib/api-client-react/` (regenerated output from the updated spec — do not hand-edit generated files)
- `pcs-control-panel-project/artifacts/pcs-control-panel/src/pages/Plans.tsx` (base plans view — mirrors the existing `src/pages/not-found.tsx` convention; large enough to warrant its own file rather than another function in `App.tsx`)
- `pcs-control-panel-project/artifacts/pcs-control-panel/src/components/plans/` (DAG visualizer, task card, claim modal, history drawer, and other plan-specific presentational components)
- `pcs-control-panel-project/artifacts/pcs-control-panel/src/lib/planTasks.ts` (pure, unit-testable helpers: ready-task predicate, lease-expiry boundary check, DAG layout/ordering — mirrors the existing `src/lib/codemap.ts` pattern so the tricky boundary logic has real Vitest coverage even without a component-testing setup)
- Minimal additions to `pcs-control-panel-project/artifacts/pcs-control-panel/src/App.tsx`: a `Plans` entry in `AppShell`'s `nav` array and a `/projects/:project/plans` `<Route>` in `Router()`
- `pcs-control-panel-project/artifacts/pcs-control-panel/src/lib/planTasks.test.ts`
- `tasks/T27-plans-ui.md`

*Sequenced Shared Integration Seam:* T27 establishes the base `Plans.tsx` view and the regenerated planning API client. Downstream task T28 will sequentially branch from merged T27 to add the AI draft modal without altering base plan components.

Do not touch AI plan draft generation (owned by T28), backend server code (owned by T23/T24/T25/T26), the legacy `web/` tree, or existing non-planning pages in `pcs-control-panel-project`.

## Non-goals

- Implementing AI draft generation modal/actions (owned by T28).
- Inventing unmerged backend endpoints; if T25/T26 are not yet merged, isolate the affected UI (prompt-prepare button, "Generate with AI" entry point) behind a typed seam with graceful feature detection rather than guessing a shape.
- Optimistic state updates that mask backend failures or concurrency conflicts.
- Using untyped `fetch`, raw `any` types, or ad-hoc `fetch` calls that bypass the generated `@workspace/api-client-react` hooks.
- Retrofitting `DESIGN.md` tokens, a component-testing framework (jsdom/React Testing Library), or any other infrastructure not already present in `pcs-control-panel-project` — out of scope unless a later task explicitly asks for it.

## Design conventions (replaces `DESIGN.md` for this task)

- Match `App.tsx`'s existing look as already built: the off-white "paper" palette, the local `Button`/`Badge`/`Stat`/`PageHeader`/`ProjectTabs`/`ErrorBanner` components, the `data-testid` naming convention, and `toast()`/`notifyError()` for all mutation feedback (per the pattern already established across Dashboard/Requirements/CodeIndex/CodeMap).
- Keyboard accessibility and screen-reader basics (semantic HTML, labeled inputs, focus handling on the claim/edit modals) are still required — this bar doesn't move, only the visual token system does.

## Invariants

- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Web UI operations reflect server-confirmed truth without speculative optimistic writes; mutations invalidate project queries. (The `DESIGN.md` clause of this invariant's statement is superseded by the "Design conventions" section above for this codebase.)

## Requirements

- Add route `/projects/:project/plans` and a corresponding nav item labeled "Plans" in `AppShell`'s nav (alongside Dashboard/Requirements/Code index/Code map).
- Provide Plan List view:
  - Displays all plans in the active project with title, goal, status (`draft`, `active`, `completed`, `archived`), task progress counter (`completed / total`), and created timestamp.
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
  - Filter toggle for "Ready Tasks" (tasks matching canonical ready predicate: active plan, prerequisites completed, status is `ready` or lease is expired [`lease_expires_at <= now()`] across `claimed`, `in_progress`, or `in_review`) — implemented in `lib/planTasks.ts` as a pure, tested function.
  - Task item card displaying: local ID, title, status badge (`pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`), assignee / `claimed_by`, lease expiration countdown/indicator ("Expired - Reclaimable" when `lease_expires_at <= now()` for `claimed`, `in_progress`, or `in_review` tasks), and linked requirement tags.
- Task orchestration controls using nested endpoints:
  - `claim_task`: Prompts for `claimed_by` name, lease seconds; calls `POST .../plans/{plan_id}/tasks/{task_id}/claim`; stores the returned one-time claim token in `localStorage` (same storage mechanism already used for the admin token — namespaced per task_id). Supports initial claim on `ready` tasks and atomic reclaim on expired (`lease_expires_at <= now()`) `claimed`, `in_progress`, or `in_review` tasks.
  - `heartbeat_task`: Extends active lease for the currently claimed task via `POST .../plans/{plan_id}/tasks/{task_id}/heartbeat` using the stored token; strictly preserves current task status (`claimed` remains `claimed`, `in_progress` remains `in_progress`).
  - `release_task`: Relinquishes active claim lease back to `ready` via `POST .../plans/{plan_id}/tasks/{task_id}/release`, clearing the stored token.
  - `set_task_status`: Transitions task status (e.g. `claimed -> in_progress`, `in_progress -> in_review`, `in_progress -> blocked`) via `POST .../plans/{plan_id}/tasks/{task_id}/status` using the active token.
  - `complete_task`: Transitions task to `completed` via `POST .../plans/{plan_id}/tasks/{task_id}/complete` using the active token (or tokenless only if no active lease / lease has expired [`lease_expires_at <= now()`]).
  - Active lease token enforcement: Mutations on tasks with active leases (`lease_expires_at > now()`) strictly require the valid stored claim token; the UI provides no "operator bypass" toggle. Attempting a mutation without a valid token on an active lease shows a `notifyError` toast/conflict banner and disables the action.
  - Visual error/conflict banner (reusing the existing `ErrorBanner` component) when a mutation fails due to lease expiry (409 Conflict), stale token (409 Conflict), or concurrent claiming. On stale token, clears the invalid local token.
- Task history drill-down:
  - Modal or expandable drawer showing append-only `plan_task_events` from `GET .../plans/{plan_id}/tasks/{task_id}/history`:
    - Event type badge (`created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled`).
    - Transition indicators (`old_status -> new_status`).
    - Actor identity and formatted timestamp.
    - Formatted display of structured `payload` details (e.g. updated fields, claimant, lease duration, transition reason).
- Prompt preparation integration seam:
  - "Copy agent prompt" button on task cards; calls T25's `prepare_task(task_id=...)` (already merged) and copies the resulting Markdown to the clipboard via the same pattern as the existing `copyBriefing`/`copySource` handlers.
- State management:
  - Server state managed entirely via TanStack Query with project-scoped query keys (matching the orval-generated hooks' own key convention, e.g. `['/api/projects/{project}/plans', ...]`).
  - No optimistic mutations; UI transitions occur only upon server HTTP 2xx confirmation.
  - Mutation `onSuccess` invalidates relevant queries to fetch fresh server state (same pattern as every existing mutation in `App.tsx`).

## Acceptance checklist

- [ ] `AC-PLAN-11` (`98f519b5-6bed-491c-b2a7-ed4150118c91`): Plans UI provides manual creation, DAG visualization, ready-task filter, claim/heartbeat/release controls, and conflict feedback.
- [ ] `AC-PLAN-12` (`5187dff3-9823-49c8-9307-669b99b24976`): Frontend mutations only update state upon server confirmation and invalidate project queries without stale state.
- [ ] Navigation link to `/projects/:project/plans` renders correctly in the sidebar.
- [ ] Plan list and detail views render correctly with progress counters, edit plan modal, and archive action.
- [ ] All task mutations use nested `/plans/{plan_id}/tasks/{task_id}/...` endpoints.
- [ ] Ready-task filter (in `lib/planTasks.ts`) accurately filters tasks whose dependencies are satisfied, including expired `in_review` tasks (`lease_expires_at <= now()`).
- [ ] Expired lease display alerts user that task is available for reclamation ("Expired - Reclaimable") across `claimed`, `in_progress`, and `in_review` states when `lease_expires_at <= now()`.
- [ ] Exact boundary condition `lease_expires_at == now()` is rendered as expired ("Expired - Reclaimable") and included in the ready-tasks filter.
- [ ] Task claim modal captures lease duration, stores the token, and updates UI to claimed state upon server confirmation.
- [ ] Reclaim of expired `in_review` task transitions UI to `claimed` with a fresh lease.
- [ ] Heartbeat extends the active lease while preserving exact task status (`claimed` stays `claimed`, `in_progress` stays `in_progress`).
- [ ] Mutations on tasks with active leases (`lease_expires_at > now()`) strictly require the active claim token; missing or invalid token shows a conflict banner.
- [ ] 409 Conflict / StaleClaimToken error shows a clear conflict banner and clears the stale local token.
- [ ] Task event history drawer displays chronologically ordered audit events with structured payload data across all event types.
- [ ] Independent UI review confirms the new pages are visually and behaviorally consistent with the rest of `pcs-control-panel-project` (per "Design conventions" above) and are reachable end-to-end through the actual deployed Docker container, not just `pnpm dev`.
- [ ] `just check` passes cleanly for the server portion; `pnpm --filter @workspace/pcs-control-panel run typecheck` and `pnpm exec vitest run` and a production `vite build` all pass cleanly for the frontend portion (there is no top-level `just check` step for `pcs-control-panel-project` yet).

## Required evidence

- Unit tests for `lib/planTasks.ts` in `lib/planTasks.test.ts` (ready-task predicate, lease-expiry boundary at exactly `now()`, DAG ordering) — mirrors the existing `lib/codemap.test.ts` coverage bar.
- `pnpm exec tsc --noEmit`, `pnpm exec vitest run`, and a production `vite build` all green.
- A real end-to-end smoke test against the actual `pcs-server-1` Docker container (rebuild + curl/verify, the same method used to verify T20's control-panel migration and the requirements status filter) — not just `pnpm dev` against localhost, since that's what will actually ship.
- Independent UI review confirmation (see acceptance checklist).

## Verification

```bash
cd pcs-control-panel-project/artifacts/pcs-control-panel
pnpm exec tsc --noEmit -p tsconfig.json
pnpm exec vitest run
PORT=5173 BASE_PATH=/ pnpm exec vite build
cd ../../.. && just check   # server side is unaffected but must stay green
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T27-plans-ui`
- **What was done:**
  - Regenerated `@workspace/api-client-react` to cover the T24 planning routes
  - Added `/projects/:project/plans` route, nav entry, and `Plans.tsx` view
  - Implemented `lib/planTasks.ts` (ready predicate, lease boundary, DAG helpers) with tests
  - Built DAG visualization, ready filter, edit/archive plan actions, and lease-aware claim controls
  - Created structured task history drawer and conflict handling banners
- **Design conventions review:**
  - Confirmed visual/behavioral consistency with the rest of `pcs-control-panel-project` (no `DESIGN.md` audit — out of scope per the 2026-09-15 retarget)
  - Accessibility basics verified (labeled inputs, focus handling, semantic HTML)
- **Verification:**
  - `planTasks.test.ts` output
  - `tsc`/`vitest`/`vite build` results
  - Docker rebuild + real end-to-end smoke test results
  - `just check` (server) green result
- **Deviations:** Retargeted from `web/` to `pcs-control-panel-project`; `DESIGN.md` compliance dropped per explicit user decision (see note at top of this file). No component-testing framework (jsdom/RTL) was added — coverage is via `lib/planTasks.ts` unit tests plus a real Docker smoke test instead.
```
