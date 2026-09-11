# T10 — Requirement contract model

**Branch:** `task/T10-contract-model`  ·  **Depends on:** T09  ·  **Blocks:** T11, T12

## Goal

Add the normalized, store-owned model for invariants and acceptance criteria while preserving existing requirement behavior and file synchronization.

## Owned files/modules

- `server/src/pcs/db/models.py`
- New Alembic migration under `server/src/pcs/alembic/versions/`
- New `server/src/pcs/requirements/contracts.py`
- `server/src/pcs/context/types.py` only for shared contract enums/value types
- New `server/tests/test_requirement_contracts.py`
- Migration/schema tests directly required by this task

Do not edit MCP registration, `prepare_task`, frontend code, or requirements Markdown sync grammar.

## Requirements

- Add invariant records with stable per-requirement keys, statement, kind (`behavior`, `architecture`, `data-boundary`, `forbidden-path`, `integration`, `manual`), risk, and deterministic order.
- Add acceptance criteria linked to invariants, with stable keys, statement, evidence kind, required flag, and independent-review policy.
- Provide service functions to create, list, merge-update, and soft-delete invariants/criteria.
- Preserve immutable revision history for contract mutations using an explicit contract revision table or equivalent append-only audit records.
- Enforce project and requirement isolation and bound all statement fields.
- Existing requirements with no criteria retain current status semantics.
- Contract records are PostgreSQL source-of-truth and are not added to `.project-context/requirements.md` in this task.

## Acceptance checklist

- [x] Migration upgrades from current head and downgrades cleanly; no existing requirement data changes — `test_migration_upgrades_from_prior_head_and_downgrades_without_changing_requirement_rows`
- [x] Stable keys are unique within their parent scope and duplicate writes return actionable errors — `test_stable_keys_are_unique_within_parent_and_duplicates_are_actionable`
- [x] Invariant and criterion CRUD is project-isolated and fully typed — `test_invariant_and_criterion_crud_is_project_isolated_and_typed`
- [x] Soft deletion removes records from active reads but preserves immutable history — `test_soft_delete_hides_from_active_reads_and_preserves_history`
- [x] Invalid kind, risk, evidence kind, overlong statement, and cross-project links are rejected — `test_invalid_kind_risk_evidence_statement_and_cross_project_links_are_rejected`
- [x] Requirements without criteria behave exactly as before in status updates — `test_requirements_without_criteria_keep_legacy_status_updates`
- [x] Every acceptance item has a regression test (plus hidden-parent, DB isolation, revision immutability, IntegrityError translation, ordering)
- [x] Focused tests and `just check` pass — 11/11 focused
- [x] Handoff lists schema, API seams for T11/T12, migration revision, and deviations

## Verification

```bash
cd server && uv run pytest tests/test_requirement_contracts.py
just migrate
just check
```

## Handoff

### Schema (revision `0006_requirement_contracts`, revises `0005_index_semantic`)

New tables only; existing requirement *rows* are unchanged. Composite uniques on `context_entries` (`id, project_id` and `id, section`) enable isolation FKs.

| Table | Role |
|-------|------|
| `requirement_invariants` | Stable per-requirement `key`, `statement`, `kind`, `risk`, `sort_order`, soft-delete `status`. Composite FKs to `(context_entries.id, project_id)` and `(id, section)` plus `requirement_section='requirements'` so SQL cannot attach to another project or a non-requirement entry. Statement `char_length` 1–2000. |
| `acceptance_criteria` | Stable per-invariant `key`, … Composite FK `(invariant_id, project_id)`. Statement bound 1–2000. |
| `requirement_contract_revisions` | Append-only snapshots. `BEFORE UPDATE` trigger rejects mutation. Parent requirement FK is `ON DELETE RESTRICT` so history outlives soft-delete and blocks hard-delete of that entry. Project teardown may `CASCADE` via `project_id`. |

Invariant kinds: `behavior`, `architecture`, `data-boundary`, `forbidden-path`, `integration`, `manual`.
Risk: `low`, `medium`, `high`.
Evidence kinds (shared with T12): `test`, `command`, `review`, `manual`, `file`.
Independent-review policy: `not-required` \| `required`.
Statements capped at 2000 chars (`CONTRACT_STATEMENT_MAX_CHARS`).

Keys are unique **including soft-deleted rows** (never reused on the same parent). Same key is allowed on a different requirement/invariant.

### Service API seams (`pcs.requirements.contracts`) — no MCP in T10

T11 should import these; do not duplicate SQL:

- `create_invariant` / `update_invariant` / `delete_invariant` / `list_invariants` / `get_invariant`
- `create_criterion` / `update_criterion` / `delete_criterion` / `list_criteria` / `get_criterion`
- `list_contract_revisions`
- Views: `InvariantView`, `CriterionView`, `ContractRevisionView` (`.as_dict()`)

`list_criteria` takes exactly one of `invariant_id` or `requirement_id`.
Soft-deleting an invariant also soft-deletes its open criteria (each gets a revision).
Omitted `key` auto-allocates `INV-NNN` / `AC-NNN` within the parent.

T12: do **not** gate `set_requirement_status` in this branch. Requirements with **no criteria** still accept `done`. T12 should wrap that function and reject `done` only when the requirement has configured (active) criteria. Evidence/violations tables are T12's migration.

T11: `prepare_task` / MCP tools are untouched. Empty contracts should be a no-op there. When T12 data is absent, treat review as `not-configured`.

### Out of scope (unchanged)

MCP registration, `prepare_task`, frontend, requirements Markdown parser/sync grammar.

### How to run

```bash
cd server && uv run pytest tests/test_requirement_contracts.py
just check
```

Upgrade/downgrade from prior head is covered by the isolated Postgres test (does not mutate the compose database). Session fixture `migrated_db` still upgrades empty → head.

### `just check`

Green: server ruff + mypy --strict, pytest (including 11 contract tests), web eslint/tsc/vitest/vite build, compose-lint.

### Review-fix regressions (91062d9 follow-up)

- Hidden/deleted/archived parent: active child reads 404/empty; `include_deleted` and `list_contract_revisions` still work — `test_hidden_parent_hides_active_child_reads_but_history_remains`
- DB isolation + statement CHECK + revision UPDATE trigger + requirement hard-delete RESTRICT — `test_db_enforces_project_section_isolation_and_statement_bounds`
- Unique-index IntegrityError is isolated by a savepoint; the same session can continue after ValidationError — `test_integrity_error_leaves_the_transaction_usable`
- Criterion list order `(sort_order, key, invariant_id, id)` — `test_criteria_order_is_deterministic_with_id_tie_breakers`

### Deviations / decisions to confirm

1. **Evidence-kind vocabulary** is defined here so T12 can store matching `kind` values. T12 may extend the check constraint if it needs more kinds.
2. **Independent review** is a string policy (`not-required`/`required`), not a bool, so T12 can add values without renaming the column.
3. **Live `just migrate` against compose Postgres was not run** (shared DB). Equivalent proof: empty→head via `migrated_db`, and 0005→head→0005 in `test_migration_upgrades_from_prior_head_and_downgrades_without_changing_requirement_rows`.
4. **T11–T13 task files are not in this branch** (not started). ROADMAP Phase 3 lists them; only T10 is implemented.
5. **T09 is still in review**; this branch is off current `main` (`2a941a4`). T09 had no schema dependency.
6. **Constraint failure isolation:** contract create/update opens a nested transaction before mutation. A failed flush rolls back only that savepoint, is translated to `ValidationError`, and leaves the same `AsyncSession` usable.

### New dependencies

None.
