# T04 — Code index: symbols + semantic retrieval

**Branch:** `task/T04-index-semantic`  ·  **Depends on:** T03, T01  ·  **Blocks:** T05

> Stub — flesh out after T03.

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
