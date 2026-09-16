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

- [x] `AC-PLAN-10` (`9521864a-18e2-498b-8b09-b24e180580d2`): AI draft persistence occurs only through explicit caller approval via atomic `create_plan_with_tasks`.
- [x] `AC-PLAN-12` (`5187dff3-9823-49c8-9307-669b99b24976`): Frontend mutations only update state upon server confirmation and invalidate project queries without stale state.
- [x] Draft generation modal opens from the Plans page and submits goal/constraints.
- [x] Advisory banner clearly distinguishes the unpersisted proposal from database records.
- [x] Proposal displays ordered tasks, dependencies, linked files, and requirement IDs.
- [x] Discard / Cancel closes the modal without calling the creation endpoint or creating rows.
- [x] "Review & Create" successfully calls atomic `create_plan_with_tasks` and navigates to the new plan.
- [x] Provider-unavailable state displays clear guidance without crashing.
- [x] Double-submit prevention verified on both draft generation and approval actions.
- [x] Independent UI review confirms the modal is visually/behaviorally consistent with `pcs-control-panel-project` and is reachable end-to-end through the actual deployed Docker container.
- [x] `just check` passes cleanly for the server portion; `tsc`/`vitest`/`vite build` pass cleanly for the frontend portion.

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

## Handoff

