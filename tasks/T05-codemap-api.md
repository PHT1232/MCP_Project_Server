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
- [ ] Default `get_code_map` returns only top-level nodes + aggregated edges; expand fetches children without resending (AC20)
- [ ] Top-level nodes match the real module structure with dependency edges (AC11)
- [ ] Overlay marks nodes with an open blocker/bug tied to a file (AC12)
- [ ] Scales on a large repo (server aggregation, not client)
- [ ] Tests per AC; `just check` green
- [ ] Handoff written

## Handoff
_(fill in)_
