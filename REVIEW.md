# REVIEW.md — how the plan owner reviews agent work

This is my (the reviewing session's) checklist. Agents: see [AGENTS.md](AGENTS.md).

## One-command review

```
scripts/review.sh TXX
```

It:
1. `git fetch` and locate the task branch `task/TXX-*`.
2. Prints `git diff --stat main...task/TXX-*` and the full diff to a pager-free file.
3. Runs `just check` against the branch (format, lint, mypy, pytest, eslint, tsc,
   vitest, builds).
4. Runs the task's acceptance tests (`just accept TXX` if defined, else the
   `tests/` paths named in the task file).
5. Prints the task's Acceptance checklist and its handoff section.

If `scripts/review.sh` doesn't exist yet (pre-T00), review manually:
`git diff main...task/TXX-*`, then `cd server && uv run ruff check . && uv run mypy . && uv run pytest`.

## Review rubric (in priority order)

1. **Requirement coverage** — does it actually implement the `FR`/`AC` IDs the
   task claims? Cross-check each Acceptance checklist item against a real test.
2. **Correctness** — logic bugs, error handling, async/await misuse, race
   conditions on concurrent writes (FR17/18), migration up/down correctness.
3. **Security** — bound params only (no SQL injection); path traversal on mounted
   repo paths (FR19, NFR5); bind surface stays localhost/tailnet only (NFR14);
   secrets not logged or committed; `.env` not tracked.
4. **Scope** — no edits outside the task's declared files; no weakened checks
   (`type: ignore`, `noqa`, `eslint-disable`, skipped tests, lowered thresholds).
5. **Tests** — every AC has a test that would fail without the change; tests are
   deterministic; DB tests use containers/fixtures, not a shared instance.
6. **Design fidelity (frontend tasks)** — computed styles resolve to `DESIGN.md`
   tokens, not literals; no violation of that file's "Don't" list; dark canvas is
   Fey Ink not `#000`; Calibre only; 99px/16px radii; ≤1 chromatic accent per
   unit (FR39a, NFR15, AC27).
7. **Simplification / altitude** — dead code, needless abstraction, copy-paste
   that should be shared, obvious perf issues (NFR1/2/9/10).

Also run `/code-review high` on the branch and fold its findings in.

## Findings

Write findings to `reviews/TXX.md` using [reviews/TEMPLATE.md](reviews/TEMPLATE.md):
- **blocker** — must fix before merge (wrong behavior, missing AC, security, scope
  breach, red checks).
- **should** — fix before merge unless there's a good reason.
- **nit** — optional; author's call.

Then either:
- **Changes requested** — set ROADMAP status, message the agent with
  `reviews/TXX.md`, let it fix on the same branch, re-review.
- **Approved** — merge the branch to `main` (`git merge --no-ff task/TXX-*`),
  set ROADMAP status to `merged`, delete the worktree/branch, unblock dependents.

## Merge order

Respect the dependency column in ROADMAP.md. T00 first and alone. Within Phase 1,
merge in dependency order (T01 before T02/T04; T03 before T04; T04/T03 before T05;
T01/T02 before T06; T05/T06 before T07). Rebase later branches on `main` after
each merge; re-run `just check` before the next merge.
