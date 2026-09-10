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
- [x] NL query returns the right file+symbol in top results on an unseen repo (AC8)
      — `test_ac8_natural_language_query_finds_file_and_symbol`
- [x] No embedding backend → keyword results + "semantic unavailable" surfaced (AC10, AC21)
      — `test_ac10_no_backend_keyword_results_and_note`, `test_ac21_status_shows_semantic_unavailable`
- [x] Supported language without its SCIP indexer → tags fallback, status shows fallback mode (AC23)
      — `test_ac23_tags_fallback_symbol_mode`, `test_ac23_status_dict_reports_modes`
- [x] `prepare_task` reports the split; small context → code pack expands (AC19, AC24)
      — `test_ac19_prepare_task_reports_split_within_budget`, `test_ac24_small_context_expands_code_pack`
- [x] Tests per AC; `just check` green
- [x] Handoff written

## Handoff

### Module layout (new / changed under `server/src/pcs/`)

```
index/
  ddl.py            —  (folded into schema.py; see F1)
  schema.py         *  F1: existence-probe + single _DDL rebuild path, no per-call DDL
  gitutil.py        *  F2: blob_map() — one `git ls-tree -r -z HEAD`
  chunker.py        *  F4: _collect_boundary_nodes + _dedupe (drop wrapper/exact/nested dups)
  models.py         *  +IndexSymbol / IndexSymbolRef / IndexSymbolEdge / IndexEmbedding,
                       chunks.chunk_hash, status.{symbol_modes,symbol_count,semantic_model,
                       embedded_chunk_count}
  embedding.py      +  EmbeddingBackend protocol; OpenAI-compatible + bundled `hashing`
                       backends; get_embedding_backend() + test override
  symbols.py        +  tree-sitter tags: extract_definitions / extract_imports /
                       resolve_import_target  (fallback, D14, AC23)
  scip.py           +  per-language SCIP indexer registry, availability probe,
                       subprocess runner, dependency-free SCIP protobuf decoder
  symbol_store.py   +  refresh_symbols() — persists ONE model from SCIP or tags, per-language mode
  semantic.py       +  embed_pending_chunks() (content-hash cache), semantic_search(),
                       hybrid_rank() (reciprocal-rank fusion), RankedHit
  hybrid.py         +  hybrid_search() (the one entry point) + gather_relevant()
                       (multi-term keyword expansion for NL task descriptions)
  retrieval.py      +  retrieve_context(), prepare_task() (FR22a split), pack_code_chunks()
  search.py         *  extracted resolve_search_scope() / ScopeClause / compute_stale()
                       so semantic reuses scope+glob plumbing; +MatchedMode
                       "semantic"/"hybrid"; SearchHit.content
  service.py        *  reindex(): F5 lock (code_index.status FOR UPDATE, not projects),
                       blob_map, symbol pass, embedding pass; search_code() → hybrid;
                       IndexStatusView + as_dict() carry symbol/semantic fields
mcp/index_tools.py  *  +retrieve_context, +prepare_task tools; search_code now hybrid
web_api/index_routes.py *  +POST /api/projects/{p}/retrieve-context, +.../prepare-task
context/summarizer.py   *  FR9d seam: backend-aware Summarizer (OpenAI chat), in-proc
                           cache keyed by entry hash; still off unless PCS_SUMMARY_BACKEND set
config.py               *  +PCS_EMBEDDING_* / PCS_SUMMARY_* / PCS_SCIP_INDEXERS
alembic/versions/0004_index_semantic.py  +  all of the above schema, `code_index` only
tests/test_index_semantic.py             +  AC8/10/21/23/19/24, F4, NFR10, SCIP decoder
```
`*` changed, `+` new.

### Run commands
- Gate: `just check` (repo root) — green (ruff, mypy --strict 52 files, pytest **70 passed
  / 1 skipped**, eslint/tsc/vitest, `vite build`, compose config).
- Migrate from empty: `just up && just migrate` → `0001→0002→0003→0004`. Down/up
  round-trip `0004↔0003` verified.
- Enable semantic search: set `PCS_EMBEDDING_BACKEND=openai` (+ `PCS_EMBEDDING_BASE_URL`,
  `_API_KEY`, `_MODEL`, `_DIMENSIONS`) **or** `PCS_EMBEDDING_BACKEND=hashing` (offline),
  then `reindex`. `get_index_status` / `search_code` report `semantic_available`.

