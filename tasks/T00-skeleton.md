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
- [x] `just setup && just check` green from a clean clone (Postgres via testcontainers or compose)
- [x] `just up` starts Postgres; `just migrate` applies the baseline from empty
- [x] MCP server runs over stdio and over HTTP bound to `127.0.0.1`
- [x] `register_project` + `set_current_focus` + `get_project_briefing` work end to end (integration test proves it)
- [x] A call with an unknown `project` returns an error listing projects (D3, AC16 seed)
- [x] Every tool call emits a structured log line with project/caller/outcome
- [x] Frontend page registers a project and shows its briefing, served from `DESIGN.md` tokens (no literal hex/px in components)
- [x] `vite build` + `tsc --noEmit` + `eslint` + `vitest` all green
- [x] CI runs `just check` and passes (workflow added; not executed on GitHub from this branch)
- [x] `.env.example` covers every var read by the skeleton
- [x] Handoff written below

## Handoff

### Final module layout

```
/
  justfile                     # setup, check, fmt, lint, typecheck, test, migrate, up, down, accept
  .env.example                 # every PCS_* var the skeleton reads
  .github/workflows/ci.yml     # runs `just setup` + `just check` on push/PR
  deploy/docker-compose.yml    # Postgres only (pgvector/pgvector:pg16); server+tailscale = T08
  server/
    pyproject.toml             # uv project, build-backend = uv_build; ruff + mypy(strict) + pytest config
    uv.lock
    alembic.ini                # script_location = src/pcs/alembic; URL injected from pcs.config
    src/pcs/
      __init__.py
      __main__.py              # `pcs stdio` | `pcs http` entry point
      config.py                # Settings (pydantic-settings, env prefix PCS_); .bind_host property
      logging.py               # JSON formatter on the `pcs` logger; log_tool_call() (NFR6)
      db/
        base.py                # async engine/sessionmaker (lazy), session_scope(), reset_engine()
        models.py              # Project, ContextEntry (+ SECTION_*/STATUS_* consts)
        __init__.py            # re-exports
      context/
        service.py             # register_project / set_current_focus / get_project_briefing (no MCP/HTTP imports)
        __init__.py
      alembic/
        env.py, script.py.mako
        versions/0001_baseline.py
      mcp/
        server.py              # FastMCP `mcp`, the 3 tools, build_http_app(); calls register_routes(mcp)
        __init__.py            # exports `mcp`, `build_http_app`
      web_api/
        routes.py              # /api/health, /api/projects (GET+POST), /api/projects/{p}/briefing
        __init__.py            # exports register_routes
    tests/
      conftest.py              # session-scoped PostgresContainer + alembic upgrade head; per-test TRUNCATE
      test_integration.py      # end-to-end via service layer AND via mcp.call_tool; HTTP app mount asserts
      test_service_unit.py     # pure token-cap tests (no DB)
  web/
    package.json               # npm; scripts: dev/build/lint/typecheck/test/fmt
    package-lock.json
    vite.config.ts             # react + tailwind v4 plugins; /api dev proxy; vitest (jsdom) block
    tsconfig.json / .app.json / .node.json
    eslint.config.js           # typescript-eslint strictTypeChecked + stylisticTypeChecked, react-hooks
    index.html
    src/
      main.tsx                 # QueryClientProvider + StrictMode; imports styles/tokens.css
      App.tsx                  # the single page
      vite-env.d.ts
      styles/tokens.css        # @import "tailwindcss" + @theme block, verbatim from DESIGN.md
      api/types.ts             # Project, Briefing, RegisterProjectInput, Health
      api/client.ts            # the ONLY module that calls fetch; ApiError
      api/client.test.ts       # vitest: URL/method/body/error-shape
      hooks/useProjects.ts     # useProjects / useBriefing / useRegisterProject (TanStack Query)
      components/              # PillButton, Card, ProjectList, RegisterForm, BriefingPanel (presentational)
      test/setup.ts
```

### How to run each piece

