# T07 — Frontend code map + search

**Branch:** `task/T07-frontend-codemap`  ·  **Depends on:** T05, T06

> Stub — flesh out after T05/T06.

## Goal
The interactive code map view and the search experience, on top of the T06 shell.

## In scope
- Interactive graph (Sigma.js / graphology) driven by `get_code_map`: pan/zoom,
  collapse by hierarchy, filter by path/language; expand a node → fetch its
  children (never the whole graph) (FR32, FR32a).
- Node visual weight = size + fan-in/out (static only) (FR32, D11).
- Context overlay: focus/blocker/bug hot spots marked on nodes; requirement-linked
  files indicated (FR33, FR36a).
- Node inspector: path, language, size, deps/dependents, related context entries,
  read-only syntax-highlighted source — no git activity (FR34, D11).
- Search panel using `search_code`; results select + locate the node on the map
  (FR35).
- All in the `DESIGN.md` language, reusing T06 components.

## Key requirements
FR32–FR35, FR39a, NFR13, NFR15, D9, D11, D17. ACs: AC11, AC12, AC13.

## Acceptance checklist
- [ ] Map renders top-level nodes matching real module structure; expand loads children lazily (AC11, AC20 client side)
- [ ] Open blocker/bug on a file marked on its node (AC12)
- [ ] Node select → inspector with source, deps/dependents, related context (AC13)
- [ ] Search result locates + highlights the node
- [ ] Stays responsive on a large graph
- [ ] Design tokens only (AC27); frontend checks green
- [ ] Handoff written

## Handoff
_(fill in)_
