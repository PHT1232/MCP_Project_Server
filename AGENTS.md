# AGENTS.md — how to work on this repo

Read this fully before writing code. Then read your task file in [tasks/](tasks/).

## What this project is

An MCP server that gives AI agents a shared, compact project briefing, plus a
full-codebase search/RAG index and a web frontend with a code map. Full spec:
[REQUIREMENTS.md](REQUIREMENTS.md). Frontend style: [DESIGN.md](DESIGN.md)
(normative). Plan: [ROADMAP.md](ROADMAP.md).

## Golden rules

1. **Stay in your task's scope.** Your task file lists the files/modules you own.
   Do not edit another task's modules, shared config, or `main`-level docs unless
   your task says so. If you need a change outside your scope, note it in your
   handoff instead of making it.
2. **Do not merge to `main`.** Work on your branch. I review, then merge.
3. **Do not weaken checks.** `just check` must pass. Don't add `# type: ignore`,
   `# noqa`, `eslint-disable`, `xfail`, or lower a threshold to get green — fix
   the cause or raise it in your handoff.
4. **Requirements are the contract.** Cite `FR`/`NFR`/`AC` IDs in code comments
   and your handoff where you implement them. If a requirement seems wrong,
   flag it — don't silently deviate.
5. **Tests are part of the task, not optional.** Every AC your task lists needs a
   test that would fail without your change.
6. **New dependency = call it out.** Add it, and list it (with why) in your
   handoff. Prefer the stack already chosen in ROADMAP.md.

## Workflow

1. Your task branch already exists (`task/TXX-slug`) and you are in a git
   worktree for it. Confirm with `git status` / `git branch --show-current`.
2. Implement. Commit in small, atomic steps with clear messages
   (`T03: add tree-sitter chunker for python`).
3. Keep your task file's **Acceptance checklist** updated (`- [x]`) as you go.
4. Before handing off: run `just check` (repo root) — it must be fully green.
5. Write your handoff as the final section of your task file (see template at the
   bottom of the file). Commit it.
6. Report back: branch name, what's done, what's not, any deviations, any
   cross-task needs, and the `just check` result.

## Commit messages

```
TXX: <imperative summary>

<what and why, requirement IDs touched>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

## Server conventions (Python)

- Python **3.12+**, managed with **uv** (`uv sync`, `uv run ...`). Never invoke
  a global `pip`/`python` — always `uv run`.
- **ruff** for format + lint (config in `pyproject.toml`); **mypy --strict**
  clean; **pytest** for tests.
- Full type hints. Public functions/classes get a short docstring stating intent
  and citing requirement IDs where relevant.
- Async where it touches I/O (DB, subprocesses, HTTP). SQLAlchemy 2.0 async
  session; no raw string-interpolated SQL — bound params only.
- All DB schema changes go through an **Alembic** migration in the same commit.
- Config via `pcs.config` (pydantic-settings), read from env / mounted file —
  never hard-coded paths, ports, or secrets.
- MCP tools/resources are registered in `pcs.mcp`; a tool's implementation lives
  in its component module and is unit-tested without the MCP layer.
- Log via structured logging (`pcs` logger). Every tool call logs project id,
  caller, outcome (NFR6).

## Requirement contract authoring

Before implementing a configured requirement, author invariants and acceptance
criteria through `create_requirement_invariant` / `create_acceptance_criterion`
(or the matching HTTP routes). Do not write contract rows in SQL or duplicate
`pcs.requirements.contracts` validation. Merge-updates omit unchanged fields;
empty payloads are rejected. Soft-delete keeps history.

Then record compact evidence, call `review_requirement_compliance`, and only
set status `done` after `evaluate_close_gate` passes. A `not-configured`
requirement is legacy state, not verified compliance. See
[docs/mcp-reference.md](docs/mcp-reference.md) and [docs/http-api.md](docs/http-api.md).

## Explaining the codebase (feature docs)

If you're asked to explain this codebase's features — what each one does, the
files that implement it, its input/output — don't write the answer as a
standalone `.md` file. Write it into pcs's `features` section instead, via
`add_feature`/`update_feature` (`section='features'` under the hood), so the
pcs-control-panel "Features" tab stays the single source of truth instead of
a summary that immediately goes stale and duplicates what the tool already
tracks:

```
add_feature(
  project="...",
  headline="Code search (search_code)",
  detail="Input: a text/symbol/glob query plus optional scope. Output: ranked
          hits (path, line range, snippet) plus total_matches/truncated.",
  linked_files=["server/src/pcs/index/search.py", "server/src/pcs/index/hybrid.py"],
  related_entry_id="<id of the requirements-section entry it satisfies, if any>",
)
```

`related_entry_id` — not `req_key` — is the link to the requirement; `req_key`
is reserved for the requirements section's own server-assigned `R-NNN`
identity. See [docs/mcp-reference.md](docs/mcp-reference.md)'s Features
section for the full tool reference.

## Frontend conventions (TypeScript)

- React + Vite + TS, **strict** tsconfig, no `any` (use `unknown` + narrowing).
- **eslint** clean, **tsc --noEmit** clean, **vitest** for logic, `vite build`
  succeeds.
- **Styling comes only from `DESIGN.md` tokens** (Tailwind v4 `@theme` from its
  Quick Start, or the CSS custom properties). No literal hex, px, or shadow
  values in components. See `DESIGN.md` "Do's and Don'ts" — it is normative
  (FR39a, NFR15).
- Server calls go through a typed API client + TanStack Query; no `fetch` in
  components.
- Components are presentational + testable; data-fetching in hooks.

## Definition of Done (every task)

- [ ] All items in the task's Acceptance checklist are `- [x]` and backed by tests
- [ ] `just check` green at repo root (server + frontend)
- [ ] New DB schema has an Alembic migration; `just migrate` runs clean from empty
- [ ] Requirement IDs cited where implemented
- [ ] Handoff section written in the task file
- [ ] No changes outside the task's declared scope
- [ ] Branch pushed / worktree left in a reviewable state; ROADMAP status set to
      `in review`
