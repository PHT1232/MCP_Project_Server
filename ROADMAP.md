# Build Roadmap — Project Context MCP Server

Working name: **`pcs`** (provisional — the skeleton task may rename).

Source of truth for *what* to build: [REQUIREMENTS.md](REQUIREMENTS.md) (v0.6) and
[DESIGN.md](DESIGN.md) (frontend style, normative).
Source of truth for *how agents work*: [AGENTS.md](AGENTS.md).
Review process: [REVIEW.md](REVIEW.md).

---

## Stack (decided)

| Layer | Choice |
|-------|--------|
| Server | **Python 3.12+**, official **MCP SDK** (`mcp`, FastMCP) — stdio + streamable HTTP |
| Package/deps | **uv** |
| DB | **PostgreSQL 16 + `pgvector`**; **SQLAlchemy 2.0** (async) + **Alembic** migrations; `psycopg` 3 driver |
| Code parsing | **tree-sitter** (`tree-sitter` + `tree-sitter-language-pack`) |
| Symbols/xrefs | per-language **SCIP** indexers invoked as subprocesses (D14), normalized to one model in PG |
| Lint/format/type/test | **ruff** (format + lint), **mypy** (strict), **pytest** (+ `pytest-asyncio`, `testcontainers` for PG) |
| Frontend | **React + Vite + TypeScript**, **TanStack Query**, **Tailwind v4** wired to `DESIGN.md`'s `@theme` block |
| Code-map graph | **Sigma.js / graphology** (handles large graphs; server sends only the visible subgraph) |
| Frontend checks | **eslint**, **tsc --noEmit**, **vitest**, `vite build` |
| Packaging | **Docker Compose** (server + Postgres + Tailscale sidecar) |
| Task runner | **just** (`justfile` at repo root: `just check`, `just test`, `just up`, …) |

Rationale and residual sub-questions live in REQUIREMENTS.md §1a / §11.

---

## Repo layout (target)

```
/
  REQUIREMENTS.md  DESIGN.md  ROADMAP.md  AGENTS.md  REVIEW.md
  justfile
  .github/workflows/ci.yml
  tasks/            # one file per task — scope, DoD, acceptance checklist
  reviews/          # one file per task — my review findings
  scripts/          # review.sh and other helpers
  server/
    pyproject.toml
    src/pcs/
      __init__.py
      config.py
      db/            # models, session, migrations wiring
      alembic/
      context/       # §7.1–7.5, 7.2a  (T01)
      requirements/  # §7 FR16a         (T02)
      index/         # §7.6             (T03, T04)
      codemap/       # §7 FR32/FR32a    (T05)
      mcp/           # tool + resource registration, transports
      web_api/       # extra HTTP endpoints the frontend needs (non-MCP)
    tests/
  web/               # React frontend  (T06, T07)
    package.json
    src/
  deploy/            # Dockerfiles, compose, tailscale  (T08)
```

---

## Phases & tasks

### Phase 0 — Walking skeleton  *(1 agent, blocks everything)*

| Task | Scope |
|------|-------|
| [T00](tasks/T00-skeleton.md) | Monorepo scaffold, `uv` + `just check` + CI, Postgres via compose, Alembic baseline, **one vertical slice** end to end: `register_project` + a minimal `get_project_briefing` (overview + focus only) over stdio **and** HTTP, one integration test, Vite frontend scaffold with the `DESIGN.md` token system and a single page that calls the HTTP endpoint. Establishes all conventions. |

**Gate:** I review T00 and merge to `main` before Phase 1 starts. Phase 1 task
files get fleshed out against the real skeleton structure at that point.

### Phase 1 — Components  *(parallel, after T00 merged)*

| Task | Scope | Depends on |
|------|-------|-----------|
| [T01](tasks/T01-context-store.md) | Context store: full entry model (`headline`/`detail`, metadata, priority), all sections, **audit log** (FR11), all read/write MCP tools, §7.2a deterministic assembly + budgets (FR9a–FR9g), `get_section`/`get_entry`/`get_entry_history`, expiry policy (FR3a), concurrency (FR17/18) | T00 |
| [T02](tasks/T02-requirements-file.md) | Requirements template file (FR16a): parser, `R-NNN` IDs, `sync_requirements`, 3-way merge, atomic writes, error surfacing | T01 |
| [T03](tasks/T03-index-keyword.md) | Code index — ingestion + keyword/structural search: repo walk + `.gitignore`, tree-sitter chunking, PG FTS + trigram, incremental (watch + git-diff), `get_index_status`, `reindex`, scoping (FR19–21, 23, 23a, 24–27, 29) | T00 |
| [T04](tasks/T04-index-semantic.md) | Code index — symbols + semantic: SCIP indexers (FR23c), symbol/xref model, embedding-backend interface + `pgvector`, hybrid ranking, `search_code`, `retrieve_context`, `prepare_task` (FR22, FR22a) | T03, T01 |
| [T05](tasks/T05-codemap-api.md) | Code-map API: dependency graph from T04 symbols, server-side aggregation `get_code_map` (scope/depth) (FR32, FR32a, FR39), context-overlay data (FR33) | T03, T04 |
| [T06](tasks/T06-frontend-shell.md) | Frontend shell + context dashboard: `DESIGN.md` system (FR39a), project picker, briefing dashboard, requirements view, index-status panel, manual refresh (FR30, 31, 36, 36a, 37, 38) | T01, T02 |
| [T07](tasks/T07-frontend-codemap.md) | Frontend code map + search: interactive aggregated graph, node inspector, search panel, overlays (FR32–35) | T05, T06 |
| [T08](tasks/T08-deploy.md) | Deployment: Dockerfiles, compose, Tailscale sidecar, env config, bind modes, run docs (FR40–42, NFR3, NFR14) | T00 (can develop early; finalizes last) |

### Phase 2 — Integration & hardening

| Task | Scope |
|------|-------|
| [T09](tasks/T09-integration.md) | End-to-end tests mapping every `AC1`–`AC27`, perf checks (NFR1/2/9/10), security pass (bind surface, SQL/path-traversal on mounted repos), `docs/` + README polish |

---

## Status

| Task | Branch | State |
|------|--------|-------|
| T00 | `task/T00-skeleton` | **merged** (`371d4c7`) — [reviews/T00.md](reviews/T00.md) |
| T01 | `task/T01-context-store` | **merged** (`dc9921a`) — [reviews/T01.md](reviews/T01.md) |
| T03 | `task/T03-index-keyword` | **merged** (`2c1a99f`) — [reviews/T03.md](reviews/T03.md) |
| T02, T06 | — | ready (depend on T01) |
| T04 | — | ready (depends on T01 + T03, both merged) |
| T08 | `task/T08-deploy` | **changes requested** (`5be855a`) — [reviews/T08.md](reviews/T08.md): B1 container unreachable |
| T05, T07 | — | blocked (T04 / T05+T06) |
| T09 | — | blocked on Phase 1 |

Update this table as tasks move: `not started → in progress → in review → changes requested → merged`.
