# T04 — Code index: symbols + semantic retrieval

**Branch:** `task/T04-index-semantic`  ·  **Depends on:** T03 + T01 (both merged)  ·  **Blocks:** T05

**Read first:** `AGENTS.md`, `REQUIREMENTS.md` §7.6 + §7.2a (FR9d seam) + D7/D13/D14,
`reviews/T03.md` (esp. F1–F5 and "Notes for dependents → T04"),
`tasks/T03-index-keyword.md` Handoff, `reviews/T01.md` (FR9d summarizer seam).
Base branch off current `main`.

**T03 gives you:** `pcs.index` — `search.keyword_search()` (returns
`SearchResult`/`SearchHit` — **wrap it, don't re-implement the FTS/trigram SQL**),
`code_index.{files,chunks,status}` schema, tree-sitter chunker, repo walk,
incremental reindex, `get_index_status` / `reindex` / keyword-only `search_code`
(already returns `semantic_available: false`). `prepare_task_token_budget` is
stored per project (D13 default 4000). T01's `pcs.context.summarizer.get_summarizer()`
is the FR9d seam — replace it with your backend-aware instance.

**Also fix the T03 follow-ups where they touch code you extend:**
- **F1** — `pcs.index.schema.ensure_index_schema` duplicates the migration DDL
  and runs ~10 `IF NOT EXISTS` statements on every call. Move to a one-time
  process guard / startup hook.
- **F2** — `_index_one_file` spawns `git rev-parse HEAD:<path>` per file. Batch
  (`git ls-tree -r HEAD`) or drop it (content_hash already covers staleness).
- **F4** — the chunker emits overlapping nested chunks (class + each method,
  `export function` twice). Dedupe before you embed them.
- **F5** — `reindex` takes the project-row `FOR UPDATE` lock (same one T01 uses
  for context writes). Lock the `code_index.status` row instead.

## Goal
Add symbol/cross-reference data and embedding-based retrieval on top of T03, and
ship the agent-facing search tools.

## In scope
- Per-language SCIP indexers as subprocesses (FR23c/D14): `scip-typescript`,
  `scip-python`, `scip-java`, `scip-go`, `rust-analyzer`, `scip-dotnet`,
  `scip-clang`. Normalize all output to one SCIP-style symbol model in PG
  (definitions, references, dependency edges).
- Fallback to tree-sitter `tags` queries + import/include queries when an
  indexer is missing/fails; `get_index_status` reports per-language mode (AC23).
- Embedding-backend interface (FR28/D7): pluggable, none bundled; keyword-only
  until configured. Content-hash embedding cache (NFR10). Vectors in `pgvector`.
- Hybrid `search_code` (keyword + semantic, ranked) (FR20, FR22).
- `retrieve_context` — token-bounded relevant-chunk pack (FR22).
- `prepare_task` — briefing (calls into T01) + relevant code in one budgeted
  response; context capped 50%, code floored 30%, slack to code, split reported
  (FR22, FR22a, D13).

## Key requirements
FR20, FR22, FR22a, FR23b, FR23c, FR25, FR28, NFR8, NFR10, NFR11. ACs: AC8, AC10,
AC19, AC21, AC23, AC24.

## Acceptance checklist
- [ ] NL query returns the right file+symbol in top results on an unseen repo (AC8)
- [ ] No embedding backend → keyword results + "semantic unavailable" surfaced (AC10, AC21)
- [ ] Supported language without its SCIP indexer → tags fallback, status shows fallback mode (AC23)
- [ ] `prepare_task` reports the split; small context → code pack expands (AC19, AC24)
- [ ] Tests per AC; `just check` green
- [ ] Handoff written

## Handoff
_(fill in)_