- **Install:** `just setup` (runs `uv sync` in `server/`, `npm install` in `web/`).
- **Full gate:** `just check` — ruff format-check + ruff lint + `mypy` (strict) + `pytest`
  (starts Postgres via testcontainers; Docker daemon required) + eslint + `tsc -b --noEmit`
  + vitest + `vite build`.
- **DB up / migrate:** `just up` (compose Postgres, waits healthy) then `just migrate`
  (`alembic upgrade head`). `just down` stops it (keeps the `pcs_pgdata` volume; add `-v` to wipe).
- **MCP over stdio:** `cd server && uv run pcs stdio` (co-located agents; no network — FR42).
- **MCP over streamable HTTP + /api:** `cd server && uv run pcs http` → binds `127.0.0.1:8080`
  (`/mcp` for MCP, `/api/*` for the frontend).
- **Frontend dev:** `cd web && npm run dev` (proxies `/api` → `http://127.0.0.1:8080`;
  override with `VITE_API_TARGET`). **Prod build:** `npm run build` → `web/dist/`.
- **Tests alone:** `just test`. **Server tests alone:** `cd server && uv run pytest`.

### Naming / structure decisions

- Package name **`pcs`** (kept from ROADMAP working name). HTTP port default **8080**, env prefix **`PCS_`**.
- A **component's logic lives in its own module** (`pcs.context.service`) as plain async
  functions over `AsyncSession` — no MCP/HTTP imports — and is unit-tested there. `pcs.mcp`
  and `pcs.web_api` are both thin shells over that same service so agents and the frontend
  can never diverge. T01+ should keep this split.
- `session_scope()` is the unit of work everywhere (commits on success, rolls back on error).
  Engine/sessionmaker are lazy singletons; `reset_engine()` exists for tests.
- Structured logging: one JSON line per event on **stderr** (stdout is the stdio MCP channel).
  `log_tool_call(tool=, project=, caller=, outcome=)` is the mandatory per-call audit record (NFR6).
  `caller` is best-effort MCP client name, else `"unknown"`; HTTP callers can send `X-PCS-Caller`.
- Migrations: single baseline `0001_baseline`. `context_entries` is intentionally the flat
  T00 shape (`id, project_id, section, headline, detail, status, author, created_at, updated_at`).
- `ContextEntry.section` values used in T00: `"overview"`, `"focus"`. `status`: `"open"` / `"resolved"`.
- `set_current_focus` **replaces** (resolves prior open focus rows, inserts a new one) rather
  than appending — simplest thing that makes the briefing show something.
- Briefing format is literal Markdown-ish text: `# <name> — project briefing` / `## Overview` /
  `## Current focus`. Hard cap via `cap_to_tokens` at ~4 chars/token, 1500 tokens (D13/FR9g).

### Seams left for later tasks

- **T01 (context store):** owns the real schema — replace `context_entries` with the full
  entry model (headline/detail rules FR3b, priority, resolved state, per-section handling),
  the **audit-log revisions** table (FR11), expiry policy (FR3a), concurrency (FR17/18).
  Replace `service.get_project_briefing` with the deterministic §7.2a assembly + per-project
  budgets; `cap_to_tokens` / `BRIEFING_TOKEN_CAP` / `HEADLINE_MAX_CHARS` are the placeholder
  hooks. Add the remaining read/write MCP tools + `context://` resources in `pcs.mcp` and the
  matching thin `/api` routes if the frontend needs them.
- **T02 (requirements file):** new module `pcs.requirements`; `register_project` currently does
  NOT create `.project-context/requirements.md` (FR16a) — add that there.
- **T03/T04 (index):** new schemas/modules `pcs.index`; keep them in separate tables so they
  are drop-and-rebuild safe (NFR12). Nothing in T00 touches them.
- **T05:** `pcs.codemap`. **T06/T07:** the frontend — copy the `styles/tokens.css` + typed
  client + TanStack-Query-hook pattern; do not introduce `fetch` in components.
- **T08 (deploy):** `Settings.bind_host` raises `NotImplementedError` for `bind_mode="tailscale"`
  — that branch is the seam. Add the server + tailscale services to `deploy/docker-compose.yml`
  and a `server/Dockerfile`.

### Deviations / decisions to confirm

