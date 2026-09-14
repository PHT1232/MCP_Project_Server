# T28 — AI Plan Draft Generation Web UI

**Branch:** `task/T28-ai-plan-ui` · **Depends on:** T25, T26, T27 · **Blocks:** T29

## Goal

Integrate advisory AI plan draft generation into the Plans UI (`/projects/:project/plans`), rendering structured, unpersisted draft proposals with task ordering, DAG dependencies, linked requirements, and validation warnings, and requiring an explicit "Review & Create" approval action that atomically persists the plan via `create_plan_with_tasks`.

## Owned files/modules

- `web/src/components/plans/AiPlanDraftModal.tsx` (and associated draft preview components)
- Additions (*sequenced shared seam* on merged T27):
  - `web/src/api/planning.ts` (`generatePlanDraft`, `useGeneratePlanDraftMutation`)
  - `web/src/views/PlansView.tsx` (trigger button and draft modal state wiring)
- `web/src/components/plans/AiPlanDraftModal.test.tsx`
- `tasks/T28-ai-plan-ui.md`

*Sequenced Shared Integration Seam:* T28 builds upon merged T27. It hooks the AI draft generation modal into `PlansView.tsx` and adds the mutation hook to `planning.ts` without modifying base plan presentation or task lifecycle components.

Do not touch server backend code, non-planning web views, or core storage models.

## Non-goals

- Automatic plan approval, automatic task claiming, or agent process dispatch.
- Persisting drafts to the database before explicit user approval.
- Storing AI provider credentials, secrets, or claim tokens in client state or caches.
- Executing proposed shell commands or scripts.

## Invariants

- `INV-PLAN-6` (`56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`): AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks.
- `INV-PLAN-7` (`78c2bf3b-1e07-4a6b-b80f-3272f56200b9`): Web UI operations reflect server-confirmed truth without speculative optimistic writes; mutations invalidate project queries; DESIGN.md tokens are followed.

## Requirements

- Add "Generate with AI" action in Plans view header.
- Provide Draft Input Form:
  - Plan goal (required textarea with character counter).
  - Optional guidance/constraints (textarea).
  - Max tasks slider/input (default 10, bounds 1–30).
  - Submit button with loading spinner and double-submit prevention.
- Display Unpersisted Proposal:
  - Visual callout distinguishing advisory draft from stored project truth (e.g., draft banner with AI provider/model attribution).
  - Proposed plan title and overall objective.
  - Ordered task breakdown showing local IDs, titles, objectives, acceptance criteria, linked files, and requirement IDs.
  - Visual representation of proposed prerequisite dependencies between tasks.
  - Display any validation warnings or schema warnings returned by the server.
- Approval and Rejection Flow:
  - "Cancel / Discard" button: Closes modal and clears local state; zero server mutations occur.
  - "Review & Create" primary action button:
    - Invokes `POST /api/projects/{project}/plans/with-tasks` with the proposed payload.
    - Displays loading state and disables repeated clicks.
    - Upon HTTP 201 confirmation: closes modal, invalidates plan queries, navigates to the newly created plan detail, and displays success toast.
- Robust Error Handling:
  - AI provider unconfigured or unavailable: Render helpful configuration warning directing user to AI settings (T20).
  - Provider timeout or rate limit: Display retryable error message.
  - Validation error or malformed draft: Render specific server error message without persisting data.
- Strict token-based styling complying with `DESIGN.md`:
  - No raw hex colors, hard-coded pixel sizing, or custom box-shadows.
  - Modal follows accessible dialog patterns (keyboard traps, Escape to close, ARIA attributes).

## Acceptance checklist

- [ ] `AC-PLAN-10` (`9521864a-18e2-498b-8b09-b24e180580d2`): AI draft persistence occurs only through explicit caller approval via atomic `create_plan_with_tasks`.
- [ ] `AC-PLAN-12` (`5187dff3-9823-49c8-9307-669b99b24976`): Frontend mutations only update state upon server confirmation and invalidate project queries without stale state.
- [ ] Draft generation modal opens from Plans view and submits goal/constraints.
- [ ] Advisory banner clearly distinguishes unpersisted proposal from database records.
- [ ] Proposal displays ordered tasks, dependencies, linked files, and requirement IDs.
- [ ] Discard / Cancel closes modal without calling creation endpoint or creating rows.
- [ ] "Review & Create" successfully calls atomic `create_plan_with_tasks` and navigates to the new plan.
- [ ] Provider unavailable state displays clear guidance without crashing.
- [ ] Double-submit prevention verified on draft generation and approval actions.
- [ ] Independent UI review verifies adherence to `DESIGN.md` tokens.
- [ ] `just check` passes cleanly (ESLint, TypeScript, Vitest, Vite build).

## Required evidence

- Component tests in `web/src/components/plans/AiPlanDraftModal.test.tsx`.
- Vitest results covering input validation, draft preview rendering, cancel disposal, and approval mutation.
- Independent UI review confirmation for `DESIGN.md` compliance.

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

- **Branch:** `task/T28-ai-plan-ui`
- **What was done:**
  - Implemented AI draft generation modal and preview components
  - Connected draft generator API with zero pre-persistence
  - Implemented atomic approval workflow via `create_plan_with_tasks`
  - Handled provider errors, loading states, and cancellation flows
- **Design Review:**
  - Verified draft callout styling against `DESIGN.md`
  - Verified dialog accessibility and keyboard interactions
- **Verification:**
  - Vitest test output
  - `just check` green result
- **Deviations:** None
```
