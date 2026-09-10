# T07 — Frontend code map + search

**Branch:** `task/T07-frontend-codemap`  ·  **Depends on:** T05 + T06 (merged)

**Read first:** `AGENTS.md` (frontend conventions — tokens only, no `fetch` in
components, typed client, strict TS); `DESIGN.md` (normative — its Do's/Don'ts,
AC27); `REQUIREMENTS.md` FR32–FR35, FR39a, NFR13, NFR15, D9/D11/D17,
AC11/AC12/AC13/AC20; `reviews/T05.md` ("Response shape for T07" + "Notes for T07")
and `tasks/T05-codemap-api.md` Handoff (full `get_code_map` JSON contract);
`reviews/T06.md` ("Seams for T07") and `tasks/T06-frontend-shell.md` Handoff.
Base off current `main`.

**T06 gives you (`web/src/`):** the design-system components (`Card`, `PillButton`,
`PillNav`, `StatusBadge`, `Typography`, `Callout`, `EntryCard`, `fields`), the
hand-rolled router (`useNavigate` / `<Link>` from `web/src/router/`), `api/client.ts`
(only `fetch` caller — extend it), `api/queryKeys.ts`, per-resource hooks, and
**`web/src/views/CodeMapView.tsx` — a stub at route `/projects/:p/code-map`,
already in the nav.** Fill it.

**T05 gives you** `GET /api/projects/{p}/code-map?scope=&depth=&external=`:
- No `scope` → top directory tier (`dir:`/`file:` nodes) + aggregated `edges`
  (`{source,target,kind,weight}`). `node.has_children`, `node.overlay`
  (`{focus,blockers,bugs,requirements,hot}`), `node.fan_in/fan_out`, `node.loc`,
  `node.size_bytes`, `node.language`, `node.outside_scope`.
- `scope=<dir path>` (+ `depth` 1..3) → that subtree only (never the whole graph).
- `scope=<file path>` → `scope_kind:"file"`, `nodes` are `kind:"symbol"` with
  `signature`/`start_line`/`end_line`, plus `dependencies[]` / `dependents[]` —
  the **node inspector** data (FR34).
- `generated_from` (index status) → show "not indexed" empty state when
  `indexed:false`.
Also `GET /api/projects/{p}/search?q=&scope=&subtree=&files=&globs=&limit=` (T03/T04)
for the search panel — hits carry `path`, `start_line`/`end_line`, `snippet`,
`score`, `matched_mode`, `symbol`, `stale`.

**Graph lib:** Sigma.js / graphology per ROADMAP (CDN not allowed — it's an npm
dep, bundled by Vite; that's fine, it's a runtime dep — declare it and note why).

**One permitted server addition:** FR34 / AC13 require the inspector to show the
file's **read-only source**. There is no source route yet. Add exactly one thin
route — `GET /api/projects/{p}/source?path=` — that returns a file's text
(reassemble from `code_index.chunks.content` ordered by `start_line`, or read the
file under the project `root_path` with the same `resolve_under_root` traversal
guard T03 uses). Path-traversal safe, bound params, `log_tool_call`. Nothing else
on the server changes.

**Out of scope:** all other server changes. Syntax highlighting = a small
bundled highlighter (e.g. `shiki`/`highlight.js`) or a minimal token pass — your
call, keep the bundle reasonable (NFR13).

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
- [x] Map renders top-level nodes matching real module structure; expand loads children lazily (AC11, AC20 client side)
      — `CodeMapView` + `lib/codemap.mergeCodeMap`; `codemap.test.ts` "merges ONLY the expanded subtree"; live: pcs-self repo → 16 top nodes, `?scope=codemap` returns just its 3 children + 1 boundary stub
- [x] Open blocker/bug on a file marked on its node (AC12)
      — `overlayTone` (ember for `overlay.hot`), `CodeGraph.fillFor`, `CodeMapLegend`, inspector badges; `codemap.test.ts` "overlayTone"
- [x] Node select → inspector with source, deps/dependents, related context (AC13)
      — `NodeInspector` + `useFileScope` + `useSource` + `lib/codemap.relatedEntries`; new `GET /api/projects/{p}/source`; live-verified