- **Branch:** `main` (worked directly; no separate task branch was created for this session)
- **What was done:**
  - `lib/api-spec/openapi.yaml`: added `POST /projects/{project}/plans/generate-draft`
    (T26's `generate_plan_draft`) plus `GeneratePlanDraftInput`,
    `PlanDraft`/`PlanDraftTask`/`PlanDraftDependency`, and
    `GeneratePlanDraftResult` schemas, derived field-for-field from
    `pcs.planning.generator.DraftGenerationResult.as_dict()` and
    `pcs.planning.schemas.PlanDraft/DraftTask/DraftDependency.as_dict()`.
    Regenerated `@workspace/api-client-react`/`api-zod` via orval, producing
    `useGeneratePlanDraft`.
  - `artifacts/pcs-control-panel/src/lib/planDraft.ts` +
    `planDraft.test.ts` (7 tests): two pure functions —
    `draftTasksToPlanTasks` maps an unpersisted `PlanDraft` (tasks/deps keyed
    by `local_task_id`, no server id yet) into T27's `PlanTask` shape so
    `DagView` can be **reused as-is** for the draft preview (id =
    `local_task_id`, status = `'pending'` placeholder, lease fields `null`,
    `dependencies` resolved from the draft's separate edge list into each
    task's own array, matching how real `PlanTask.dependencies` works) — and
    `draftToCreatePlanWithTasksInput` maps the same draft into the exact
    `POST /plans/with-tasks` body shape for the approval action.
  - `artifacts/pcs-control-panel/src/components/plans/AiPlanDraftModal.tsx`:
    two-step modal — **input** (goal textarea with a live char counter,
    optional constraints textarea, a max-tasks range slider 1–30 defaulting
    to 10, Cancel/Generate) and **preview** (advisory banner naming
    provider/model, title/goal/notes, one card per proposed task showing
    local id, title, objective, acceptance criteria, linked-file and
    requirement-id badges, the reused `DagView` for dependencies when any
    exist, Back/Discard/"Review & Create"). A `warning` from an `ok:false`
    result stays on the input step (so the user can edit and retry) rather
    than advancing; a link to `/settings/ai` appears only when the warning
    text names AI Settings (the unconfigured/unreachable-provider cases),
    not for a malformed-draft validation warning. Implements a real focus
    trap (Tab/Shift+Tab cycling within the dialog), Escape-to-close, focus
    return to the trigger element on unmount, and `role="dialog"` +
    `aria-modal` + `aria-labelledby`.
  - `artifacts/pcs-control-panel/src/pages/Plans.tsx`: added a "Generate with
    AI" header button (`Sparkles` icon, secondary style, next to "New plan")
    and `aiDraftOpen` state; `onCreated` invalidates every planning query for
    the project (reusing T27's `invalidatePlanningQueries`), selects the new
    plan (`setSelectedPlanId`) so its detail renders immediately — the
    page's existing master-detail layout stands in for "navigate to the new
    plan detail," since there's no separate per-plan route — and closes the
    modal.
  - **Found and fixed a real, pre-existing server bug while running the
    required live-provider smoke test** (see Deviations) —
    `server/src/pcs/ai_settings.py`'s `ValidatedEndpoint.request_extensions`
    passed `sni_hostname` as `bytes` (`self.host.encode("ascii")`); httpx's
    **async** transport (anyio backend, used by `httpx.AsyncClient`) crashes
    on that with `AttributeError: 'bytes' object has no attribute 'encode'`
    inside `anyio.streams.tls.TLSStream.wrap` → `idna2008_resolve`, which
    expects `str` and encodes it itself. The **sync** `httpx.Client` path
    (T20's `Summarizer._call_backend`) tolerates bytes by accident via a
    different backend, which is why this was never caught before. Changed
    the property to return the plain `str` `self.host`. This affects every
    async caller of `resolve_provider_endpoint` over HTTPS — `generator.py`
    (this task), and `pcs/index/embedding.py`'s embedding generation, which
    was silently failing the same way for any HTTPS embedding provider
    (masked on this instance because its configured embedding provider is
    plain HTTP, not HTTPS, so `sni_hostname` never entered the TLS path).
    Updated `tests/test_ai_settings.py`'s
    `test_embedding_connection_is_pinned_against_dns_rebinding`, which
    asserted `request.extensions["sni_hostname"] == b"example.com"` — i.e.
    it enshrined the bug instead of catching it, since that test's mocked
    transport never exercises the real TLS handshake code path. Fixed to
    assert the `str` value.
- **Design conventions review:**
  - `AiPlanDraftModal` reuses `Button`/`Badge`/`ErrorBanner`/the shared
    palette and `data-testid` convention, and reuses T27's `DagView`
    component directly for the dependency preview rather than building a
    second visualizer.
  - Dialog accessibility verified both in code and by driving the real
    rendered page (focus trap, Escape, ARIA attributes) — see Verification.
  - No `DESIGN.md` audit performed (out of scope per the 2026-09-15 retarget
    note); no component-testing framework added.
- **Verification:**
  - `pnpm --filter @workspace/pcs-control-panel run typecheck` — clean, 0
    errors (required one `tsc --build` of `lib/api-client-react`'s composite
    project reference first, same as T27, to refresh its `.d.ts` output
    after regenerating the client).
  - `pnpm exec vitest run` — 3 files, 62 tests passed (7 new in
    `planDraft.test.ts`; 55 pre-existing from T27).
  - `PORT=5173 BASE_PATH=/ pnpm exec vite build` — succeeded.
  - `cd server && just check` — full pass after the `ai_settings.py` fix:
    ruff, mypy (115 files), backend pytest (402 passed, 1 skipped,
    including the corrected `test_ai_settings.py` assertion), `web/` eslint
    + vitest (76 passed) + build, `docker compose config` for both compose
    files.
  - Real Docker end-to-end smoke test against the live `pcs-server-1`
    container (rebuilt twice: once to discover the TLS bug against the
    actual configured provider, once more after the fix), using the
    `t27-smoke-test` project from T27:
    - **Before the fix**, `POST .../plans/generate-draft` against the real
      configured summary provider (`openai-compatible`,
      `https://apithat.dev/v1`, `gemini-3.1-flash-lite` — confirmed via
      `GET /api/admin/ai-settings`) returned
      `{"ok": false, "warning": "AI provider request failed or timed out. Try again or check AI Settings."}`
      every time; a hot-patch + a standalone async-httpx repro script run
      inside the container (`docker exec … python3`) reproduced the actual
      `AttributeError` with a full traceback, confirming the root cause
      before touching any source file.
    - **After the fix and a proper image rebuild**: real generation
      succeeded end-to-end. One early attempt returned
      `ok:false` with `"Provider referenced unknown requirement id(s): [...]"`
      (the model referenced a requirement id not present in the project —
      generator.py's own AC-PLAN-9 cross-project/hallucination guard
      correctly rejected it); a follow-up prompt asking the model not to
      reference requirement ids produced a valid 2–3-task draft with a
      dependency edge, which was then approved via
      `POST /plans/with-tasks` → **HTTP 201** with the plan and both tasks
      persisted exactly as drafted.
    - Drove the **actual browser-rendered page** (not just curl) with a
      headless Chromium + `puppeteer-core` script (`executablePath:
      /usr/bin/chromium`, no separate browser download) against the live
      container: opened the Plans page, clicked "Generate with AI", typed a
      goal, submitted, and screenshotted (a) the input form with the char
      counter and slider, (b) the preview step — advisory banner naming
      `openai-compatible · gemini-3.1-flash-lite`, 3 ordered task cards with
      acceptance criteria, and the reused `DagView` showing "No
      prerequisites" → "Depth 1" → "Depth 2" with a labeled
      `setup-route → implement-logic → verify-endpoint` chain — (c) clicked
      "Review & Create" and screenshotted the result: modal closed, a "Plan
      created — … 3 task(s)." toast, and the new plan immediately selected
      and visible in the detail pane with all 3 tasks. Also reproduced and
      screenshotted the validation-warning state (an intentionally
      requirement-inviting goal) showing the red warning banner inline on
      the input step, with **no** "Open AI settings" link (correct — it's a
      draft-validation warning, not a provider-configuration one) and the
      modal still fully usable for a retry.
    - Archived both plans created during the smoke test afterward via
      `archive_plan`, same cleanup pattern as T27.
- **Deviations:**
  - Retargeted from `web/` to `pcs-control-panel-project`; `DESIGN.md`
    compliance dropped per explicit user decision. No component-testing
    framework added, per T27's note.
  - **Cross-task fix, not originally scoped to T28's owned files**: the
    `sni_hostname` bytes→str fix in `server/src/pcs/ai_settings.py` (plus the
    one corrected test assertion in `server/tests/test_ai_settings.py`). This
    is server code T28's own spec says not to touch, but it directly blocked
    the task's required "real end-to-end smoke test... against a real,
    running AI provider" acceptance criterion — the provider call crashed
    every time, for a genuine pre-existing bug, not a config issue. Fixing
    root causes rather than working around them, and per T29's own scope
    anticipating exactly this ("minimal cross-task fixes strictly
    demonstrated by failing integration tests, must be documented in
    handoff") — documented here since it surfaced during T28, verified with
    the full `just check` suite plus a live re-test against the real
    provider, and T29 will inherit it already fixed rather than rediscover
    it.
