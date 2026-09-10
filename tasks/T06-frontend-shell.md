# T06 — Frontend shell + context dashboard

**Branch:** `task/T06-frontend-shell`  ·  **Depends on:** T01, T02  ·  **Blocks:** T07

> Stub — flesh out after T01/T02.

## Goal
The frontend application shell and everything that isn't the code map: project
picker, context dashboard, requirements view, index-status panel — all in the
`DESIGN.md` language.

## In scope
- Design system layer from `DESIGN.md` (extends the T00 token plumbing): the
  documented components (pill nav/button, cards, badges, section headline,
  highlighted word) as reusable React components. Normative: `DESIGN.md`
  Do's/Don'ts (FR39a, NFR15).
- Project picker with one-line status (FR31).
- Context dashboard: overview/focus/blockers/bugs/conventions/decisions, with
  create/update/resolve editing wired to the MCP/HTTP write surface (FR36).
- Requirements view: list + status + "N of M done", add + status change; edits
  flow through the store and back to the file (FR36a).
- Index-status panel + "reindex now" (FR37); semantic-unavailable indicator (AC21).
- Manual refresh control re-fetching everything; no live push (FR38, D6).
- Typed API client + TanStack Query; no `fetch` in components.

## Key requirements
FR30, FR31, FR36, FR36a, FR37, FR38, FR39a, NFR13, NFR15, D6, D17.
ACs: AC14, AC14a, AC21, AC27.

## Acceptance checklist
- [ ] Computed styles resolve to `DESIGN.md` tokens, not literals; no "Don't"-list violations (AC27)
- [ ] Dashboard edit reflected in next `get_project_briefing` and vice versa (AC14)
- [ ] Requirements view shows accurate N/M; store change and file change both reflected (AC14a)
- [ ] Refresh re-fetches; nothing updates without it (D6)
- [ ] `eslint` + `tsc --noEmit` + `vitest` + `vite build` green
- [ ] Handoff written

## Handoff
_(fill in)_
