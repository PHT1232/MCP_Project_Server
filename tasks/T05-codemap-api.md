# T05 — Code-map API

**Branch:** `task/T05-codemap-api`  ·  **Depends on:** T03 + T04 (merged)  ·  **Blocks:** T07

**Read first:** `AGENTS.md`; `REQUIREMENTS.md` §7 FR32/FR32a/FR33/FR39 + D9/D11 +
AC11/AC12/AC20; `reviews/T04.md` "Notes for dependents → T05" and
`tasks/T04-index-semantic.md` Handoff ("The symbol model (T05 consumes this)");
`reviews/T03.md`; `reviews/T01.md` (context sections for the overlay). Base off
current `main`.

**T04 gives you `code_index.symbol_edges`:**
`src_path` (repo-relative importing file, always set) · `dst_module` (raw import
string, always set) · `dst_path` (resolved repo-relative target file, or `''`
when external/unresolved) · `kind` (`import` today; `call`/`inherits` reserved) ·
`language` · `mode` (`scip`/`fallback`). Unique on
`(project_id, src_path, dst_path, dst_module, kind)`. Resolved file→file edges:
`WHERE project_id=:p AND dst_path <> ''`. Also: `code_index.symbols` /
`symbol_refs` (zoom-in node detail), `code_index.files` (path, language,
size_bytes, skipped), `code_index.chunks` (LOC per file via line ranges).
`get_index_status().as_dict()` carries `symbol_modes`, `symbol_count`, etc.

**Context overlay (FR33):** join file paths against T01 context entries that
carry `linked_files` (blockers/bugs/requirements) and the current `focus`
entry's referenced paths (see T03 `search.py._extract_focus_paths` for the
heuristic). Sections: `blockers`, `bugs`, `requirements`, `focus`.

**Out of scope:** the frontend graph rendering — all T07. You ship the data API
(`get_code_map` MCP tool + `context://{project}/code-map` resource + HTTP route),
built with server-side level-of-detail so the client never holds the whole graph
(D9/FR32a).

## Goal
Server-side dependency/structure graph with level-of-detail aggregation, plus the
context-overlay data the frontend needs.

## In scope
- Build the graph from T04 symbols/edges: nodes = modules/packages/dirs → files →
  key symbols; edges = import/call dependencies; node metrics = LOC, fan-in/out
  (static only, no churn — FR32, FR39, D11).
- `get_code_map(project, scope?, depth?)` — returns top-level nodes + aggregated
  edges by default; children/finer edges on demand; response never re-sends the
  whole graph (FR32a, D9).
- Resource `context://{project}/code-map`.
- Overlay data: which nodes carry an open focus/blocker/bug, and which carry a
  requirement's linked files (FR33, FR36a link).
- Regenerate as part of the index update path (FR39).

## Key requirements
FR32, FR32a, FR33, FR39, D9, D11. ACs: AC11, AC12, AC20.

## Acceptance checklist
- [x] Default `get_code_map` returns only top-level nodes + aggregated edges; expand fetches children without resending (AC20)
      — `test_ac20_default_is_top_tier_only_and_expansion_is_scoped`
- [x] Top-level nodes match the real module structure with dependency edges (AC11)
      — `test_ac11_top_level_nodes_and_edges_match_module_structure`, `test_ac11_expanding_scope_returns_only_that_subtree`
- [x] Overlay marks nodes with an open blocker/bug tied to a file (AC12)
      — `test_ac12_blocker_and_bug_flag_the_owning_nodes`, `test_overlay_picks_up_current_focus_paths`
- [x] Scales on a large repo (server aggregation, not client)
      — `test_ac20_*` builds a 240-file wide/deep repo; default response stays ~13 nodes / <20 KB JSON
- [x] Tests per AC; `just check` green
- [x] Handoff written

## Handoff

### Module layout (new under `server/src/pcs/`)

