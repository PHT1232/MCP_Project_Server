# T09 — Integration & hardening

**Branch:** `task/T09-integration`  ·  **Depends on:** all of Phase 1

## Goal
Prove the whole system meets the spec end to end and is fit to run.

## In scope
- Project-wide acceptance coverage for `AC1`–`AC27`, including explicit manual evidence where an automated test cannot reproduce an agent-orientation or physical-tailnet experiment.
- Runnable performance checks for NFR1, NFR2, NFR9, and NFR10.
- Security regression checks for NFR5/NFR14, path traversal, SQL-bound input, subprocess safety, and tracked secrets.
- Verified architecture, configuration, MCP, HTTP API, and deployment documentation.
- Final roadmap and release-readiness status.

## Key requirements
All ACs, NFR1, NFR2, NFR9, NFR10, NFR14.

## Acceptance checklist
- [x] Every `AC1`–`AC27` is indexed in `reviews/coverage.md` with automated or explicit manual evidence
- [x] Perf checks pass and are runnable via `just perf`
- [x] Security review clean or findings triaged; runnable via `just security`
- [x] Docs complete and verified against the code
- [x] `just check` green
- [x] Handoff / release notes written

## Handoff

### Added release gates

- `server/tests/test_performance.py` measures a representative warm briefing (NFR1), configured briefing budget (NFR2), one-file incremental reindex (NFR9), and a generated 100,000-LOC full index (NFR10).
- `server/tests/test_security.py` covers lexical/absolute/symlink traversal, source containment, default secret exclusions, SQL-injection-shaped values and project isolation, and shell-free git subprocess arguments (FR19, NFR5).
- `scripts/check-secrets.sh` rejects tracked local env/credential files and likely live AWS/private-key/OpenAI/Tailscale secrets while allowing documented placeholders.
- `just perf`, `just security`, and `just accept T09` make the release checks reproducible.

### Documentation

- `docs/architecture.md`: runtime, persistence, indexing/retrieval, source/code-map, network, and external-provider boundaries.
- `docs/configuration.md`: process, Compose, frontend, and per-project settings with defaults and privacy notes.
- `docs/mcp-reference.md`: registered MCP tools and resources.
- `docs/http-api.md`: frontend HTTP routes and response/error conventions.
- `README.md` and `docs/deploy.md`: corrected development, bind, Compose environment, image, and Tailscale Serve guidance.

### Acceptance evidence

`reviews/coverage.md` maps all ACs to tests and manual checks. AC2 and AC7 are controlled agent experiments and AC26 requires a second physical tailnet device; these are documented manual release checks because this worktree cannot honestly automate or reproduce them. AC25's real Compose smoke and T07's live indexed-repository exercise are retained as prior reviewer/live evidence.

### Security disposition

- No user-controlled SQL interpolation found; adversarial query/project/glob inputs remain bound and project-isolated.
- Repository/source paths reject lexical, absolute, home-relative, and symlink escapes.
- Git subprocesses use argument vectors without a shell.
- Default direct HTTP binding is loopback. The product Compose process binds `0.0.0.0` only inside its container and publishes exclusively on host `127.0.0.1`; Tailscale mode accepts only `100.64.0.0/10`. This intentional container exception is documented and covered by deployment tests.
- External embedding and summarization providers may receive project content only when explicitly configured; documentation now states this privacy boundary.

### Measured results

Initial focused run on this machine:

- NFR1 briefing p95: 3.4 ms (`<200 ms`).
- NFR2 briefing: 577 estimated tokens with a 600-token configured budget.
- NFR9 incremental reindex: 0.174 s (`<5 s`).
- NFR10 full index: 100,000 LOC, 100 files, 1,400 chunks in 4.051 s (`<180 s`).
- Security suite: 10 passed; tracked-secret scan passed.

Final `just accept T09` passed: performance 4/4, security 10/10 plus secret scan, server 116 passed / 1 skipped, web 47 passed, production build and Compose lint green.

### New dependencies

None.

### Manual release checks

1. AC2: give a fresh agent only `get_project_briefing` for a fixed unfamiliar task; verify it selects the relevant files without unrelated reads.
2. AC7: repeat the fixed orientation task without PCS and compare recorded input tokens; the PCS-assisted run must use fewer orientation tokens.
3. AC26: from a second tailnet device, verify frontend and `/mcp` are reachable by tailnet name; from a non-tailnet LAN device verify they are unreachable. With Tailscale off, verify host loopback works and LAN access fails.