### The symbol model (T05 consumes this)
One normalised SCIP-style model in schema `code_index`, filled identically by a real
SCIP indexer or the tags fallback; every row carries `mode ∈ {scip, fallback}`.

- `symbols(id, project_id, file_id, path, scip_symbol, name, kind, language,
  start_line, end_line, signature, mode)` — definitions. `scip_symbol` is the real
  SCIP symbol string in scip mode, or `local <path>#<name>:<line>` in fallback mode.
- `symbol_refs(... scip_symbol, name, start_line, end_line, is_definition, mode)` —
  occurrences (defs + uses). Fallback mode currently emits definition rows only.
- **`symbol_edges(id, project_id, src_path, dst_path, dst_module, kind, language, mode)`**
  — the dependency-edge shape **T05's `get_code_map` reads**:
  - `src_path` — repo-relative importing file (always set).
  - `dst_module` — raw import/include target string (always set):
    `"shop.pricing"`, `"react"`, `"./utils"`, `"fmt"`, `"<stdio.h>"`.
  - `dst_path` — resolved repo-relative target file, or `""` when unresolved
    (external package / stdlib / unresolvable relative). Resolution today covers
    relative JS/TS and dotted Python; extend in T05 if needed.
  - `kind` — `"import"` today (`"call"`/`"inherits"` reserved for scip mode).
  - unique on `(project_id, src_path, dst_path, dst_module, kind)`.
  Query for the map: `SELECT src_path, dst_path, dst_module, kind, mode FROM
  code_index.symbol_edges WHERE project_id = :p AND dst_path <> ''` for resolved
  file→file edges; drop the last predicate to also show edges to external modules.

### Embedding-backend contract (FR28, D7, NFR10, NFR11)
```python
class EmbeddingBackend(Protocol):
    name: str            # model id — part of the cache key
    dimensions: int      # pgvector column width; must match the model
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```
- `get_embedding_backend()` → instance or `None` (semantic off). `None` unless
  `PCS_EMBEDDING_BACKEND` is set. Tests inject via
  `set_embedding_backend_override(backend, active=True)`.
- Cache: `code_index.embeddings(chunk_hash, model, dim, embedding vector)`.
  `chunk_hash = sha256(chunk.content)`. `embed_pending_chunks()` only embeds hashes
  with no row for the active `model`, so unchanged chunks are never re-embedded
  across reindexes (NFR10 — `test_nfr10_unchanged_chunks_not_re_embedded`).
- Vectors stored/queried via raw SQL `CAST(:vec AS vector)` and `<=>` (cosine).
  No `pgvector` Python dep. No ANN index yet (exact scan) — fine at NFR1 scale;
  add ivfflat/hnsw when a dimension is pinned (T09 note).
- NFR11: the only outbound path is the configured `PCS_EMBEDDING_BASE_URL` /
  `PCS_SUMMARY_BASE_URL`. `hashing` is fully local.

### How F1/F2/F4/F5 were resolved
- **F1** — `ensure_index_schema()` now does one `SELECT to_regclass('code_index.embeddings')`
  and returns immediately when present (the normal path — effectively free). The
  full `_DDL` tuple runs only when the schema is actually missing (AC15 drop case).
  One list of `CREATE … IF NOT EXISTS`, no second copy of per-column migration DDL
  to keep in sync — migrations `0003`/`0004` own the forward/backward path, this
  file only heals a live DB whose schema was dropped under a stamped version.
- **F2** — `gitutil.blob_map()` runs one `git ls-tree -r -z HEAD`; `reindex()` calls
  it once and passes the `{path: blob}` dict into `_index_one_file`. Zero
  per-file subprocesses.
- **F4** — the chunker drops `export_statement`-style wrapper nodes that just wrap a
  declaration, then dedupes exact-span duplicates and fully-nested same-symbol/same-kind
  duplicates before returning. A class and its methods (different kinds) are kept on
  purpose — that granularity helps retrieval and each chunk is embedded at most once
  by content hash anyway.
- **F5** — `reindex()` no longer takes `resolve_project(for_update=True)`. It takes
  `SELECT project_id FROM code_index.status WHERE project_id = :pid FOR UPDATE`, so a
  long index serialises other reindexes but never blocks T01 context writes.

