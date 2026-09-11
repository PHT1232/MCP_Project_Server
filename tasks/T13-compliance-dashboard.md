# T13 — Compliance review API and dashboard

**Branch:** `task/T13-compliance-dashboard`  ·  **Depends on:** T11, T12  ·  **Blocks:** release

## Goal

Give agents and humans one compact pre-close compliance view showing criterion coverage, stale validation, independent-review state, and blocking violations, with drill-down on demand.

## Owned files/modules

- New `server/src/pcs/requirements/compliance.py`
- New requirement compliance MCP registration module
- New/extended `server/src/pcs/web_api/requirements_routes.py`
- `server/src/pcs/mcp/server.py` only for route/tool registration
- `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/api/queryKeys.ts`
- New `web/src/hooks/useRequirementCompliance.ts`
- Requirements view/components and focused tests
- `docs/http-api.md`, `docs/mcp-reference.md`, `docs/architecture.md`
- `reviews/coverage.md` entries for this phase

Do not introduce LLM compliance judgement, execute tests, parse CI logs, or mutate source files.

## Requirements

- Add `review_requirement_compliance(project, requirement_ids)` returning compact deterministic verdicts: verified count, missing criteria, stale evidence, review state, and blocking violations.
- Success output is exception-only and short. Failure output gives criterion/invariant IDs plus concise file references; details require explicit drill-down.
- Add typed HTTP reads for requirement contract, evidence summary, and compliance verdict. Existing requirement endpoints remain compatible.
- Dashboard requirement rows show implementation status separately from verification state.
- Requirement detail shows `AC verified/total`, validation `current/stale/missing`, independent review, and open violations.
- UI never displays raw logs/diffs and follows `DESIGN.md` tokens.
- Add an explicit pre-close agent workflow to docs: prepare task, inspect missing ACs, record evidence, run compliance review, then request `done`.

## Acceptance checklist

- [x] Verified requirement returns a compact success verdict with no repeated prose
- [x] Failed requirement returns only actionable exceptions and drill-down IDs
- [x] Multi-requirement review remains token-bounded and deterministic
- [x] HTTP and MCP return equivalent compliance state
- [x] Dashboard distinguishes requirement status from verification state
- [x] Stale validation and blocking violations are visually prominent without literal style values
- [x] Existing projects with no criteria render an explicit `not configured` state, not a false failure
- [x] Agent workflow documentation includes the close-gate sequence and examples
- [x] Every acceptance item has server or web regression coverage
- [x] `just check` passes
- [x] Handoff includes API payloads, UI screenshots/manual evidence, and remaining limitations

## Verification

```bash
cd server && uv run pytest -k 'compliance or requirement'
cd web && npm run test -- --run
just check
```

## Handoff

### Delivered

- Deterministic `review_requirement_compliance(project, requirement_ids)` MCP tool and equivalent `GET /api/projects/{project}/requirements/compliance` route. Requests are sorted/deduplicated, capped at 25 requirements, and capped at 8 actionable exceptions per requirement with accurate omission counts.
- Typed contract and bounded evidence HTTP drill-down. Evidence is latest-first (20 rows); open blocking violations are prioritized before warnings (20 rows). Raw logs/diffs, authors, and timestamps are not returned or rendered.
- Requirements dashboard separates implementation status from verification, shows AC verified/total, current/stale/missing, independent review, blocking/warning violations, explicit `not configured`, and partial-batch failures.
- Documented pre-close flow: prepare task, inspect contract, record evidence, review compliance, then request `done`.

### Payload examples

Verified rows remain exception-only:

```json
{"requirement_id":"req-1","req_key":"R-001","status":"in-progress","configured":true,"verdict":"verified","ac_verified":2,"ac_total":2,"validation":"ok","review":"passed","exceptions":[],"omitted_exceptions":0}
```

Failure rows expose IDs and concise references rather than contract prose:

```json
{"kind":"blocking","violation_id":"violation-id","invariant_id":"invariant-id","invariant_key":"INV-1","file_refs":["src/app.py:42"]}
```

### Verification evidence

- Server requirement/compliance suite passed, including HTTP/MCP equality, project isolation, deterministic bounds, >8 exception accounting, and blocking-first violation ordering.
- Frontend lint, strict typecheck, 66 Vitest tests, and Vite production build passed. Component tests provide manual-equivalent UI evidence for all dashboard states, including hostile raw-log/diff content remaining absent.
- Independent diff review found two blocking and two coverage/ordering issues; all were fixed with regressions before handoff.
- No browser screenshot was captured because no browser automation or screenshot tooling is configured in this worktree. Rendered states are covered through Testing Library DOM assertions.

### Limitations

- Dashboard batches more than 25 requirements into separate bounded requests; a failed batch is shown as unavailable while successful batches remain usable.
- Drill-down intentionally exposes IDs, metadata, and concise file references only. Full contract prose remains available through the explicit API/MCP contract read, not the compliance UI.
- Compliance is deterministic stored-state evaluation. It does not execute tests, parse CI logs, make LLM judgments, or mutate source.
- T13 reuses T12 repository-state and freshness primitives but reconstructs identity-bearing criterion exceptions; future close-gate semantic changes must update both paths together.

### Dependencies and deviations

- No new dependencies.
- No contract deviations.
