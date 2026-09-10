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
- [ ] Map renders top-level nodes matching real module structure; expand loads children lazily (AC11, AC20 client side)
- [ ] Open blocker/bug on a file marked on its node (AC12)
- [ ] Node select → inspector with source, deps/dependents, related context (AC13)
- [ ] Search result locates + highlights the node
- [ ] Stays responsive on a large graph
- [ ] Design tokens only (AC27); frontend checks green
- [ ] Handoff written

## Handoff
_(fill in)_
