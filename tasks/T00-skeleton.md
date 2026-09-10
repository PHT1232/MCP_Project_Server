# T00 — Walking skeleton

**Branch:** `task/T00-skeleton`  ·  **Depends on:** nothing  ·  **Blocks:** everything

## Goal

Stand up the monorepo and prove one MCP tool works end to end — over both stdio
and HTTP — backed by real PostgreSQL, with the full check/CI toolchain and a
frontend that renders one page from the `DESIGN.md` design system. This task
**sets the conventions** every later task follows, so favor clarity over
cleverness and write the structure others will copy.

## In scope

### Repo / tooling
- `justfile` at repo root with at least: `setup`, `check` (runs everything),
  `fmt`, `lint`, `typecheck`, `test`, `migrate`, `up` (compose up), `down`,
  `accept` (takes a task id; no-op stub for now).
- `server/pyproject.toml` via **uv**: deps for `mcp`, `sqlalchemy[asyncio]`,
  `psycopg[binary]`, `alembic`, `pydantic-settings`, `pytest`, `pytest-asyncio`,
  `testcontainers[postgresql]`, `ruff`, `mypy`. ruff + mypy(strict) config here.
- `web/` via npm: Vite + React + TS (strict), Tailwind v4, eslint, vitest.
  Tailwind `@theme` populated from `DESIGN.md` Quick Start block; a `tokens.css`
  or equivalent as the single style source.
- `.github/workflows/ci.yml`: runs `just check` on push/PR, with a Postgres
  service (or testcontainers) available.
- `.env.example` documenting every config var the skeleton reads.

### Server
- `pcs.config` — pydantic-settings model (DB URL, host/port, bind mode
  `localhost|tailscale`, log level). Bind mode defaults to `localhost` and the
  HTTP server must bind `127.0.0.1` (NFR14) — tailscale is a later task, just
  leave the seam.
- `pcs.db` — async engine/session wiring; Alembic set up with **one baseline
  migration** creating `projects` and a minimal `context_entries` table
  (id, project_id, section, headline, detail, status, author, created_at,
  updated_at). Keep it minimal — T01 owns the real schema and will migrate it.
- `pcs.mcp` — FastMCP app exposing exactly two tools:
  - `register_project(name, root_path, overview)` → creates a project row + an
    `overview` context entry. Enforces explicit project everywhere (D3).
  - `get_project_briefing(project)` → returns overview + current focus only,
    plain text, token-bounded to a hardcoded 1500 (FR9, real logic is T01).
  - `set_current_focus(project, text)` → so the briefing has something to show.
- Both **stdio** and **streamable HTTP** transports runnable (`just` targets or
  CLI flags). Every tool call logs project/caller/outcome (NFR6).
- One non-MCP HTTP endpoint `GET /api/health` and `GET /api/projects` for the
  frontend to call.

### Frontend
- One page: lists projects from `GET /api/projects`, lets you type a name +
  overview and call register (via a typed API client + TanStack Query), shows
  the briefing text for a selected project.
- Rendered in the `DESIGN.md` language: Fey Ink canvas, Calibre stack, a pill
  button, a 16px card, one Signal-blue active underline. This is the reference
  other frontend tasks copy — get the token plumbing right, not the feature set.

### Tests
- Integration test: spin up Postgres (testcontainers), run migrations,
  `register_project` then `get_project_briefing` returns the overview — exercised
  through the MCP tool layer, once via in-process and asserting the HTTP app
  mounts.
- Frontend: one vitest test on the API client; `vite build` succeeds.

## Out of scope
- Real §7.2a sizing, audit log, other sections, expiry (T01).
- Any indexing, code map, search (T03–T05).
- Docker image hardening, Tailscale (T08) — but the compose file for **Postgres**
  must exist and `just up` must start it.
- Auth, multi-project resolution beyond explicit param.

## Key requirements
FR4 (Postgres), FR5/FR8 (briefing + explicit project), FR14 (register), NFR3
(compose + stdio + HTTP), NFR6 (logging), NFR14 (localhost bind), FR39a/NFR15
(frontend tokens), D1/D3.

## Acceptance checklist
- [ ] `just setup && just check` green from a clean clone (Postgres via testcontainers or compose)
- [ ] `just up` starts Postgres; `just migrate` applies the baseline from empty
- [ ] MCP server runs over stdio and over HTTP bound to `127.0.0.1`
- [ ] `register_project` + `set_current_focus` + `get_project_briefing` work end to end (integration test proves it)
- [ ] A call with an unknown `project` returns an error listing projects (D3, AC16 seed)
- [ ] Every tool call emits a structured log line with project/caller/outcome
- [ ] Frontend page registers a project and shows its briefing, served from `DESIGN.md` tokens (no literal hex/px in components)
- [ ] `vite build` + `tsc --noEmit` + `eslint` + `vitest` all green
- [ ] CI runs `just check` and passes
- [ ] `.env.example` covers every var read by the skeleton
- [ ] Handoff written below

## Handoff
_(fill in: final module layout, how to run each piece, naming decisions made,
anything T01–T08 should know, deviations, new deps and why.)_