```
codemap/
  __init__.py            +  re-exports get_code_map
  service.py             +  get_code_map() — LOD aggregation, edges, overlay; NO MCP/HTTP imports
mcp/codemap_tools.py     +  register_codemap_tools() — get_code_map tool + context://{project}/code-map resource
web_api/codemap_routes.py +  register_codemap_routes() — GET /api/projects/{p}/code-map?scope=&depth=&external=
mcp/server.py            *  wires the three register_* calls (after the index ones)
tests/test_codemap.py    +  AC11 / AC12 / AC20 + scales + surface (11 tests)
tests/test_integration.py *  EXPECTED_TOOLS += "get_code_map" (necessary consequence of the new tool)
```
`*` changed, `+` new. **No migration, no config, no `.env.example` change** — see Decisions.

### Run commands
- Gate: `just check` (repo root) — green (ruff, mypy --strict **66 files**, pytest **97 passed / 1 skipped**, eslint/tsc/vitest, compose-lint, `vite build`).
- `just migrate` from empty → `0001…0005` unchanged; `alembic heads` singular (`0005_index_semantic`). T05 adds no revision.

### The `get_code_map` response shape (T07 consumes this)

`get_code_map(project, scope?, depth=1, include_external=false)`

**Directory / top-tier response** (`scope` omitted, or a subtree path):
```jsonc
{
  "project": "<uuid>",
  "project_name": "acme-web",
  "scope": null,                       // or "services" — echoed, normalised
  "scope_kind": "directory",
  "depth": 1,                          // clamped to 1..3
  "generated_from": {                  // provenance / FR39
    "indexed": true,
    "last_full_at": "2026-09-10T…Z",
    "last_incremental_at": "2026-09-10T…Z",
    "last_commit": "abc123…" | null,
    "symbol_modes": { "python": "fallback" }
  },
  "nodes": [
    {
      "id": "dir:services",            // "dir:<path>" | "file:<path>" | "ext:<module>"
      "kind": "directory",             // "directory" | "file" | "external"
      "path": "services",              // repo-relative; "" only for a bare root file
      "label": "services",             // last path segment
      "language": "python" | null,     // dominant language of the files under the node
      "loc": 128,                      // Σ MAX(end_line) of each file's chunks (D11 static)
      "size_bytes": 4213,
      "file_count": 5,
      "symbol_count": 7,
      "fan_in": 1,                     // distinct in-scope+boundary nodes importing into this node
      "fan_out": 2,                    // distinct nodes this node imports
      "has_children": true,            // dir → always; file → symbol_count > 0
      "outside_scope": false,          // true = a boundary node pulled in only to anchor a crossing edge
      "overlay": { "focus": 0, "blockers": 1, "bugs": 0, "requirements": 0, "hot": true }
    }
  ],
  "edges": [
    { "source": "file:main.py", "target": "dir:services", "kind": "import", "weight": 1 }
    // kind is "import" today ("call"/"inherits" reserved by T04's scip mode); weight = # of
    // underlying file→file edges aggregated into this tier edge; self-loops dropped
  ],
  "stats": {
    "total_files": 240,               // whole project (context for "this is a slice")
    "total_resolved_edges": 611,
    "node_count": 13,
    "edge_count": 12,
    "truncated": false
  },
  "overlay_legend": ["focus", "blockers", "bugs", "requirements"]
}
```

**File / symbol response** (`scope` is an indexed file path) — the node-inspector zoom (FR34 data):
```jsonc
{
  "scope": "services/billing/invoice.py",
  "scope_kind": "file",
  "depth": 0,
  "nodes": [
    { "id": "sym:services/billing/invoice.py#make_invoice:4", "kind": "symbol",
      "path": "services/billing/invoice.py", "label": "make_invoice", "symbol_kind": "function",
      "language": "python", "start_line": 4, "end_line": 5, "loc": 2, "signature": "def make_invoice(order):",
      "has_children": false, "outside_scope": false, "overlay": { … } }
  ],
  "edges": [],
  "dependencies": ["lib/money.py", "services/pricing/__init__.py"],   // resolved dst_path, else raw module
  "dependents": ["services/api/routes.py"],                          // files that import this file
  "stats": { "node_count": 1, "edge_count": 0, "truncated": false },
  "overlay_legend": [ … ]
}
```

### LOD / scope / depth contract (D9 / FR32a / AC20)
- **Default** (`scope=None`): the repo's **top directory tier** — every indexed file is folded to
  its first path segment (a `dir:` node) unless it *is* a root-level file (a `file:` node). Edges
  are aggregated between those top nodes; intra-tier edges become self-loops and are dropped.