- [x] Search result locates + highlights the node
      — `SearchPanel` → `onLocateHit` → `lib/codemap.locateHit` loop (expands scopes as needed); `codemap.test.ts` "locateHit"
- [x] Stays responsive on a large graph
      — server LOD (T05) + client only holds the visible subgraph; Sigma WebGL canvas; default payload stayed <20 KB in T05's 240-file test
- [x] Design tokens only (AC27); frontend checks green
      — grep: no hex/px in `web/src/components` or `web/src/views`; Sigma canvas colours read from `tokens.css` custom properties at runtime (`lib/tokens.ts`)
- [x] Handoff written

## Handoff

**Branch:** `task/T07-frontend-codemap` off `main` @ `a32cdca`. `just check` green
at repo root (server: ruff + mypy --strict **69 files** + pytest **102 passed / 1
skipped** on the real Postgres testcontainer; web: eslint clean, `tsc -b
--noEmit` clean, **47 vitest**, `vite build`; compose-lint). Ran live against the
compose Postgres with `uv run pcs http` serving the built bundle — registered a
project pointing at `server/src/pcs`, full-indexed it (61 files), opened the code
map (`/api/.../code-map`), expanded `codemap`, opened the file inspector
(`scope=codemap/service.py` → symbols + deps/dependents), fetched
`/api/.../source?path=codemap/source.py` (content + `truncated:false`), rejected
`../../../../etc/passwd` with 400, hit an unknown file with 404, and searched
`get_code_map` (5 hits). SPA deep-link `/projects/pcs-self/code-map` → 200 shell.

### View / component inventory (`web/src/`)
| File | Role |
|---|---|
| `views/CodeMapView.tsx` | The `/projects/:p/code-map` view — orchestrates graph + inspector + search, holds the merged `CodeGraph` and selection, drives lazy expansion and hit-location. Not-indexed empty state. |
| `components/CodeGraph.tsx` | Sigma/graphology canvas. Pan/zoom (Sigma default), node size = `nodeWeight` (D11 static), node colour = overlay tone / kind, edge thickness = `log2(weight)`, selection ring = Fey Signal (nav accent). `clickNode` → select, `doubleClickNode` → expand. Rebuilds the graphology graph in an effect; single Sigma instance. |
| `components/NodeInspector.tsx` | FR34/AC13 panel: label/kind/overlay badges, path, language, LOC, size, fan-in/out; for a file — dependencies/dependents (clickable → locate), symbol list, related context entries, `SourceView`. No git (D11). |
| `components/SourceView.tsx` | Read-only source, line-number gutter, tokens from `lib/highlight`. Calibre only (no monospace face — DESIGN.md "no second typeface"); one chromatic accent (Ember keywords). |
| `components/SearchPanel.tsx` | FR35 query box → `useCodeSearch`; hit rows (path, line range, `matched_mode`, `stale`, score, snippet); click → `onLocateHit`. |
| `components/CodeMapLegend.tsx` | FR33 legend from `overlay_legend` with StatusBadge tones. |
| `lib/codemap.ts` | **DOM-free model** (all unit-tested): `mergeCodeMap`, `overlayTone`, `nodeWeight`, `layout`, `locateHit`, `relatedEntries`, `graphLanguages`, `nodeMatchesFilter`. |
| `lib/tokens.ts` | `codeMapPalette()` — reads `--color-fey-*` from `tokens.css` at runtime for the Sigma canvas; `FALLBACK` mirrors `tokens.css` verbatim for jsdom only. |
| `lib/highlight.ts` | ~150-line stateful syntax scanner (keyword/string/comment/number). |
| `hooks/useCodeMap.ts` | `useCodeMap` (top tier), `fetchCodeMapScope` (imperative `queryClient.query`), `useFileScope`, `useSource`, `useCodeSearch`. |
| `api/client.ts` | `getCodeMap(project, scope?, depth?)`, `getSource(project, path)`, `searchCode(project, query, opts)`. |
| `api/types.ts` | `CodeMap*`, `SourceFile`, `SearchHit`, `SearchResponse`. |
| `api/queryKeys.ts` | `codeMap(project, scope)` (scope `null` → `"__root__"`), `source`, `search` — all match `isRefreshable` by `project`. |

