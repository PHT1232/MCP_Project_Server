# T14 — Requirement contract authoring API

**Branch:** `task/T14-contract-authoring-api` · **Depends on:** T13 · **Blocks:** T15 and all verified-compliance workflows

## Goal

Let agents create, update, and soft-delete normalized requirement invariants and acceptance criteria through audited MCP tools and equivalent HTTP endpoints, so requirements can move from legacy `not-configured` to enforceable verified compliance.

## Owned files/modules

- `server/src/pcs/mcp/contract_tools.py`
- `server/src/pcs/web_api/requirements_routes.py`
- `server/src/pcs/mcp/server.py` only if registration changes are required
- New focused adapter tests, preferably `server/tests/test_contract_authoring_api.py`
- `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/client.test.ts` only if typed HTTP clients are included
- `docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`
- `AGENTS.md` for the mandatory contract-authoring workflow

Do not change contract tables/migrations or weaken service validation. `pcs.requirements.contracts` remains the single business-logic implementation.

## Invariants

- `INV-AUTHOR-1`: Every mutation delegates to `contracts.create_*`, `update_*`, or `delete_*`; adapters do not duplicate validation or write DB rows directly.
- `INV-AUTHOR-2`: Caller identity from MCP/HTTP is always recorded as author and immutable revision history is created by the service.
- `INV-AUTHOR-3`: Project isolation, requirement-section validation, key uniqueness, enum validation, and statement bounds cannot be bypassed at an adapter.
- `INV-AUTHOR-4`: Updates are merge updates. Omitted fields retain values; explicit invalid values fail. No accidental clearing through transport defaults.
- `INV-AUTHOR-5`: Deletes are soft deletes and preserve revision history. Deleting an invariant applies existing criterion cascade semantics.
- `INV-AUTHOR-6`: Reads and writes return stable IDs required by evidence and compliance tools.
- `INV-AUTHOR-7`: Every call emits a structured audit result without logging full contract prose.
- `INV-AUTHOR-8`: HTTP and MCP mutations produce equivalent stored state; no UI editor is required in this task.

## MCP tools

- `create_requirement_invariant(project, requirement_id, statement, kind, risk, key?, sort_order?)`
- `update_requirement_invariant(project, invariant_id, statement?, kind?, risk?, key?, sort_order?)`
- `delete_requirement_invariant(project, invariant_id)`
- `create_acceptance_criterion(project, invariant_id, statement, evidence_kind, key?, required=true, independent_review="not-required", sort_order?)`
- `update_acceptance_criterion(project, criterion_id, statement?, evidence_kind?, required?, independent_review?, key?, sort_order?)`
- `delete_acceptance_criterion(project, criterion_id)`

Names must remain explicit and avoid collision with context-entry CRUD. Return typed view dictionaries including IDs.

## HTTP routes

Add equivalent create/update/delete routes below `/api/projects/{project}/requirements/...`. Use `POST` for create, `PATCH` for merge update, and `DELETE` for soft delete. Existing contract/evidence/compliance reads remain compatible.

## Acceptance checklist

