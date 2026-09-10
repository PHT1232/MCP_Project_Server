# T03 — Code index: ingestion + keyword/structural search

**Branch:** `task/T03-index-keyword`  ·  **Depends on:** T00  ·  **Blocks:** T04, T05

> Stub — flesh out after T00.

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
- Keyword/structural search: exact + fuzzy text, symbol-name-ish, file globs;
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
FR19–FR21, FR23, FR23a, FR24–FR27, FR29, NFR9, NFR10. ACs: AC9 (partial), AC15.

## Acceptance checklist
- [ ] Indexes a sample repo respecting `.gitignore`; status reports counts + skipped-with-reason
- [ ] Keyword query returns correct path + line range + snippet
- [ ] Editing a file and re-querying within seconds reflects the change; stale results flagged (AC9)
- [ ] Dropping index tables + restart → clean rebuild, curated context untouched (AC15)
- [ ] Tests per AC; `just check` green
- [ ] Handoff written

## Handoff
_(fill in)_
