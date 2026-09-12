# T19 — Token-efficient evidence quality and review gates

**Branch:** `task/T19-evidence-quality` · **Base:** `13b983b` · **Requirement:** R-069 (`8216ee52-1a19-4711-82ee-b55d00ef7502`)

## Goal

Strengthen evidence recording and compliance review with explicit lifecycle state, dirty-worktree safeguards, scoped independent review, deterministic weak-evidence warnings, persisted findings, and bounded compact contract status.

## Owned files/modules

- `server/src/pcs/requirements/evidence.py`
- `server/src/pcs/requirements/compliance.py`
- `server/src/pcs/requirements/briefing.py` only for compact evidence/warning/review counts
- `server/src/pcs/db/models.py` only for T19 evidence columns and constraints
- `server/src/pcs/mcp/evidence_tools.py` only for T19 evidence fields
- New Alembic revision `server/src/pcs/alembic/versions/0019_evidence_quality.py`
- Focused tests in `server/tests/test_evidence_quality.py` plus minimal updates to existing evidence/compliance/task-contract tests when compatibility requires them
- This task file

Do not edit T15–T18 modules, `ROADMAP.md`, shared frontend code, or main-level docs. T15 reserves migration number `0008`; T19 uses globally unique revision id `0019_evidence_quality`, currently based on `0007_requirement_evidence`. Integration sequencing must rebase or merge this revision onto the eventual post-T15–T18 Alembic head before merge if those branches add migrations.

## Contract

- `INV-EVIDENCE-1..7`
- `AC-EVIDENCE-1..12`

## Acceptance checklist

- [x] AC-EVIDENCE-1: Dirty-worktree evidence without `worktree_fingerprint` is rejected with compact `dirty-worktree` / required-field detail and no paths.
- [x] AC-EVIDENCE-2: Dirty-worktree evidence with a bounded valid fingerprint is provisional and cannot close an AC.
- [x] AC-EVIDENCE-3: Lifecycle is deterministically one of `provisional`, `verified-at-commit`, `stale`, or `superseded`.
- [x] AC-EVIDENCE-4: Only current passed `verified-at-commit` evidence satisfies an AC.
- [x] AC-EVIDENCE-5: `claim_ref` is limited to 160 characters, available in drill-down, and absent from compact task-contract output.
- [x] AC-EVIDENCE-6: High-risk invariants require distinct, correctly scoped review evidence.
- [x] AC-EVIDENCE-7: Criteria marked `independent_review=required` reject self-review and unrelated review scope.
- [x] AC-EVIDENCE-8: Compliance emits stable warning codes for all six specified weak-evidence patterns.
- [x] AC-EVIDENCE-9: Warning analysis is deterministic and bounded, with no LLM, logs, diffs, dirty path list, or generated prose.
- [x] AC-EVIDENCE-10: Reviewer findings persist as warning/blocking violations and resolve without history deletion.
- [x] AC-EVIDENCE-11: Every unresolved blocking violation gates closure, including under soft-deleted invariants.
- [x] AC-EVIDENCE-12: `get_task_contract` stays within 500 tokens and exposes counts/status only; details remain in drill-down.
- [x] Migration upgrades and downgrades cleanly and documents sequencing around T15's reserved `0008`.
- [x] Focused pytest, mypy, ruff, `git diff --check`, and `just check` pass.

## Verification

```bash
cd server && uv run pytest tests/test_evidence_quality.py tests/test_requirement_evidence.py tests/test_requirement_compliance.py tests/test_task_contract.py
cd server && uv run mypy
cd server && uv run ruff check src tests
just check
git diff --check
```

## Handoff

Status: repaired and validated, intentionally uncommitted on `task/T19-evidence-quality`.

### Delivered

- `source_commit` now resolves through Git to a commit object. Valid abbreviations expand to 40 characters; nonexistent hashes and blob/tree objects fail closed.
- `file_ref` and `test_ref` are normalized and checked at the claimed commit with bounded Git subprocesses. Only blobs verify; directories/trees and missing paths remain unverified and produce `missing-file-test-ref`. Fabricated refs cannot suppress security warnings.
- Evidence persists two clearly named recording states (`provisional`, `verified-at-commit`) and returns four effective lifecycle states (`provisional`, `verified-at-commit`, `stale`, `superseded`). Revision/provenance staleness has explicit precedence over supersession and is tested in exact row order.
- `claim_ref` remains descriptive and bounded to 160 characters. Authorization-sensitive `review_ref` is separately persisted, exposed through MCP/service responses, and restricted to `criterion:<uuid>` or `invariant:<uuid>`.
- Six stable warning codes have deterministic semantics. `missing-commit-ref` and `dirty-no-fingerprint` explicitly diagnose legacy/seeded rows because public recording rejects those states. Collision and normalized reuse checks inspect only current `verified-at-commit` rows; normalized reuse warns above the named threshold of three criteria.
- Security generic-command detection safely tokenizes without shell execution, unwraps supported `sh -c` and `uv run` wrappers, accepts project-wide options, and distinguishes scoped security test targets.
- Compact `get_task_contract` renders only lifecycle counts, warning/violation counts, validation, and review status; claim details remain in drill-down and output remains within 500 tokens.
- Unresolved blocking violations still gate closure when their invariant is soft-deleted. Project, requirement, and criterion isolation remains enforced.
- Migration `0019_evidence_quality` conservatively defaults preexisting evidence to provisional/unverified, adds DB constraints including canonical UUID-shaped `review_ref`, rejects malformed direct SQL values, downgrades cleanly, and is the sole Alembic head in this worktree.

### Exact validation

- Focused pytest: `104 passed, 2 warnings` across T19, evidence, compliance, task-contract, and contract-authoring API tests.
- T19 focused file: `28 passed`.
- Migration plus direct PostgreSQL constraint tests: `2 passed`; `uv run alembic heads` returned only `0019_evidence_quality (head)`.
- `uv run mypy`: success, 89 source files.
- `uv run ruff check src tests`: passed.
- `uv run ruff format --check src tests`: 89 files already formatted.
- `just check`: passed; server `256 passed, 1 skipped, 2 warnings`; frontend `68 passed`; ESLint, TypeScript, Vite build, and both Compose validations passed.
- `git diff --check`: passed.

### Risks and sequencing

- `0019_evidence_quality` currently points to `0007_requirement_evidence`. Integration must update its `down_revision` if T15-T18 add migrations first.
- Existing integrations that used descriptive `claim_ref` as review authorization must send typed `review_ref` instead.
- Existing callers recording against dirty worktrees must supply the exact server-compatible fingerprint.
- The two warnings are existing Starlette/httpx deprecations. No new dependencies. No commit created.
