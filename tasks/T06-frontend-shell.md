# T06 — Frontend shell + context dashboard

**Branch:** `task/T06-frontend-shell`  ·  **Depends on:** T01 + T02 (merged)  ·  **Blocks:** T07

**Read first:** `AGENTS.md`, `DESIGN.md` (normative — its Do's/Don'ts, token
block, and component specs), `REQUIREMENTS.md` FR30/31/36/36a/37/38 + FR39a +
D6/D17 + AC14/AC14a/AC21/AC27, `reviews/T01.md` + `reviews/T02.md` + `reviews/T03.md`
"Notes for dependents → T06", and the T01/T02/T03 handoffs. Base off current `main`.

**What exists (T00 scaffold + T01–T03 HTTP surface):**
- `web/src/`: `styles/tokens.css` (DESIGN.md `@theme` verbatim — the ONLY style
  source), `api/client.ts` + `api/types.ts` (typed client, the only `fetch`
  caller), `hooks/useProjects.ts` (TanStack Query), components `Card`,
  `PillButton`, `ProjectList`, `RegisterForm`, `BriefingPanel`, `App.tsx`.
- Server `/api` routes (all JSON, `x-pcs-caller` header optional):
  - `GET /api/health`, `GET|POST /api/projects`, `PATCH /api/projects/{p}` (budgets/expiry)
  - `GET /api/projects/{p}/briefing?sections=&max_tokens=`
  - `PUT /api/projects/{p}/focus`
  - `GET /api/projects/{p}/sections/{section}`, `POST /api/projects/{p}/entries`,
    `GET|PATCH|DELETE /api/projects/{p}/entries/{id}`, `POST …/entries/{id}/resolve`,
    `GET …/entries/{id}/history`
  - `GET /api/projects/{p}/requirements` → `{requirements[], done_count, total_count}`;
    `POST /api/projects/{p}/requirements/sync` → `SyncReport.as_dict()`
  - `GET /api/projects/{p}/index`, `POST /api/projects/{p}/reindex`,
    `GET /api/projects/{p}/search?q=&scope=&subtree=&files=&globs=&limit=`
- Entry JSON carries `req_key`; requirement write responses carry a
  `requirements_file` object (`{path, written, errors, reconciliations}`) —
  surface `errors` to the user (AC14a).
- Sections: `overview, focus, blockers, bugs, conventions, decisions, requirements, glossary`.
  Requirement status tokens: `not-started | in-progress | blocked | done`.
- **S-T06 from reviews/T01.md:** `add_focus`/`update_focus`/`resolve_focus` exist
  alongside `set_current_focus` — pick one model for the dashboard (recommend
  `set_current_focus` replace-semantics; don't surface the generic focus CRUD).

**Out of scope:** the code map / graph / node inspector / code search UI — all T07.
You build the shell T07 mounts into.

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
