# T15 — Codebase Guide storage and service

**Branch:** `task/T15-codebase-guide-core` · **Depends on:** T14 · **Blocks:** T16

## Goal

Create durable per-file agent-authored notes, deterministic guide reads, freshness tracking, and safe one-way Markdown generation.

## Owned files/modules

- New `server/src/pcs/repofile.py`
- New `server/src/pcs/alembic/versions/0008_codebase_guide.py`
- `server/src/pcs/index/schema.py`
- `server/src/pcs/config.py`
- New `server/src/pcs/codemap/guide.py`
- New `server/tests/test_codebase_guide.py`

Do not edit MCP/HTTP/frontend/docs/requirements modules or `requirements/service.py`.

## Invariants

- `INV-GUIDE-1`: Summary prose is supplied by the caller; no auto-stub or LLM generation exists.
- `INV-GUIDE-2`: Indexed facts come only from active non-skipped index rows and resolved symbol edges.
- `INV-GUIDE-3`: Notes survive full reindex because identity is `(project_id, path)`, never `files.id`.
- `INV-GUIDE-4`: A note is stale exactly when its captured hash differs from the current indexed hash.
- `INV-GUIDE-5`: Generated file writes cannot escape the configured root through a relative path; writes are atomic.
- `INV-GUIDE-6`: Read-only artifact failure never rolls back a valid note write and is reported explicitly.
- `INV-GUIDE-7`: Migration and AC15 heal schema stay equivalent; existing index data remains intact.

## Requirements

- Add migration `0008_codebase_guide`, down revision `0007_requirement_evidence`, creating `code_index.file_notes` with the plan schema and downgrade.
- Add equivalent `file_notes` DDL to the AC15 schema-heal list. Ensure the schema probe cannot return early while `file_notes` is missing.
- Add `codebase_guide_file`, default `.project-context/CODEBASE_GUIDE.md`, exposed as `PCS_CODEBASE_GUIDE_FILE`.
- Add safe reusable `atomic_write`, `dir_writable`, and configured-path resolution helpers. Include the requested why-comment; do not refactor requirements sync.
- Implement `get_codebase_guide`, `describe_files`, `write_guide_file`, and `render_guide_markdown` without MCP/HTTP imports.
- Validate include mode and scope. Unknown scope mirrors existing `CodeMapError` behavior.
- Apply all valid notes in mixed requests, report unknown/skipped paths with bounded near matches, and fail if every path is unknown.
- Empty summary deletes a note. Reject malformed/duplicate paths and summaries that violate existing bounded-write/privacy conventions.
- Generate deterministic Markdown grouped by top directory, with coverage, do-not-edit notice, summary/undocumented marker, imports/importers, and stale marker.

## Acceptance checklist

- [x] Migration upgrade/downgrade round-trip preserves existing index tables — `test_migration_upgrade_downgrade_preserves_index_tables`
- [x] AC15 schema heal recreates `file_notes` and does not early-return without it — `test_ac15_heals_file_notes_when_only_that_table_is_missing`
- [x] Upsert captures current content hash, caller, timestamp, and updates coverage — `test_upsert_captures_hash_caller_coverage`
- [x] Full reindex does not delete notes for paths that remain indexed — `test_full_reindex_preserves_notes`
- [x] Mixed valid/unknown writes apply valid notes and return bounded near matches — `test_mixed_unknown_empty_delete`
- [x] All-unknown input fails; empty summary deletes — same test
- [x] Scope and all four include modes return deterministic correct subsets — `test_scope_and_include_modes`
- [x] Symbols/imports/importers and index provenance come from index facts — `test_guide_reads_index_facts_only`
- [x] Hash change marks a note stale without altering its prose — `test_hash_change_marks_stale_without_changing_prose`
- [x] Relative traversal is rejected and generated writes are atomic — `test_relative_traversal_rejected_and_writes_atomic`
- [x] Read-only artifact path reports non-writable while preserving the DB note — `test_readonly_artifact_preserves_db_note`
- [x] Markdown output is deterministic and contains coverage, prose, connections, undocumented and stale states — `test_markdown_is_deterministic`
- [x] Focused tests and `just check` pass
- [x] Handoff lists schema, payload shape, security decisions, test evidence, and limitations
- [x] Independent review of path safety, transactions, schema healing, and SQL parameterization

## Required evidence

- Migration command evidence: upgrade, downgrade `-1`, upgrade head.
- Tests covering every checklist item in `test_codebase_guide.py`.
- Independent review of path safety, transaction behavior, schema healing, and SQL parameterization.

## Verification

```bash
just migrate
cd server && uv run pytest tests/test_codebase_guide.py
cd server && uv run ruff check . && uv run mypy
just check
```

## Handoff

Status: **code + independent review clean** on `task/T15-codebase-guide-core` @ `f89efcc`. R-064 stays **in-progress** — close gate blocked on fresh evidence at this SHA.

### Review fixes (this pass)

- **INV-GUIDE-5 / blocking `4054d8f2`:** FIXED + resolved. `atomic_write(..., contain_under=)` re-checks before `os.replace` and on the final path; relative `write_guide_file` passes project root.
- **INV-GUIDE-2 / warning `31e69995`:** FIXED + resolved. `_load_connections` joins both endpoints to active `code_index.files` (`skipped=false`).
- **Tests:** symlink race, interrupted replace, connection skipped/missing endpoints; removed tautological markdown assertion.

### Independent review

Agent [T15 independent review](4d9c8799-9e73-4726-bb4a-9d55f32052f4) verdict **CLEAN** at `f89efcc`. Both prior findings FIXED; AC-GUIDE-1/2/3/5/6/7 pass; only notes on absolute configured paths and post-replace cleanup.

### PCS gate (live)

- Violations `4054d8f2` and `31e69995`: **resolved**
- `evaluate_close_gate`: `passed=false`, `review=passed`, `validation=stale`, `ac_verified=0/12`
- **Blocker:** PCS project root is `/repos/MCP_Project_Server` on host `100.86.141.82`. Recording evidence with `source_commit=f89efcc…` fails: `source_commit must resolve to an existing commit object` (T19 strict git resolve). No push was done per instructions, so the remote checkout cannot see this SHA. After the SHA is available on that root (push + pull, or equivalent sync), re-record all 12 ACs + review evidence, re-run `evaluate_close_gate`, then set `R-064=done` only if it passes.

### Validation

- `uv run pytest tests/test_codebase_guide.py` — 13 passed (container migration round-trip included)
- `just check` — 241 passed / 1 skipped server, 68 vitest
- `ruff` / `mypy --strict` / `git diff --check` — clean

### Schema / payload / security

Unchanged from prior handoff: path-keyed `file_notes`, include modes, bound SQL, read-only artifact degradation, write-time root containment for relative guide paths.

### Limitations / out of scope

No MCP/HTTP/frontend (T16–T18). No push/merge. Evidence + `R-064=done` still pending remote commit visibility.

### New dependencies

None.

