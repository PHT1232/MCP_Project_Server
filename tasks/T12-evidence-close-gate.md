# T12 — Evidence ledger and deterministic close gate

**Branch:** `task/T12-evidence-close-gate`  ·  **Depends on:** T10  ·  **Can run with:** T11  ·  **Blocks:** T13

## Goal

Record compact evidence with revision provenance and prevent false completion when configured acceptance criteria are missing, failed, stale, or blocked by an open violation.

## Owned files/modules

- New Alembic migration for evidence and violations
- New `server/src/pcs/requirements/evidence.py`
- `server/src/pcs/db/models.py` — evidence/violation tables, ownership uniques, and composite FKs (required by the T12 schema)
- `server/src/pcs/context/service.py` only around requirement status transitions
- Requirement evidence MCP tools in a new registration module
- `server/src/pcs/mcp/server.py` only for registration
- New `server/tests/test_requirement_evidence.py`
- `server/tests/test_integration.py` — `EXPECTED_TOOLS` union with T12 evidence tools
- `docs/mcp-reference.md`
- `ROADMAP.md` — T12 status only
- `tasks/T12-evidence-close-gate.md` — checklist and handoff

Do not edit `prepare_task`, retrieval ranking, frontend code, or requirement-file grammar.

## Requirements

- Store compact evidence: criterion ID, kind, result (`passed`, `failed`, `manual-pending`), command/test/file references, source commit, optional worktree fingerprint, author, timestamp, and optional artifact reference.
- Do not store full stdout, full diffs, credentials, or arbitrary binary payloads.
- Store review violations linked to invariants with severity, concise summary, optional file/line, lifecycle status, author, and timestamps.
- Derive close-gate state deterministically from required criteria, latest valid evidence, source revision/fingerprint freshness, independent-review policy, and open blocking violations.
- Add tools to record/list evidence, add/resolve violations, and evaluate the close gate.
- Keep `set_requirement_status` backward compatible: requirements without configured criteria may still become `done`; configured requirements receive an actionable rejection until the gate passes.
- Independent-review evidence must have an author different from the recorded implementer when policy requires it.
- Evidence does not automatically change requirement status, preserving D4.

## Acceptance checklist

- [x] Missing required criterion rejects `done` and names the criterion key — `test_missing_required_criterion_rejects_done_and_names_key`
- [x] Latest failed evidence rejects `done`; later passing current evidence supersedes it without deleting history — `test_failed_evidence_rejects_done_until_later_pass_supersedes`
- [x] Evidence from an older commit/fingerprint is reported stale and rejects `done` — `test_older_commit_is_stale_and_rejects_done`
- [x] Open blocking violation rejects `done`; resolving it preserves history and removes the block — `test_open_blocking_violation_rejects_done_until_resolved`
- [x] Independent-review policy rejects self-authored review evidence — `test_independent_review_rejects_self_authored_review`
- [x] Requirement with no configured criteria preserves legacy status behavior — `test_requirements_without_criteria_keep_legacy_status_updates`
- [x] No-criteria requirement with an open blocking violation rejects `done` — `test_no_criteria_open_blocking_violation_rejects_done`
- [x] Open blocking violation still rejects `done` after the parent invariant is soft-deleted; deleted required criteria are omitted from `ac_total` / missing / stale — `test_open_blocking_violation_survives_soft_deleted_invariant`
- [x] Evidence payload limits reject raw/oversized log-like content and secrets are not echoed in errors — `test_payload_limits_reject_logs_and_do_not_echo_secrets`
- [x] Concurrent evidence writes preserve all records and produce deterministic latest-evidence selection — `test_concurrent_evidence_writes_preserve_all_and_latest_is_deterministic`
- [x] Criterion update binds a new revision and makes prior evidence stale — `test_criterion_update_makes_prior_evidence_stale`
- [x] Latest review result (failed / manual-pending) supersedes an older pass — `test_latest_failed_review_supersedes_older_pass`
- [x] Short SHA expands to 40 characters or is rejected — `test_short_sha_expands_or_rejects`
- [x] Dirty file content changes the worktree fingerprint when porcelain is unchanged — `test_dirty_content_changes_fingerprint_with_same_porcelain`
- [x] Staged-only index changes after a clean-tree record are stale — `test_staged_index_change_after_clean_evidence_is_stale`
- [x] Untracked file creation and same-path content change are stale — `test_untracked_file_content_change_is_stale`
- [x] Unreadable git state fails closed — `test_unreadable_git_state_fails_closed`
- [x] DB ownership constraints reject cross-requirement/cross-revision SQL — `test_ownership_constraints_reject_cross_requirement_and_revision_sql`
- [x] Close-gate / done serializes with add and resolve violation — `test_done_waits_for_in_flight_add_violation`, `test_done_waits_for_in_flight_resolve_violation`
- [x] Close-gate / done shares the T10 project lock with criterion mutations — `test_criterion_mutation_serializes_with_done_transition`
- [x] Real T12→T11 ranking for missing/stale/blocking — `test_t12_close_gate_ranks_missing_stale_and_blocking_in_task_contract`
- [x] Focused tests, `just migrate`, and `just check` pass — `tests/test_requirement_evidence.py` 28 passed; `tests/test_task_contract.py` 26 passed; `just migrate` already at `0007`; `just check` green (206 passed / 1 skipped server, 56 vitest); `git diff --check` clean
- [x] Handoff documents freshness semantics and compatibility behavior

## Verification

```bash
cd server && uv run pytest tests/test_requirement_evidence.py
just migrate
just check
```

## Handoff

Status: **in progress** on `task/T12-evidence-close-gate` (merged `main` `7a2beb1` / T11). Uncommitted. R-061 stays **in-progress**. Not marking done. Requesting independent review of close-gate `ac_total` accounting after a soft-deleted invariant.

