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
- [x] Computed styles resolve to `DESIGN.md` tokens, not literals; no "Don't"-list violations (AC27)
- [x] Dashboard edit reflected in next `get_project_briefing` and vice versa (AC14)
- [x] Requirements view shows accurate N/M; store change and file change both reflected (AC14a)
- [x] Refresh re-fetches; nothing updates without it (D6)
- [x] `eslint` + `tsc --noEmit` + `vitest` + `vite build` green
- [x] Handoff written

## Handoff

**Branch:** `task/T06-frontend-shell` off `main` @ `10fd175`. `just check` green
at repo root (server: ruff + mypy --strict + 77 pytest; web: eslint clean,
`tsc -b --noEmit` clean, 26 vitest, `vite build`; compose-lint). Ran live against
`deploy/docker-compose.yml` — registered a project, added a blocker, set focus,
added a requirement, synced the file, fetched the briefing; the server serves my
built bundle from `PCS_STATIC_DIR` and the SPA catch-all resolves deep links
(`GET /projects/demo/requirements` → 200 shell).

### Component inventory (`web/src/components/`)
| Component | DESIGN.md spec | Notes |
|---|---|---|
| `Card` | Product Showcase Card | `surface` = `card` (Charcoal) / `elevated` (Obsidian); `halo` toggles the single `shadow-xl` black halo |
| `PillButton` | Primary Action Button | ghost, 99px, white text, soft white halo; `size` sm/md. The only button style — no chromatic fill |
| `PillNav` + `PillNavLink` | Pill Navigation Button | active = Fey Signal 1px bottom border + white; Signal used only as a nav accent |
| `Typography` → `Headline`, `Highlight`, `SectionTitle`, `Caption` | Section Headline + Highlighted Word | display/heading tokens carry the −0.08em tracking; `Highlight` = one accent word (ember default / signal) |
| `StatusBadge` + `RequirementStatusBadge` | Status Badge | outlined pill, one tone each: Growth=done, Ember=blocked, Mist=in-progress, Graphite=not-started/resolved. Never blue |
| `fields` → `Field`, `TextInput`, `TextArea`, `Select` | (form wells) | Obsidian well, Smoke border, focus→Mist |
| `Callout` | — | Ember (`alert`) / Graphite (`muted`) notices; no blue |
| `RequirementsFileNotice` | — | renders `requirements_file.errors` + `reconciliations` (AC14a) |
| `EntryForm`, `EntryCard` | — | shared create/edit + one-entry display with inline edit/resolve |
| `AppShell`, `ProjectPicker`, `ProjectList` | — | frame, header switcher, FR31 picker with one-line status |

Design-system source of truth is unchanged: `web/src/styles/tokens.css`
(DESIGN.md `@theme` verbatim). AC27 verified — `grep -rniE '#[0-9a-f]{3,8}'` and
`grep -rnE '[0-9]+px|\[[^]]*px[^]]*\]'` over `web/src/**/*.{ts,tsx,css}` (minus
`tokens.css`) find only prose in doc-comments, no style literals. One inline
`style` remains: the requirements progress meter width (`${pct}%`) — a
data-driven value, not a token.

### Route map (`web/src/routes.ts`, `web/src/router/`)
| Path | View | `/api` routes used |
|---|---|---|
| `/` | `ProjectsView` | `GET /api/projects`, `POST /api/projects` |
| `/projects/:p` | → redirect to `…/dashboard` | — |
| `/projects/:p/dashboard` | `DashboardView` | `GET …/sections/{overview,focus,blockers,bugs,conventions,decisions}`, `POST/PATCH …/entries`, `POST …/entries/{id}/resolve`, `PUT …/focus`, `GET …/briefing` |
| `/projects/:p/requirements` | `RequirementsView` | `GET …/requirements`, `POST …/entries` (section=`requirements`), `PATCH …/entries/{id}`, `POST …/requirements/sync` |
| `/projects/:p/index` | `IndexView` | `GET …/index`, `POST …/reindex` |
| `/projects/:p/code-map` | `CodeMapView` (T07 stub) | — |

Router is a ~120-line History-API implementation (`router/router.tsx` +
`router/context.ts`), no dependency. Split into a JSX file (provider + `Link`)
and a no-JSX file (hooks + `matchPath`) so `react-refresh/only-export-components`
stays quiet.

