# T03 — Code index: ingestion + keyword/structural search

**Branch:** `task/T03-index-keyword`  ·  **Depends on:** T00  ·  **Blocks:** T04, T05

## Goal
Index a project's repo and serve keyword/structural search over it, with
incremental updates. No embeddings, no SCIP yet.

## In scope
- Repo walk honoring `.gitignore` + configurable ignore/allow list; secrets,
  vendored deps, build output excluded by default (FR19).
- tree-sitter chunking on function/class/module boundaries for the 7 families,
  plain-text fallback otherwise (FR23, FR23a).
- Storage in PostgreSQL: chunk table with FTS (`tsvector`) + trigram
  (`pg_trgm`) indexes; each chunk records file path, line range, git blob/commit
  (FR21, FR25).
- Keyword/structural search: exact + fuzzy text, symbol names, file globs;
  results carry path, line range, snippet, score, matched mode (FR20 keyword,
  FR21).
- Incremental: full pass on first registration; thereafter changed files only,
  via file watch + git revision diff (FR24). Stale results flagged (FR25, NFR9).
- `get_index_status` (FR26), `reindex` full/incremental (FR27), search scoping
  (FR29).

## Out of scope
- Symbols/xrefs and dependency edges (T04 — SCIP).
- Embeddings / semantic (T04).
- `search_code` hybrid ranking + `retrieve_context` + `prepare_task` (T04) —
  T03 exposes an internal keyword-search API T04 builds on, plus a thin
  `search_code` that is keyword-only until T04 lands.

## Key requirements
FR19–FR21, FR23, FR23a, FR24–FR27, FR29, NFR5, NFR9, NFR12. ACs: AC9, AC15.

## Acceptance checklist
- [x] Indexes a sample repo respecting `.gitignore`; status reports counts + skipped-with-reason
- [x] Keyword query returns correct path + line range + snippet
- [x] Editing a file and re-querying within seconds reflects the change; stale results flagged (AC9)
- [x] Dropping index tables + restart → clean rebuild, curated context untouched (AC15)
- [x] Tests per AC; `just check` green
- [x] Handoff written

## Handoff

### Final module layout

```
server/
  pyproject.toml                 # +pathspec, tree-sitter, tree-sitter-language-pack, watchfiles
  src/pcs/
    config.py                    # PCS_INDEX_IGNORE/ALLOW/MAX_FILE_BYTES/WATCH
    alembic/env.py               # imports pcs.index.models so tables register
    alembic/versions/
      0003_code_index.py         # pg_trgm + schema code_index (NFR12, AC15)
    index/
      models.py                  # IndexFile, IndexChunk, IndexStatus
      schema.py                  # ensure_index_schema() after DROP SCHEMA (AC15)
      ignore.py                  # walk + gitignore + defaults + NFR5
      gitutil.py                 # HEAD, blob, changed paths
      chunker.py                 # tree-sitter FR23a + plaintext fallback
      search.py                  # keyword_search — T04 public API
      service.py                 # reindex, status, search_code, index_if_root_exists
      watch.py                   # HTTP-side incremental trigger (FR24)
    mcp/index_tools.py           # get_index_status, reindex, search_code
    web_api/index_routes.py      # GET index, POST reindex, GET search
  tests/
    test_index.py                # gitignore, keyword, AC9, AC15, scopes, MCP
.env.example                     # new PCS_INDEX_* vars
```

### How to run each piece

