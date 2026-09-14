# T21 — Semantic query runtime fallback

**Branch:** `task/T21-semantic-runtime-fallback`  ·  **Base:** `task/T20-ai-provider-settings`

## Goal

Keep code search and relevance consumers available in keyword mode when the
configured embedding provider fails while embedding a query (NFR8, FR20, FR22),
without changing persisted index compatibility or exposing provider secrets
(NFR10, NFR11).

## In scope

- `server/src/pcs/index/embedding.py`
- `server/src/pcs/index/semantic.py`
- `server/src/pcs/index/hybrid.py`
- `server/src/pcs/index/service.py`
- `server/src/pcs/index/retrieval.py`
- `server/tests/test_semantic_runtime_fallback.py`
- This task file

## Acceptance checklist

- [x] Working semantic queries retain hybrid fusion and mode (FR20).
- [x] Missing backend and missing embeddings retain existing keyword fallback (AC10, AC21).
- [x] Timeout, connection, and provider failures at `backend.embed()` return keyword hits with a safe runtime note (NFR8).
- [x] Runtime fallback continues salient-term probing for relevance consumers (FR22).
- [x] Path/scope validation and unrelated programming errors still propagate.
- [x] Query fallback does not mutate embeddings, counts, or `reindex_required` (NFR10).
- [x] `semantic_query_failed` warning is structured and redacted (NFR6, NFR11).
- [x] MCP `search_code` returns a valid payload on query timeout (FR22).
- [x] Focused tests and `just check` are green.
- [x] Handoff written.

## Handoff

### Root cause

`hybrid_search()` correctly calculated keyword hits first, but
`semantic_search()` called `backend.embed([query])` without a provider-failure
boundary. Runtime timeout/connection/HTTP exceptions therefore escaped through
the service and MCP wrappers, discarding the already-computed keyword hits and
allowing raw provider exception text to reach `ToolError`.

### Implemented

- Added the redacted `EmbeddingProviderError` taxonomy at the embedding adapter
  boundary. The OpenAI-compatible adapter maps URL/provider validation,
  timeout, request/connection, HTTP status, and malformed/cardinality response
  failures without retaining sensitive text in the public exception message
  (NFR8, NFR11).
- Wrapped only `backend.embed([query])` in `semantic_search()` for protocol-level
  timeout/connection normalization. Vector SQL, scope resolution, keyword SQL,
  and result processing remain outside that catch, so validation, database, and
  programming errors are not converted to fallback.
- `hybrid_search()` catches only `EmbeddingProviderError`, returns the keyword
  hits already computed, marks semantic unavailable, supplies a fixed safe note,
  and emits `semantic_query_failed` with project, sanitized model/backend, and a
  finite error kind (NFR6, NFR8, NFR11).
- Surfaced `semantic_note` from `search_code`, `retrieve_context`, and
  `prepare_task`; retained `search_code.note` as a compatibility alias.
- Preserved the existing `gather_relevant()` branch: runtime fallback has
  `semantic_available=False`, so fewer than three primary hits trigger salient
  keyword-term probing (FR22).

### Files changed

- `server/src/pcs/index/embedding.py`
- `server/src/pcs/index/semantic.py`
- `server/src/pcs/index/hybrid.py`
- `server/src/pcs/index/service.py`
- `server/src/pcs/index/retrieval.py`
- `server/tests/test_semantic_runtime_fallback.py`
- `tasks/T21-semantic-runtime-fallback.md`

### Verification

- Regression-first run before implementation: `7 failed, 4 passed`; timeout and
  connection exceptions escaped to `search_code`, and MCP produced
  `Error executing tool search_code: ...` with the raw failure text.
- `uv run pytest tests/test_semantic_runtime_fallback.py -q` — **15 passed**.
- Focused index/retrieval/MCP/provider suite — **102 passed, 1 skipped**.
- `just check` — green: ruff format/lint, mypy strict, eslint, TypeScript
  typecheck, **304 passed / 1 skipped** server tests, **76 passed** frontend
  tests, Compose validation, and Vite production build.

The existing SCIP real-binary test remains the single skip because the binary
is unavailable. The two existing Starlette/httpx deprecation warnings remain.

### Trade-offs / deviations

- Query failures do not change `reindex_required`, counters, status, or stored
  document embeddings. This intentionally treats the failure as request-local;
  there is no circuit breaker or retry in this change.
- Model/backend log labels are restricted to a safe identifier character set;
  unusual labels are recorded as `<redacted>` rather than risk leaking a URL or
  credential.
- No schema migration and no new dependency.
- The branch is based on unmerged T20 because `reindex_required` and runtime AI
  provider settings exist there. No ROADMAP entry existed for this bug, so
  ROADMAP was not edited outside this task's scope. Branch was not pushed or
  merged.
