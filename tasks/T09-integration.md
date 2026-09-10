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
- [x] Every `AC1`–`AC27` is indexed in `reviews/coverage.md` with verified, partial, or manual-pending status
- [x] Perf checks pass and are runnable via `just perf`
- [x] Security review clean or findings triaged; runnable via `just security`
- [x] Docs complete and verified against the code
- [x] `just check` green
- [x] Handoff / release notes written

## Handoff

### Added release gates

- `server/tests/test_performance.py` measures a representative warm briefing (NFR1), configured briefing budget (NFR2), one-file incremental reindex (NFR9), and a generated 100,000-LOC full index (NFR10).
- `server/tests/test_security.py` covers lexical/absolute/symlink traversal, source containment, default secret exclusions, SQL-injection-shaped values and project isolation, and shell-free git subprocess arguments (FR19, NFR5).
- `scripts/check-secrets.sh` rejects tracked local env/credential files and selected high-confidence AWS/private-key/OpenAI/Tailscale secret formats while allowing documented placeholders.
- `just perf`, `just security`, and `just accept T09` make the release checks reproducible.

### Documentation

- `docs/architecture.md`: runtime, persistence, indexing/retrieval, source/code-map, network, and external-provider boundaries.
- `docs/configuration.md`: process, Compose, frontend, and per-project settings with defaults and privacy notes.
- `docs/mcp-reference.md`: registered MCP tools and resources.
- `docs/http-api.md`: frontend HTTP routes and response/error conventions.
- `README.md` and `docs/deploy.md`: corrected development, bind, Compose environment, image, and Tailscale Serve guidance.

### Acceptance evidence

`reviews/coverage.md` maps all ACs to automated tests, prior live checks, and pending manual protocols. AC2 and AC7 require controlled agent experiments; AC6/AC15 require full process lifecycle checks; AC26 requires a second physical tailnet device; frontend-cross-interface criteria remain partial where component and service tests do not form a browser-level E2E. AC25's real Compose smoke and T07's live indexed-repository exercise are retained as prior reviewer/live evidence.

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

Final post-review `just accept T09` passed: server 116 passed / 1 skipped because no real SCIP binary is installed (fallback mode is tested), web 47 passed, secret scan, production build, and Compose lint green.

### New dependencies

None.

### Manual release checks

1. AC2/AC7: pin a repository revision, unfamiliar task sentence, model/version, agent settings, and allowed tools. Run at least three fresh-session pairs with treatment order alternated. In the PCS run, provide the task sentence and access to `get_project_briefing`; in baseline, provide the task sentence and normal repository-read tools. Record tool/file-read logs and API-reported input tokens through the first implementation edit. AC2 passes when PCS runs identify the relevant files with no unrelated reads; AC7 passes when median PCS orientation tokens are lower than baseline.
2. AC6: write context through HTTP/MCP, terminate and recreate the server process against the same PostgreSQL instance, then fetch and compare the briefing.
3. AC15: drop `code_index`, restart the server against preserved curated tables, trigger/wait for rebuild, then verify search works and curated context is unchanged.
4. AC26: from a second tailnet device, verify frontend and `/mcp` are reachable by tailnet name; from a non-tailnet LAN device verify they are unreachable. With Tailscale off, verify host loopback works and LAN access fails.