- **Install / gate:** `just setup && just check`.
- **Migrate:** `just up && just migrate` applies `0001` → `0002` → `0003`.
- **Index a project:** `register_project` with a real `root_path` does a full pass
  (missing roots no-op, so T01's `/repos/acme-web` tests stay green). Or call
  MCP `reindex` / `POST /api/projects/{project}/reindex`.
- **Search:** MCP `search_code` or `GET /api/projects/{project}/search?q=`.
- **Status:** MCP `get_index_status` or `GET /api/projects/{project}/index`.

### Naming / structure decisions

- Index lives in PostgreSQL schema **`code_index`** (files, chunks, status).
  `DROP SCHEMA code_index CASCADE` cannot touch curated context. `ensure_index_schema`
  recreates extension/schema/tables if they were dropped while Alembic still
  thinks `0003` is applied (AC15).
- Chunk `tsv` is a **generated stored tsvector** over `symbol || content`
  (`simple` config). Trigram GIN indexes on `content`, `symbol`, and `path`.
- Default ignores: `.git`, `node_modules`, `vendor`, `venv`, `.venv`, `dist`,
  `build`, `target`, `__pycache__`, `.env` / `.env.*`, `*.pem`/`*.key`, secrets,
  binaries (NUL / non-UTF-8), oversized files (`PCS_INDEX_MAX_FILE_BYTES`,
  default 1_000_000). Plus repo `.gitignore` and nested gitignores.
- tree-sitter language-pack keys: `python`, `javascript`, `typescript`, `tsx`,
  `java`, `go`, `rust`, `csharp` (not `c_sharp`), `c`, `cpp`.
- Stale (NFR9): at search time the working-tree SHA-256 is compared to the
  indexed `content_hash`. Hits against a changed file are returned with
  `stale=true`, never as current. Incremental reindex refreshes the chunk.
- Scopes (FR29): `project` | `subtree` | `files` | `focus`. Focus parses open
  focus headline/detail for path-like tokens. Path traversal outside the
  project root is rejected (NFR5).
- Auto-index on MCP/HTTP `register_project` only if the root directory exists.
- File watch runs on the HTTP app lifespan (`PCS_INDEX_WATCH`, default true).
  Tests set it false and call `reindex(incremental=True)` directly.

### MCP tools added (35 total)

- `get_index_status` (FR26)
- `reindex` (`incremental` default true; first pass is always full) (FR27)
- `search_code` — keyword only; `semantic_available: false` + note (FR20, FR28/AC10 seed)

### HTTP surface (T06)

- `GET /api/projects/{project}/index`
- `POST /api/projects/{project}/reindex` body `{ "incremental": true }`
- `GET /api/projects/{project}/search?q=&scope=&subtree=&files=&globs=&limit=`

Registered in `web_api/index_routes.py`, not stuffed into T01 `_ROUTES`.

### Seams left for later tasks

- **T04:** wrap `pcs.index.search.keyword_search` (returns `SearchResult` /
  `SearchHit`). Do not duplicate the FTS/trigram SQL. Hybrid ranking, SCIP
  symbols/xrefs, embeddings, `retrieve_context`, `prepare_task` are T04.
  `search_code` already reports `semantic_available: false`.
- **T05:** code-map nodes can reuse `code_index.files` paths/languages; edges
  wait on T04 SCIP.
- **T06:** typed client for the three index HTTP routes; index-status panel
  (FR37). Single `TestClient` per process against singleton `mcp`.
- **T01 tests:** `register_project` with a missing root must keep no-op'ing
  auto-index.

### Deviations / decisions to confirm

1. **Keyword `search_code` is shipped now** (thin, keyword-only) so agents can
   search before T04. T04 should extend it, not replace the tool name.
2. **C# language-pack name is `csharp`**, not `c_sharp`.
3. **Watch is HTTP-lifespan only.** Stdio-only MCP still full-indexes on
   register (if the root exists) and supports manual `reindex`; git-diff +
   content-hash incremental does not need the watcher.
4. **Skipped ignored directories are recorded once** (e.g. `node_modules`),
   not every file inside them.
5. **T01 `mcp/tools.py` + `web_api/routes.py`** gained an `index_if_root_exists`
   + `ensure_watch` hook after `register_project` (FR24). No context-store
   schema change.

### New dependencies

| Package | Why |
|---------|-----|
| `pathspec` | `.gitignore` + extra ignore/allow gitignore patterns (FR19) |
| `tree-sitter` | Parser runtime (FR23) |
| `tree-sitter-language-pack` `>=0.7,<0.8` | Bundled grammars for the 7 families; 0.7.x ships in the wheel (CI/offline) |
| `watchfiles` | HTTP-side file watch → incremental reindex (FR24) |

mypy `ignore_missing_imports` for `pathspec`, `tree_sitter_language_pack`,
`watchfiles` (same class of override as `testcontainers.*`).

### Notes that may affect T04/T05/T06 scoping

- Public keyword API: `from pcs.index import keyword_search`.
- `IndexChunk` does not map the generated `tsv` column; search uses SQL.
- `ensure_index_schema` is idempotent and is called from reindex/status/search.
- Do not add a second Starlette `TestClient` in this process (session manager
  is one-shot). T03 HTTP coverage piggybacks on T01's existing client plus
  route-registration assertions.
