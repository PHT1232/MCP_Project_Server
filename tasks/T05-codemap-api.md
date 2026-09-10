# T05 — Code-map API

**Branch:** `task/T05-codemap-api`  ·  **Depends on:** T03, T04  ·  **Blocks:** T07

> Stub — flesh out after T03/T04.

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
