# T28 — AI Plan Draft Generation Control Panel UI

**Branch:** `task/T28-ai-plan-ui` · **Depends on:** T25, T26, T27 · **Blocks:** T29

> **Retargeted 2026-09-15:** same retarget as T27 — build against
> `pcs-control-panel-project`, not `web/`, and follow that app's own
> established visual conventions instead of `DESIGN.md`. See the note at the
> top of `tasks/T27-plans-ui.md` for the full rationale. Everything else in
> the original spec (functional requirements, approval-flow semantics,
> acceptance criteria content) is unchanged.

## Goal

Integrate advisory AI plan draft generation into the Plans page (`/projects/:project/plans`), rendering structured, unpersisted draft proposals with task ordering, DAG dependencies, linked requirements, and validation warnings, and requiring an explicit "Review & Create" approval action that atomically persists the plan via `create_plan_with_tasks`.

## Owned files/modules

- `pcs-control-panel-project/artifacts/pcs-control-panel/src/components/plans/AiPlanDraftModal.tsx` (and associated draft preview components)
- `pcs-control-panel-project/lib/api-spec/openapi.yaml` + regenerated `@workspace/api-client-react` output: add T26's `POST /api/projects/{project}/plans/generate-draft` route (*sequenced shared seam* on merged T26 — appends to the spec, doesn't touch the T24 routes T27 already added)
- Additions (*sequenced shared seam* on merged T27):
  - `pcs-control-panel-project/artifacts/pcs-control-panel/src/pages/Plans.tsx` (trigger button and draft modal state wiring)
- `pcs-control-panel-project/artifacts/pcs-control-panel/src/components/plans/AiPlanDraftModal.test.tsx` — see "Required evidence" below on scope
- `tasks/T28-ai-plan-ui.md`

*Sequenced Shared Integration Seam:* T28 builds upon merged T27. It hooks the AI draft generation modal into `Plans.tsx` and adds the generated draft mutation hook without modifying base plan presentation or task lifecycle components.

Do not touch server backend code, non-planning pages, the legacy `web/` tree, or core storage models.

## Non-goals

- Automatic plan approval, automatic task claiming, or agent process dispatch.
- Persisting drafts to the database before explicit user approval.
- Storing AI provider credentials, secrets, or claim tokens in client state or caches.
- Executing proposed shell commands or scripts.
- Retrofitting `DESIGN.md` tokens or a component-testing framework not already present in `pcs-control-panel-project` (see T27's note).

## Invariants

- `INV-PLAN-6` (`56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`): AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks.
- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Web UI operations reflect server-confirmed truth without speculative optimistic writes; mutations invalidate project queries. (The `DESIGN.md` clause is superseded for this codebase — see T27's retarget note.)

## Requirements

- Add "Generate with AI" action in the Plans page header.
- Provide Draft Input Form:
  - Plan goal (required textarea with character counter).
  - Optional guidance/constraints (textarea).
  - Max tasks slider/input (default 10, bounds 1–30).
  - Submit button with loading spinner and double-submit prevention.
- Display Unpersisted Proposal:
  - Visual callout distinguishing the advisory draft from stored project truth (draft banner with AI provider/model attribution).
  - Proposed plan title and overall objective.
  - Ordered task breakdown showing local IDs, titles, objectives, acceptance criteria, linked files, and requirement IDs.
  - Visual representation of proposed prerequisite dependencies between tasks (reuse T27's DAG visualizer component where practical).
  - Display any validation warnings or schema warnings returned by the server.
- Approval and Rejection Flow:
  - "Cancel / Discard" button: closes the modal and clears local state; zero server mutations occur.
  - "Review & Create" primary action button:
    - Invokes `POST /api/projects/{project}/plans/with-tasks` with the proposed payload.
    - Shows a loading state and disables repeated clicks.
    - Upon HTTP 201 confirmation: closes the modal, invalidates plan queries, navigates to the newly created plan detail, and shows a success toast (`notify(...)`, matching the existing pattern).
- Robust Error Handling (via `notifyError(...)`, matching the existing pattern):
  - AI provider unconfigured or unavailable: render a helpful configuration warning linking to the AI Settings page (T20; already live in this app).
  - Provider timeout or rate limit: display a retryable error message.
  - Validation error or malformed draft: render the specific server error message without persisting data.
- Modal follows accessible dialog patterns (keyboard traps, Escape to close, ARIA attributes, focus return on close) and visually matches `pcs-control-panel-project`'s existing modal/form styling (see T27's "Design conventions" section — no separate token audit here).

## Acceptance checklist

- [ ] `AC-PLAN-10` (`9521864a-18e2-498b-8b09-b24e180580d2`): AI draft persistence occurs only through explicit caller approval via atomic `create_plan_with_tasks`.
- [ ] `AC-PLAN-12` (`5187dff3-9823-49c8-9307-669b99b24976`): Frontend mutations only update state upon server confirmation and invalidate project queries without stale state.
- [ ] Draft generation modal opens from the Plans page and submits goal/constraints.
- [ ] Advisory banner clearly distinguishes the unpersisted proposal from database records.
- [ ] Proposal displays ordered tasks, dependencies, linked files, and requirement IDs.
- [ ] Discard / Cancel closes the modal without calling the creation endpoint or creating rows.
- [ ] "Review & Create" successfully calls atomic `create_plan_with_tasks` and navigates to the new plan.
- [ ] Provider-unavailable state displays clear guidance without crashing.
- [ ] Double-submit prevention verified on both draft generation and approval actions.
- [ ] Independent UI review confirms the modal is visually/behaviorally consistent with `pcs-control-panel-project` and is reachable end-to-end through the actual deployed Docker container.
- [ ] `just check` passes cleanly for the server portion; `tsc`/`vitest`/`vite build` pass cleanly for the frontend portion.

## Required evidence

- Any pure logic extracted for schema/response shaping (e.g. mapping the draft response into the DAG visualizer's input shape) lives in a testable `lib/` module with Vitest coverage, matching T27's `lib/planTasks.ts` convention. A full `AiPlanDraftModal.test.tsx` component-render test is optional, not required — this app has no jsdom/React Testing Library setup yet (see T27's note); don't add that infrastructure just for this task unless asked.
- `pnpm exec tsc --noEmit`, `pnpm exec vitest run`, and a production `vite build` all green.
- A real end-to-end smoke test against the actual `pcs-server-1` Docker container (rebuild + verify the full generate -> review -> approve flow against a real, running AI provider or a clearly-surfaced "not configured" state).
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

- **Branch:** `task/T28-ai-plan-ui`
- **What was done:**
  - Regenerated `@workspace/api-client-react` to cover T26's `generate-draft` route
  - Implemented AI draft generation modal and preview components in `Plans.tsx`
  - Connected draft generator API with zero pre-persistence
  - Implemented atomic approval workflow via `create_plan_with_tasks`
  - Handled provider errors, loading states, and cancellation flows
- **Design conventions review:**
  - Confirmed visual/behavioral consistency with the rest of `pcs-control-panel-project` (no `DESIGN.md` audit — out of scope per the 2026-09-15 retarget)
  - Verified dialog accessibility and keyboard interactions
- **Verification:**
  - `tsc`/`vitest`/`vite build` results
  - Docker rebuild + real end-to-end smoke test results (including a real or clearly-simulated provider-unavailable state)
  - `just check` (server) green result
- **Deviations:** Retargeted from `web/` to `pcs-control-panel-project`; `DESIGN.md` compliance dropped per explicit user decision. No component-testing framework added, per T27's note.
```
