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

- [ ] Verified requirement returns a compact success verdict with no repeated prose
- [ ] Failed requirement returns only actionable exceptions and drill-down IDs
- [ ] Multi-requirement review remains token-bounded and deterministic
- [ ] HTTP and MCP return equivalent compliance state
- [ ] Dashboard distinguishes requirement status from verification state
- [ ] Stale validation and blocking violations are visually prominent without literal style values
- [ ] Existing projects with no criteria render an explicit `not configured` state, not a false failure
- [ ] Agent workflow documentation includes the close-gate sequence and examples
- [ ] Every acceptance item has server or web regression coverage
- [ ] `just check` passes
- [ ] Handoff includes API payloads, UI screenshots/manual evidence, and remaining limitations

## Verification

```bash
cd server && uv run pytest -k 'compliance or requirement'
cd web && npm run test -- --run
just check
```