- **Expand**: pass `scope="<subtree>"` (+ optional `depth`). The service loads **only rows under
  that prefix** (`path LIKE 'subtree/%'`), folds them to `len(scope_segments)+depth` segments, and
  emits edges among them. Edges that cross the scope boundary collapse their far endpoint to a
  **sibling** node of `scope` and mark it `outside_scope:true` so T07 can render it as a stub /
  navigation affordance without fetching it. The response never contains nodes from other subtrees.
- **`depth`** is clamped to `1..3` (`codemap_service.MAX_DEPTH`). Default 1.
- **File scope**: if `scope` exactly matches an indexed file, you get the symbol/inspector response
  instead (symbols as nodes + `dependencies`/`dependents`).
- `include_external=true` adds `ext:<module>` nodes for unresolved imports (`react`, `fmt`, …),
  aggregated per module. Off by default to keep the default payload tight.

### Overlay shape (FR33)
`node.overlay = { focus, blockers, bugs, requirements, hot }`. Each section count = number of
**open** context entries in that section whose referenced paths land on the node's subtree
(exact match, inside the node, or an ancestor dir of it). Referenced paths are `entry.linked_files`
for blockers/bugs/requirements and `search._extract_focus_paths(headline+detail)` for the current
focus (same heuristic as `search_code(scope='focus')`). `hot = blockers + bugs > 0` — T07's hot-spot flag (AC12). `overlay_legend` gives the section order.

### How invalidation / regeneration works (FR39)
The map is a **stateless projection** — it is computed on every call from
`code_index.{files,chunks,symbols,symbol_edges}` + the T01 context entries, and nothing is
materialised. `reindex` (FR24/FR27) already rebuilds those index tables, so the next
`get_code_map` reflects the new structure with zero extra work; there is no cache to invalidate
and no separate diagramming step. `generated_from` echoes the index status so T07 can show
"map as of commit …".

### Decisions
1. **No persisted graph table / no migration.** The brief allowed either a cached `code_index`
   graph table or on-demand SQL aggregation. On-demand wins here: the graph is 100 % derivable,
   a cache adds an invalidation surface, and at NFR1 scale the aggregation is sub-10 ms. The
   default call does read every file row for the project to fold the top tier (O(files), one
   indexed query, tiny rows); a subtree call reads only its prefix. If a real deployment ever
   dwarfs NFR1, the fold can move into a SQL `GROUP BY` on `split_part(path,'/',…)` without
   changing the response contract. **Confirm you're happy with on-demand vs. a cache table.**
2. **LOC = `MAX(end_line)` of a file's chunks**, summed for directory nodes. `chunks` line ranges
   overlap (class + methods), so a straight `Σ(end-start)` would over-count; the last covered line
   is a good file-length proxy and needs no extra columns. `size_bytes` is also returned for T07
   to pick whichever drives node weight (FR32).
3. **Boundary nodes.** A subtree call surfaces `outside_scope:true` stub nodes purely to anchor
   edges that leave the scope. They carry no metrics. T07 should render them as "click to
   navigate", not as real nodes in the layout.
4. **`get_code_map` tool `project` is optional (`str | None`)** to match every other tool in
   `pcs.mcp` (they all default it and raise the D3 "unknown project" error from the service).

### Deviations
- `tests/test_integration.py::EXPECTED_TOOLS` gained `"get_code_map"` — a necessary consequence of
  registering the tool, not scope creep (same pattern T04 used for its two tools).
- HTTP route behaviour is covered via the service + MCP-tool tests + a route-registration
  assertion (mirrors `test_index.py::test_http_index_routes_are_registered`). A second
  `TestClient(build_http_app())` is avoided on purpose — `StreamableHTTPSessionManager.run()` is
  one-shot per process and `test_integration.py` already owns it (documented in `test_deploy.py`).

### New dependencies
None. Uses only stdlib (`collections.Counter`), SQLAlchemy, and existing `pcs.*` modules.

### New settings
None. `MAX_DEPTH` / `DEFAULT_DEPTH` are module constants in `pcs.codemap.service`; no env knobs
were warranted. Nothing to add to `.env.example` or `pcs.config`.