1. **`mcp` pinned to `>=1.13,<2`.** The installed latest is `mcp` 2.x, which renamed
   `FastMCP` → `MCPServer` and changed transport APIs. The whole task contract and ROADMAP
   say "FastMCP", and T01–T09 are written against it, so I stayed on the 1.x line
   (`mcp==1.30.0` resolved). Revisit as a deliberate, separate migration if desired.
2. **Two extra HTTP routes beyond the two named in the task.** The task lists only
   `GET /api/health` and `GET /api/projects`, but the acceptance checklist requires the
   frontend to *register a project and show its briefing*. Rather than embed an MCP JSON-RPC
   client in the browser (way over-scope for T00), I added `POST /api/projects` and
   `GET /api/projects/{project}/briefing` as thin shells over the identical service functions
   the MCP tools use. If you'd rather the frontend drive MCP directly, that's a T06 decision.
3. **Build backend `uv_build`, not hatchling.** ROADMAP says "uv" without naming a build
   backend; hatchling's editable install did not put `src/` on `sys.path` under this uv, so
   I used uv's own `uv_build` backend (native src-layout support). No functional impact.
4. **testcontainers extra is `[postgres]`** (task file wrote `[postgresql]`); modern
   `testcontainers` 4.x uses `testcontainers.community.postgres` — that's what the tests import.
5. **`accept` is a pure echo stub** (`just accept TXX` prints a line) — real acceptance
   wiring is T09 per the task ("no-op stub for now").
6. Two **deprecation warnings** surface in `pytest` (Starlette's TestClient suggests `httpx2`;
   an anyio alias). They are warnings only — the suite is green and no `filterwarnings`
   suppression was added.

### New dependencies (and why)

**server/pyproject.toml — runtime**
| Package | Why |
|---|---|
| `mcp>=1.13,<2` | MCP SDK / FastMCP — the server (ROADMAP stack); pinned <2 (deviation 1) |
| `sqlalchemy[asyncio]>=2.0.36` | async ORM (ROADMAP) |
| `psycopg[binary]>=3.2.3` | Postgres driver v3 for `postgresql+psycopg://` (ROADMAP) |
| `alembic>=1.14.0` | migrations (ROADMAP) |
| `pydantic-settings>=2.6.1` | `pcs.config` (AGENTS.md) |
| `uvicorn>=0.34.0` | ASGI server for the streamable-HTTP transport |
| `starlette>=0.46.0` | explicit — `/api` route + response types (already transitive via mcp) |

**server — dev**
| Package | Why |
|---|---|
| `pytest`, `pytest-asyncio` | tests (ROADMAP) |
| `testcontainers[postgres]>=4.9.0` | real Postgres for the integration test (ROADMAP) |
| `ruff`, `mypy` | format/lint/type gate (ROADMAP/AGENTS.md) |

**web/package.json — runtime:** `react`, `react-dom`, `@tanstack/react-query` (ROADMAP).
**web — dev:** `vite`, `@vitejs/plugin-react`, `typescript`, `typescript-eslint`, `@eslint/js`,
`eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`,
`tailwindcss` + `@tailwindcss/vite` (v4), `vitest` + `jsdom`, `@types/{react,react-dom,node}` —
all standard for the ROADMAP frontend stack.

### Notes that may affect T01–T09 scoping

- The service-layer / thin-transport split works well; T01 should resist putting SQL in
  `pcs.mcp`. Every tool = `_caller(ctx)` + `session_scope()` + one service call + `log_tool_call`.
- FastMCP tools take `ctx: Context | None = None` so `mcp.call_tool()` works in tests without a
  live request. Keep that pattern or tests get harder.
- `mcp.streamable_http_app()` returns a Starlette app and `FastMCP.custom_route` is how non-MCP
  routes attach — T06/T08 don't need a second web framework.
- testcontainers pulls `pgvector/pgvector:pg16` (~150 MB) on first `just check`/CI run; budget
  for it in CI timeouts.
- The frontend currently reaches the server only via `/api`. If T01 wants the browser to call
  new context tools, add `/api` shells (cheap) rather than MCP-in-browser.