### Base / T11

Branch fast-forwarded from `30ca8b0` to `7a2beb1` so T11 compact retrieval is present. T11 ranking / `prepare_task` were not edited. T12 `summarize_close_gate` is consumed by T11 `_load_close_gate`.

### Schema (revision `0007_requirement_evidence`, revises `0006_requirement_contracts`)

| Table | Role |
|--------|------|
| `requirement_evidence` | Append-only compact evidence. Composite FKs: requirement+project, criterion+project, `(contract_revision_id, requirement_id)`, `(contract_revision_id, criterion_id)`. Stored `source_commit` is exactly 40 hex. `seq` is latest-evidence order. Trigger rejects UPDATE/DELETE. |
| `requirement_violations` | Findings on an invariant. Composite FK `(invariant_id, requirement_id)`. `resolve` sets `status=resolved`, `resolved_at`, and `resolved_by`. Only `severity=blocking` + `status=open` reject `done`. |

Also adds uniques used by those FKs: `uq_acceptance_criteria_id_project`, `uq_requirement_invariants_id_requirement`, `uq_requirement_contract_revisions_id_requirement`, `uq_requirement_contract_revisions_id_entity`.

Direct SQL that mixes another requirement’s criterion/revision/invariant is rejected (`test_ownership_constraints_reject_cross_requirement_and_revision_sql`).

### Freshness / SHA / git fail-closed

- `source_commit` input is 7–40 hex. Short SHAs are expanded with `git rev-parse --verify`; unresolvable shorts are rejected. Full 40-char SHAs are stored as-is. DB check is `char_length = 40`.
- Worktree fingerprint hashes three layers: the index (`git ls-files -s -z`, so staged-only blob changes count), unstaged worktree bytes (`git diff --name-only -z` plus file contents), and untracked file bytes (`git ls-files -o --exclude-standard -z`). Creating an untracked file or changing that file’s bytes with the same path/status is stale. Porcelain text alone is not used.
- If HEAD or any dirty-layer listing cannot be read, required evidence is **stale** (fail closed). Unreadable git does not skip freshness.
- Evidence is stale when `source_commit != HEAD`, stored fingerprint ≠ current dirty digest, git is unreadable, or `contract_revision_id` is not the criterion’s current T10 revision (criterion update stale-binds old rows).

### Close gate

- Legacy `done` only when there are **no criteria and no open blocking violations**.
- Required criteria: latest matching-kind evidence on the **current** criterion revision must be `passed` and not stale.
- Independent review: pick the latest **review of any result**, then check result / freshness / identity. Latest `failed` or `manual-pending` supersedes an older pass. Reviewer identity is `strip().casefold()` vs the implementer.
- Open blocking violations reject `done`, including when the parent invariant is soft-deleted (keys resolved via `list_invariants(..., include_deleted=True)`). Required criteria are those whose parent is still active (`invariant_id in active_ids`); a soft-deleted parent is omitted from `ac_total` / missing / stale and cannot yield `passed=true` with `ac_verified=0/ac_total=1`.
- `evaluate_close_gate` / `assert_close_gate_allows_done` (`set_requirement_status` → `done`), `record_evidence`, `add_violation`, and `resolve_violation` take the same **project** `SELECT … FOR UPDATE` as T10 `contracts.py` criterion/invariant mutations, then lock the requirement row. A criterion mutation cannot commit between gate evaluation and `done`; if the mutation holds the lock first, `done` waits and evaluates the new revision (stale). Violation add/resolve still serialize with `done` on the requirement row.

Recording evidence never changes status (D4).

### T11 seam

`summarize_close_gate` payload unchanged in shape: `ac_verified`/`ac_total`, `missing_keys`, `missing`/`stale` as `{id, key, invariant_id, invariant_key}`, `stale_count`, `validation`, `review`, `blocking`. Real integration (no `_load_close_gate` mock): missing / stale / blocking parents rank above peers in `get_task_contract`.

### MCP

Tools declare enums (`kind`, `result`, `severity`), SHA pattern `^[0-9a-fA-F]{7,40}$`, and bounds (`summary` 1–200, `line_no` ≥ 1, ref max lengths). Author is the MCP caller; resolver is stored on resolve.

### Checks (this cycle)

- `uv run pytest tests/test_requirement_evidence.py tests/test_task_contract.py` — 28 + 26 passed
- `just migrate` — already at `0007_requirement_evidence`
- `just check` — 206 passed / 1 skipped server, 56 vitest, mypy/ruff/eslint/tsc/vite/compose green
- `git diff --check` — clean
- `git diff -- ROADMAP.md` — T12 `not started` → `in progress` only; T11 stays `in progress`

### Files

In-scope T12 edits (owned or required for the schema/tools/status):

- `server/src/pcs/alembic/versions/0007_requirement_evidence.py`
- `server/src/pcs/db/models.py` — evidence/violation tables, ownership uniques, composite FKs
- `server/src/pcs/requirements/evidence.py`
- `server/src/pcs/context/service.py` — `set_requirement_status` close-gate only
- `server/src/pcs/mcp/evidence_tools.py` and `server/src/pcs/mcp/server.py` registration
- `server/tests/test_requirement_evidence.py`
- `server/tests/test_integration.py` — `EXPECTED_TOOLS` includes T12 evidence tools
- `docs/mcp-reference.md`
- `ROADMAP.md` — T12 **in progress** only (T11 row unchanged)
- `tasks/T12-evidence-close-gate.md` — checklist and handoff

### Out of scope

`prepare_task`, T11 ranking implementation, frontend, requirements Markdown grammar, T13. No commit. R-061 not marked done.

### New dependencies

None.