### Graph transform contract (`lib/codemap.ts`)
- `CodeGraph = { nodes: Map<id, MergedNode>, edges: Map<edgeKey, CodeMapEdge>, loadedScopes: Set<string> }`.
- `mergeCodeMap(graph, map)` returns a **new** graph:
  - `map.scope === null` → graph is re-seeded from this tier (a manual refresh resets to the top tier; expansions are re-opened by the user).
  - `map.scope` a dir path → the aggregate `dir:<scope>` node and every edge incident to it are dropped; the response's nodes/edges are merged in; an incoming `outside_scope` stub never overwrites a real node already present; `loadedScopes += scope`.
  - `map.scope_kind === "file"` → returned unchanged (that payload feeds the inspector, not the graph).
  - `fan_in`/`fan_out` are **recomputed from the merged edge set** after every merge (consistent across tiers; == distinct graph neighbours, which is what T05 means per tier).
- `nodeWeight = 1 + √loc·0.6 + (fan_in+fan_out)·0.8` (D11 — static only). Renderer maps it to 4–26 px.
- `overlayTone`: ember if `hot || blockers || bugs`, else growth if `focus`, else mist if `requirements`, else null. Never Signal.
- `locateHit(graph, path)` → `{kind:"node"|"expand"|"unreachable"}`; the view loops expand→merge→retry (≤5) to reveal a search hit.

### The source route (server)
`GET /api/projects/{project}/source?path=` → `{path, language, content, truncated}`.
`pcs/codemap/source.py::get_source` + `pcs/web_api/source_routes.py`, registered in
`pcs/mcp/server.py` next to the other `web_api` modules. Guard order: `resolve_project`
(D3) → `resolve_project_root` + `resolve_under_root` (NFR5, rejects `..`/absolute/`~`
→ 400) → the path must be a **non-skipped** `code_index.files` row for the project
(else 404) → bytes read from disk, capped at 512 KiB (`truncated:true` past that).
Reads from disk (not reassembled from chunks) so the viewer sees the working tree;
`code_index.chunks` ranges overlap, so reassembly would double lines. `log_tool_call`
as `get_source`. Test: `server/tests/test_source.py` (content, traversal ×2, unknown
file 404, unknown project, route registration) — real Postgres.

### Decisions
1. **Sigma canvas colours read from `tokens.css` at runtime** (`getComputedStyle` on
   `:root`). Sigma renders to WebGL and cannot take Tailwind classes; the `FALLBACK`
   map in `lib/tokens.ts` is a verbatim copy of `tokens.css` used only where there is
   no computed style (jsdom). No colour literals in `components/` or `views/`.
2. **Minimal in-repo highlighter** instead of shiki/highlight.js — those dwarf the
   rest of the bundle (NFR13). It tags a common keyword set + strings/comments/numbers;
   not a full grammar, good enough for a read-only viewer.
3. **Manual refresh resets the map to the top tier.** Preserving every open expansion
   across a refresh would mean re-fetching each `loadedScope`; FR38 refresh semantics
   ("fresh data") make a reset acceptable. "Reset view" button does the same on demand.
4. **`fan_in`/`fan_out` recomputed client-side** from the merged edge set rather than
   trusting per-response numbers across a merge (they'd be inconsistent between a
   node seen as a tier aggregate and later as an expanded child).
5. **Source read from disk**, not reassembled from `code_index.chunks` (overlapping
   ranges). Trade-off: the inspector can show content newer than the last index; the
   search panel already surfaces a `stale` flag for that situation.
6. **Node overlay = colour shift** (+ inspector badges + legend), not a separate ring
   — Sigma v3's default node program has no border. Documented; a ring program is a
   later polish.

### Deviations
- `web/src/api/client.test.ts` gained 4 cases; `queryKeys.ts` / `types.ts` extended —
  all within "extend `api/client.ts` (+ `types.ts`, `queryKeys.ts`)".