- [x] Agent can create an invariant and criterion, then `get_requirement_contract` returns both stable IDs — `test_mcp_create_returns_stable_ids_in_contract`
- [x] Create/update/delete through MCP creates immutable revisions with the MCP caller as author — `test_mcp_mutations_record_caller_as_revision_author`
- [x] Equivalent HTTP mutations create the same stored state and revisions with HTTP caller identity — `test_http_mutations_match_mcp_stored_state`
- [x] Partial updates preserve omitted fields and reject empty mutation payloads — `test_partial_update_preserves_omitted_fields_and_rejects_empty`
- [x] Duplicate keys, invalid enum values, oversized/empty statements, negative sort order, wrong-section IDs, and cross-project IDs return actionable errors — `test_validation_isolation_and_wrong_section_errors`
- [x] Soft-deleted records disappear from active contract reads and remain in revision history — `test_soft_delete_hides_from_reads_and_keeps_history`
- [x] Deleting an invariant preserves existing criterion cascade semantics — same test plus `test_http_criterion_delete_matches_mcp`
- [x] A newly configured required criterion changes compliance from `not-configured` to failed/missing until evidence exists — `test_legacy_requirement_to_verified_close_gate`
- [x] After valid evidence and required independent review, compliance becomes verified and close gate allows `done` — same test
- [x] Audit logs contain tool/project/caller/outcome but not full statements — `test_audit_logs_omit_contract_prose`
- [x] MCP explicit JSON `null` rejects the whole PATCH (including mixed null+valid); `false` and `0` are accepted — `test_mcp_explicit_null_rejects_whole_payload_false_and_zero_ok`
- [x] HTTP POST/PATCH reject unknown fields and coerced JSON types; `sort_order: 0` and `required: false` succeed — `test_http_unknown_fields_and_strict_json_types`
- [x] Failure-path audit omits statements, keys, enum values, and caller payload — `test_audit_failure_omits_caller_payload` (includes stuffed `include` on GET/MCP reads)
- [x] Existing read/evidence/compliance APIs remain compatible — `test_existing_read_routes_remain_registered`, T13/T12 suites
- [x] MCP reference, HTTP reference, architecture, and `AGENTS.md` document the authoring-before-implementation workflow
- [x] Focused tests and `just check` pass — authoring/contracts/evidence 53 passed; `just check` 228 passed / 1 skipped server, 68 vitest
- [x] Independent security/correctness review has no open blocking violations — final adversarial re-review clean
- [x] Handoff includes exact payload examples, evidence IDs, compliance result, and limitations

## Required evidence

- Adapter tests covering every mutation, validation, isolation, revision history, audit privacy, and MCP/HTTP equivalence.
- End-to-end test: legacy requirement → create contract → missing gate → record evidence/review → verified gate.
- Independent review required for authorization boundaries, omission semantics, and delete/history behavior.

## Verification

```bash
cd server && uv run pytest tests/test_contract_authoring_api.py tests/test_requirement_contracts.py tests/test_requirement_evidence.py
just check
```

## Handoff

Status: **in review** on `task/T14-contract-authoring-api` (from `main` `1202091`). R-068 stays **in-progress** and **not-configured** on the live PCS process until the deployed server is restarted with T14 and its live contract/evidence is authored.

### Adapters (INV-AUTHOR-1)

MCP tools in `server/src/pcs/mcp/contract_tools.py` and HTTP routes in `server/src/pcs/web_api/requirements_routes.py` only call `contracts.create_*` / `update_*` / `delete_*`. No SQL and no copied enum/statement validation beyond transport presence, JSON types, unknown-field rejection (`UNKNOWN_FIELDS`), explicit-null rejection (`EXPLICIT_NULL`), and empty-merge rejection (`EMPTY_MUTATION`).

HTTP:

- `POST /api/projects/{project}/requirements/{requirement_id}/invariants` → 201
- `PATCH|DELETE /api/projects/{project}/requirements/invariants/{invariant_id}`
- `POST /api/projects/{project}/requirements/invariants/{invariant_id}/criteria` → 201
- `PATCH|DELETE /api/projects/{project}/requirements/criteria/{criterion_id}`

`X-PCS-Caller` (default `frontend`) is the HTTP author. MCP `caller(ctx)` is the MCP author. Empty `PATCH {}` is 400. Explicit JSON `null` on any present patch field rejects the whole payload (`EXPLICIT_NULL`); omitted keys are not sent to the service. HTTP POST/PATCH reject unknown fields (`UNKNOWN_FIELDS`) and non-JSON-native types (no `str(...)` coercion). `false` and `0` remain valid. HTTP GET + MCP contract reads/mutations in T14-owned files log `log_tool_call` outcomes as categories only (`ok` / `error: validation` / `error: not-found` / `error: project-not-found` / `error: failed`).

### Payload examples (from tests)

MCP create:

```json
{"project":"t14-project","requirement_id":"<req>","key":"INV-GATE","statement":"Close gate requires evidence and independent review.","kind":"behavior","risk":"high"}
{"project":"t14-project","invariant_id":"<inv>","key":"AC-GATE","statement":"Record passing tests and an independent review.","evidence_kind":"test","independent_review":"required"}
```

HTTP create:

```http
POST /api/projects/t14-project/requirements/<req>/invariants
X-PCS-Caller: http-reviewer
{"key":"INV-HTTP","statement":"HTTP and MCP share contracts.create_invariant.","kind":"behavior","risk":"low"}
```