### Hooks (`web/src/hooks/`)
`useProjects`/`useProject`/`useBriefing`/`useRegisterProject`, `useSection` +
`useEntryMutations`, `useSetFocus`, `useRequirements` + `useRequirementMutations`,
`useIndexStatus` + `useReindex`, `useRefreshAll`. Every mutation `onSuccess`
invalidates its section **and** the briefing (+ requirements where relevant) so
AC14 holds both directions. `QueryClient` keeps the scaffold's
`refetchOnWindowFocus: false`; nothing polls or subscribes (D6). `useRefreshAll`
is the FR38 control — invalidates exactly the current project's queries + the
project list via `isRefreshable(key, project)` and reports `isRefreshing` /
`lastRefreshedAt`.

### Design decisions
- **Focus = `set_current_focus` replace-semantics (S-T06).** `PUT …/focus` with
  `{text}`; the generic `add_focus`/`update_focus`/`resolve_focus` CRUD is not
  surfaced. `FocusPanel` is a single textarea + "Set focus".
- **Overview is edit-only.** Exactly one overview entry exists (from register);
  the panel PATCHes it (`updateEntry`) — no add/resolve. There is no
  `update_overview` HTTP route, but `PATCH …/entries/{id}` works on the overview
  row. If a project somehow has no overview entry the panel shows an empty state
  (can't create one from the UI) — noted as a gap below.
- **Add-requirement goes through `POST …/entries`** with `section:"requirements"`,
  `headline`, `status`; the server's write-through assigns `R-NNN` and writes the
  file. The immediate response's `req_key` is `null` (assigned async), so the
  view invalidates and refetches `GET …/requirements` to show the real key.
- **Multiple status badges per requirements card.** DESIGN.md says ≤1 chromatic
  accent per card; each requirement renders in its own bordered Obsidian
  sub-panel (one badge each), mirroring the Insider Transaction Card's
  one-pill-per-row model. The outer `Card` is a container.
- **Progress meter uses `bg-fey-growth`** as a completion meaning-carrier (not a
  button fill) — analogous to the Ticker's green.
- **`reindex` "Reindex now" = incremental, "Full rebuild" = `{incremental:false}`.**

### Seams for T07
- Mount the code-map view at `web/src/views/CodeMapView.tsx` (route
  `/projects/:p/code-map`, already in `NAV_ITEMS` / `PROJECT_VIEWS`). It receives
  `{ project }`.
- `GET /api/projects/{p}/search?q=&scope=&subtree=&files=&globs=&limit=` is
  **not** yet in `api/client.ts` — add `searchCode()` there (keep client the only
  fetch caller) when wiring the search panel.
- `ProjectPicker` + `AppShell` already provide the selected project everywhere;
  T07 can read the route param via `matchPath` like `App.tsx` does, or lift a
  `useCurrentProject` hook if preferred.
- Query keys live in `api/queryKeys.ts`; add a `codeMap(project, scope)` key and
  it is picked up by the manual refresh automatically via `isRefreshable`.

### Deviations / gaps (please confirm)
- **No server change requested.** Everything needed was already exposed by
  T01–T03's HTTP surface.
- `IndexStatus.semantic_note` is typed optional — T04 has not merged, so the
  live payload only carries `semantic_available:false`. `semanticIndicator()`
  falls back to a default reason; once T04 adds `semantic_note` it is shown
  verbatim. No code change needed then.
- Overview cannot be created from the UI if the single overview entry is missing
  (see above). Low risk — register always creates one.
- Entry history (`GET …/entries/{id}/history`) is not surfaced — FR36 lists only
  create/update/resolve and it was out of the stated scope. Easy add later.
- The requirements "sync" write-through already runs after every requirement
  mutation server-side (T02 N2/deviation 3); the explicit "Sync file" button is
  for the file→store direction and manual reconciliation.

### New dependencies
- `@testing-library/react` + `@testing-library/dom` (**dev only**) — for the
  dashboard edit→refetch render test. No runtime deps added; router is hand-rolled
  to avoid `react-router`.

### Tests (`web`, 26 vitest)
- `api/client.test.ts` — every client function, mocked `fetch`, URL + method +
  body assertions (T00 style).
- `lib/requirements.test.ts` — `doneSummary` / `doneFraction` incl. clamping a
  stale done-count (FR36a "N of M").
- `lib/semantic.test.ts` — `semanticIndicator`: unavailable+default reason,
  server `semantic_note` preferred, available, blank note ignored (AC21).
- `views/DashboardEdit.test.tsx` — render `SectionPanel`, add an entry, assert
  `addEntry` payload then a second `getSection` fetch and the new row (AC14, D6).