- `pcs/mcp/server.py` import + one `register_source_routes(mcp)` line, and
  `server/tests/test_source.py` — the permitted source route + its registration + test.
- No new MCP tool for `source` (not required; the route is frontend-only like the
  other `web_api` additions).

### New dependencies
| Package | Kind | Why |
|---|---|---|
| `sigma@^3.0.3` | runtime | The graph renderer named in ROADMAP; WebGL canvas keeps a large graph responsive (NFR13). Vite-bundled, no CDN. |
| `graphology@^0.26.0` | runtime | Sigma's graph model (peer). |
No server dependencies added.

### Bundle size
`vite build`: `dist/assets/index-*.js` **475.51 kB raw / 133.92 kB gzip**, CSS
15.69 kB / 3.93 kB gzip. Sigma + graphology account for ~230 kB raw of that; still
under Vite's 500 kB warning threshold and a single chunk. If it needs trimming later,
Sigma can be a lazy `import()` gated on the code-map route.

---

## Post-merge change: graph → tree (2026-09-11)

The interactive Sigma.js/graphology graph was replaced with a **filterable file
tree** — the visual graph read as too convoluted. Everything else is unchanged:
the node inspector (symbols, dependencies/dependents, related context, read-only
source), the search panel with hit → node location, the context overlay
(hot-spot badges + legend), lazy per-subtree expansion (D9/AC20), and the
`get_code_map` / `/source` server APIs (untouched).

- **Removed:** `web/src/components/CodeGraph.tsx`, `web/src/lib/tokens.ts`, and
  the `sigma` + `graphology` dependencies. `lib/codemap.ts` lost `layout`,
  `Point`, and `nodeWeight` (graph-renderer-only).
- **Added:** `web/src/components/CodeTree.tsx` — an indented, path-sorted list of
  the loaded nodes; each row shows kind, label, language, LOC, fan-in/out and an
  overlay badge; directory rows with unloaded children get an "Expand" button.
  `lib/codemap.ts` gained `treeRows()` and `pathDepth()`.
- **Tests:** `codemap.test.ts` swapped the `layout`/`nodeWeight` cases for
  `treeRows` cases; new `components/CodeTree.test.tsx`.
- **Bundle:** `dist/assets/index-*.js` is now **315 kB raw / 95 kB gzip** (was
  475 kB / 134 kB).

---

## Post-merge change: tree → read-down document (2026-09-11)

The interactive tree was itself replaced with a **read-down "codebase map"
document** — a low-resolution written overview you read top to bottom, not a
widget to drive. The interactive graph is the agent's job now (`get_code_map`
over MCP / `context://{project}/code-map`); the web view is for a human building
a mental model. The node inspector and the search panel are **kept** — a path
anywhere in the document is a button that locates + opens it in the inspector,
exactly as a search hit does.

- **Removed:** `web/src/components/CodeTree.tsx` + test; `lib/codemap.ts` lost
  `treeRows`, `pathDepth`, `nodeMatchesFilter`, `graphLanguages` (tree/filter
  only). The path + language filter UI and the "Reset view" button are gone.
- **Added:**
  - `web/src/lib/codemapDoc.ts` — pure `buildCodeMapDoc(top, detail, {overview})`
    projecting the top two `get_code_map` tiers into `{ overview, areas[],
    connections[] }`, plus `hotSpotsFromEntries(blockers, bugs)` (open blockers /
    bugs → their `linked_files`). Unit-tested in `codemapDoc.test.ts`.
  - `web/src/components/CodeMapDocument.tsx` — renders it: Overview · Structure
    (per-area metrics, overlay badges, "depends on", child list) · Hot spots ·
    How it connects. Tested in `CodeMapDocument.test.tsx`.
  - `useCodeMapDoc` (hook) — a second top-level query at `depth=2` for the
    per-area child list; `queryKeys.codeMapDoc` (refresh picks it up by project).
- **Server:** untouched — same `get_code_map` / `/source` APIs, now called with
  `depth=2` for the document tier.
- **Bundle:** `dist/assets/index-*.js` **318 kB raw / 96 kB gzip** (unchanged —
  the tree was not the weight).