Merge-update keeps omitted fields: `{"risk":"low"}` does not clear `statement`/`kind`/`key`/`sort_order`.

### End-to-end close gate (`test_legacy_requirement_to_verified_close_gate`)

1. Legacy requirement: `evaluate_close_gate` `configured=false` / `passed=true`; `review_requirement_compliance` `verdict=not-configured`.
2. After MCP create of `INV-GATE` + required `AC-GATE` with `independent_review=required`: gate `configured=true`, `passed=false`, `ac_verified=0/ac_total=1`, unmet names `AC-GATE`; compliance `verdict=failed`; `set_requirement_status(done)` raises `CloseGateError`.
3. After passing test evidence (`author=implementer`) and passing review evidence (`author=reviewer`) on the current commit: `evaluate_close_gate.passed=true`, `ac_verified=1/ac_total=1`; `review_requirement_compliance` `verdict=verified`, `exceptions=[]`; `done` allowed.

### Live R-068 (this process)

`evaluate_close_gate` on `a41e9d6d-6500-4f65-a99e-7194c35ba9e1`: `configured=false`, `validation=not-configured`.
`review_requirement_compliance`: `verdict=not-configured`. The running PCS server does not yet expose T14 authoring tools, so this requirement cannot be configured here until that process is restarted onto this branch.

### Review-fix cycle (four blocking findings)

1. MCP merge-update fields use Pydantic's `MISSING` sentinel so omitted values remain distinct from explicit JSON/MCP `null`. Transport type/null checks run inside `_run_logged`, therefore rejected calls still emit one safe audit event before `contracts.update_*` is reached. Mixed `statement=null` + `risk=low` does not apply `risk`; `required=false` and `sort_order=0` succeed.
2. HTTP `_reject_unknown` / `_merge_kwargs` allowlists reject typos and extras with `UNKNOWN_FIELDS` (message does not echo the extra names/values).
3. HTTP `_as_str` / `_as_bool` / `_as_int` require JSON string/bool/int; bool is not an int; no `str(...)` coercion.
4. MCP adapters log via `_run_logged`; HTTP adapters log via `_mutate`; both use `audit_outcome(exc)`. Failure-path tests prove logs do not contain statements, keys, enum values, or caller payload.

GET T13 handlers in this file and MCP `get_requirement_contract` / `get_task_contract` also use `audit_outcome` so a stuffed `include` query cannot land in the audit line (BL-01). `pcs.mcp.support.run_tool` is unchanged; other MCP modules still interpolate `error: {exc}`.

### Checks

- `uv run pytest tests/test_contract_authoring_api.py tests/test_requirement_contracts.py tests/test_requirement_evidence.py tests/test_requirement_compliance.py tests/test_task_contract.py` — 88 passed
- `uv run mypy` — clean (87 files)
- `just check` — 228 passed / 1 skipped server, 68 vitest, ruff/eslint/tsc/vite/compose green
- `git diff --check` — clean

Initial adversarial review found BL-01 (read-path `error: {exc}`); the fix routes T14 contract reads through categorized audit outcomes. Final independent re-review confirmed invalid MCP `include` and explicit-null mutation calls each emit one safe event with no caller payload leakage and reported **clean, no blocking findings**. `pcs.mcp.support.run_tool` is unchanged outside T14 scope. `tests/test_task_contract.py` also spies `pcs.mcp.contract_tools.log_tool_call` because T11 contract reads in this module no longer use `run_tool`.

### Files

- `server/src/pcs/mcp/contract_tools.py`
- `server/src/pcs/web_api/requirements_routes.py`
- `server/tests/test_contract_authoring_api.py`
- `server/tests/test_integration.py` — `EXPECTED_TOOLS` union
- `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/client.test.ts`
- `docs/mcp-reference.md`, `docs/http-api.md`, `docs/architecture.md`, `AGENTS.md`
- `ROADMAP.md` — T14 **in review**
- `tasks/T14-contract-authoring-api.md`

### Out of scope / limitations

No UI editor. No schema/migration changes. `prepare_task` ranking untouched. Live R-068 remains not-configured until T14 tools are deployed and a contract is authored with evidence plus independent review.

### New dependencies

None.
