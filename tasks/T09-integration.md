# T09 — Integration & hardening

**Branch:** `task/T09-integration`  ·  **Depends on:** all of Phase 1

> Stub — flesh out when Phase 1 nears done.

## Goal
Prove the whole system meets the spec end to end and is fit to run.

## In scope
- An E2E suite mapping **every** acceptance criterion `AC1`–`AC27` to a passing
  test (some already covered by component tasks — this closes the gaps and adds
  cross-component flows: AC2, AC7, cross-task AC14/AC14a paths).
- Perf checks: briefing < 200 ms (NFR1), briefing ≤ budget (NFR2), incremental
  reindex within seconds (NFR9), medium-repo full index in minutes (NFR10).
- Security pass: bind surface (NFR14), bound-params/SQL, path traversal on
  mounted repos (FR19/NFR5), secret handling, `.env` not tracked. Run
  `/security-review`.
- `docs/`: architecture overview, configuration reference, MCP tool/resource
  reference generated or hand-written, deploy guide. README.
- Final `ROADMAP.md` status pass.

## Key requirements
All ACs, NFR1, NFR2, NFR9, NFR10, NFR14.

## Acceptance checklist
- [ ] Every `AC1`–`AC27` has a green test, indexed in a coverage table
- [ ] Perf checks pass and are runnable via `just`
- [ ] `/security-review` clean or findings triaged
- [ ] Docs complete and verified against the code
- [ ] `just check` green
- [ ] Handoff / release notes written

## Handoff
_(fill in)_