### Seams for T05
- Dependency edges: `code_index.symbol_edges` (shape above).
- File nodes: reuse `code_index.files` (path, language) as T03 said.
- `symbols` / `symbol_refs` give node-level detail for the zoomed-in map.
- `get_index_status().as_dict()` gained `symbol_modes`, `symbol_count`,
  `semantic_available`, `semantic_model`, `embedded_chunk_count`, `semantic_note`
  for the frontend index panel (T06/T07, FR37, AC21).

### Deviations / decisions to confirm
1. **SCIP indexers not exercised end-to-end.** No `scip-*` / `rust-analyzer`
   binary is installable in this offline env. Implemented and wired: the
   per-language registry, `PCS_SCIP_INDEXERS` overrides, `shutil.which` availability
   probe, subprocess runner, and a dependency-free SCIP protobuf decoder
   (`parse_scip_index`, unit-tested with hand-encoded bytes in
   `test_parse_scip_index_decodes_documents_and_symbols`). The subprocess→normalise
   path runs only when a binary is present; `test_scip_real_binary_path_or_documented_skip`
   **`pytest.skip`s loudly** (not xfail) when `scip-python` is absent. The
   tree-sitter tags fallback is the fully-tested path and is what AC23 checks.
   **Follow-up:** verify the SCIP path against a real `scip-python`/`scip-typescript`
   in an environment that has them, and flesh out `symbol_refs` cross-file
   resolution + `kind='call'/'inherits'` from SCIP relationships.
2. **Bundled `hashing` embedding backend.** A zero-dependency, offline, deterministic
   n-gram feature-hashing vectoriser, **opt-in** via `PCS_EMBEDDING_BACKEND=hashing`.
   Semantic search is still OFF by default (D7 honoured). It exists so AC8 / the
   semantic pipeline are testable offline and so air-gapped installs have an option.
   Real deployments use `openai`. Confirm this is acceptable vs. "nothing bundled".
3. **`.env.example` NOT updated** — this session's tooling has a hard
   `Read(.env.*)` deny rule, so the file could not be edited. The settings are in
   `pcs.config` with full descriptions. **Please add this block** after
   `PCS_INDEX_WATCH=true`:
   ```
   PCS_EMBEDDING_BACKEND=
   PCS_EMBEDDING_BASE_URL=https://api.openai.com/v1
   PCS_EMBEDDING_API_KEY=
   PCS_EMBEDDING_MODEL=text-embedding-3-small
   PCS_EMBEDDING_DIMENSIONS=1536
   PCS_EMBEDDING_BATCH_SIZE=64
   PCS_EMBEDDING_TIMEOUT_SECONDS=30
   PCS_SUMMARY_BACKEND=
   PCS_SUMMARY_BASE_URL=https://api.openai.com/v1
   PCS_SUMMARY_API_KEY=
   PCS_SUMMARY_MODEL=gpt-4o-mini
   PCS_SCIP_INDEXERS=
   ```
4. **Migration head collision with T02.** T02's unmerged `0004_requirements_file`
   also descends from `0003_code_index`. When both merge there will be two `0004`
   heads off `0003`; the integrator picks a linearisation (rename one to `0005`
   or add a merge revision). T04 is correct against current `main`.
5. **`prepare_task` briefing regeneration.** To honour the 30% code floor when
   curated context is large, the briefing is regenerated at a smaller
   `max_tokens` rather than string-truncated — cleaner and stays on section
   boundaries. Split is always reported in `result["split"]`.
6. **FR9d summarizer cache is process-local** (dict), not a table. Persistent
   caching keyed by content hash is a small follow-up (needs a `context` schema
   migration, which the task allowed but which had no AC).
7. **`test_integration.py` expected-tool-set** and **`test_index.py` route
   assertions** updated for the two new tools/routes (necessary consequence of
   the new surface, not scope creep).

### New dependencies
| Package | Why | ROADMAP-aligned |
|---------|-----|-----------------|
| `httpx>=0.27` | OpenAI-compatible embedding + FR9d summary HTTP calls. Already a transitive dep of `mcp`; now declared directly. | yes (MCP SDK stack) |

No `pgvector` Python package (raw-SQL vector casts), no `protobuf` (hand-rolled
SCIP decoder), no SCIP binaries bundled.
