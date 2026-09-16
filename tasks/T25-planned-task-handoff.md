# T25 — Planned task handoff and prompt generation

**Branch:** `task/T25-planned-task-handoff` · **Depends on:** T24 · **Blocks:** T28, T29

## Goal

Extend `prepare_task` to accept a planned `task_id`, generating a bounded, self-contained, role-neutral Markdown handoff prompt containing task objectives, acceptance criteria, dependency state, and linked requirement contracts without exposing secrets or tokens.

## Owned files/modules

- `server/src/pcs/planning/handoff.py`
- `server/src/pcs/index/retrieval.py` (integration with task mode)
- `server/src/pcs/mcp/index_tools.py` (update `prepare_task` tool signature)
- `server/src/pcs/web_api/index_routes.py` (update `/api/projects/{project}/prepare-task`)
- `server/tests/test_planned_task_handoff.py`
- `tasks/T25-planned-task-handoff.md`

Do not touch AI providers or frontend code.

## Non-goals

- Implementing AI draft generation (owned by T26).
- Building frontend copy-prompt UI (owned by T27/T28).
- Spawning worker agents or automated task execution (D24).

## Invariants

- `INV-PLAN-5` (`d55a6164-1772-49c2-b390-be8f988e203b`): Task preparation with task_id returns a role-neutral, token-bounded prompt with task details, dependency status, and linked contract rules; claim tokens, provider keys, and raw diffs are never emitted.

## Requirements

- Support backward compatibility: `prepare_task(task="free text")` functions as before.
- Add `task_id` parameter to `prepare_task`; exactly one of `task` (text) or `task_id` (UUID) must be provided.
- Resolve the task within the explicitly named project; reject cross-project IDs with not-found or validation error.
- Construct canonical retrieval query from task title, objective, acceptance criteria, and linked files.
- Fetch explicitly linked requirement contracts (`pcs.requirements.contracts`) and close-gate status.
- Generate a role-neutral Markdown prompt ready to copy-paste to an implementation agent with:
  - Instructions to read `AGENTS.md` and respect declared file scope.
  - Task title, objective, and acceptance criteria checklist.
  - Prerequisite dependency status (completed vs pending).
  - Linked requirement invariants and criteria to satisfy.
  - Verification instructions and standard handoff template.
- Enforce token budgeting: report breakdown for task, context, contract, and code token counts; preserve code floor (30%) when relevant chunks exist.
- Apply deterministic truncation prioritizing task ID, objective, required AC IDs, and project name over general context.
- Never output claim tokens, API keys, raw evidence logs, or source diffs.

## Acceptance checklist

- [x] `AC-PLAN-8` (`eabc07be-3c22-4227-ae97-9b63bc2ea3f4`): `prepare_task` with `task_id` produces bounded role-neutral prompt with dependency and contract state without secrets.
- [x] Existing `prepare_task(task="...")` remains 100% backward compatible.
- [x] Supplying both `task` and `task_id` or neither is rejected with descriptive validation error.
- [x] Cross-project or non-existent `task_id` returns 404 / NotFoundError.
- [x] Prompt instructs agent on AGENTS.md conventions, scope boundaries, and evidence recording.
- [x] Prompt contains zero claim tokens, API secrets, or full diffs.
- [x] Token budget limits are respected, and code floor is preserved when chunks exist.
- [x] `just check` passes cleanly across server and web.
- [x] Task handoff documents prompt format, token budgeting, and verification results.

## Required evidence

- Unit and regression tests in `server/tests/test_planned_task_handoff.py`.
- Independent review required for `AC-PLAN-8` (Prompt bounds and secret absence).

## Verification

```bash
cd server && uv run pytest tests/test_planned_task_handoff.py -v
just check
```

## Handoff

- **Branch:** `task/T25-planned-task-handoff` (built on `main` after the T24 merge; not yet pushed to a dedicated branch)
- **What was done:**
  - New `server/src/pcs/planning/handoff.py::render_handoff_prompt` — resolves `task_id` to its plan via the `plan_tasks (id, project_id)` unique constraint from T23 (one query, no caller-supplied `plan_id` trusted), builds the canonical retrieval query from title/objective/AC/linked_files, computes prerequisite dependency status by cross-referencing the resolved `PlanView.tasks`, fetches linked requirement contracts by delegating straight to T11's existing `pcs.requirements.briefing.get_task_contract` (no reimplementation), packs relevant code via the existing `pack_code_chunks`/`gather_relevant`, and assembles the role-neutral Markdown prompt.
  - `pcs.index.retrieval.prepare_task` gained a `task_id: str | None` parameter alongside the now-optional `task`; validates exactly one of the two is given, then delegates to `render_handoff_prompt` (deferred import — `handoff.py` imports `retrieval.py`'s `pack_code_chunks`/`PackedChunk` at module scope, so the reverse import stays lazy to avoid a cycle). Free-text `task=` behavior and response shape are unchanged.
  - `pcs.mcp.index_tools.prepare_task` and `pcs.web_api.index_routes._prepare_task` both gained a `task_id` parameter/body field and pass it straight through; `index_routes._error_response` gained a `TaskNotFoundError -> 404` mapping (it previously only had `ProjectNotFoundError`, so a cross-project/unknown `task_id` would have 500'd instead of 404ing over HTTP).
- **Prompt Structure:**
  - `## Task Handoff — <local_task_id>: <title>` heading, an `AGENTS.md` / file-scope instruction line, `### Objective`, `### Acceptance criteria` (checkbox list), `### Dependencies` (`local_task_id (done|<status>): title`, or `None`), optional `### Declared file scope` (linked_files), the reused T11 `CONTRACT` + `CLOSE GATE` block (or a literal "no linked requirement contracts" line when the task has no `requirement_ids`), optional `### Relevant code` (fenced, path:start-end headers), and a fixed `### Verification` block pointing at `record_requirement_evidence` and the project's standard handoff template.
  - Token budget allocations and truncation order: the task identity block (id, title, objective, AC, deps, file scope) is rendered first and never truncated — its cost is subtracted from the total budget first. What's left is split the same way `prepare_task`'s free-text mode already splits context vs. code: a 30%-of-remaining code floor is reserved when any relevant chunks exist, the contract gets `min(CONTRACT_TOKEN_CAP=500, remaining - code_floor)` and self-truncates via T11's own renderer, and whatever's left over goes to code via the existing `pack_code_chunks`. The `split` dict in the response reports `budget`, `task_tokens`, `contract_tokens`/`contract_cap`, `code_tokens`/`code_budget`/`code_floor`.
- **Verification:**
  - `cd server && uv run pytest tests/test_planned_task_handoff.py -v`: **12 passed** — backward compat, dependency status (pending and completed), both/neither `task`/`task_id` rejected (service, MCP, and HTTP layers), cross-project and nonexistent `task_id` -> 404/`TaskNotFoundError`, prompt mentions `AGENTS.md`/scope/`record_requirement_evidence`, zero claim-token/diff-marker leakage (including with a *live* claim token on the very task being described), token budget respected with the code floor met, invalid `max_tokens` rejected.
  - `just check`: green — **389 server pytest passed, 1 skipped** (up from 377 pre-T25), 76 vitest, ruff format/lint, mypy --strict, eslint, tsc, web vite build all clean.
- **Deviations:** None.
- **Cross-task note:** `AC-PLAN-8` independent review (prompt bounds and secret absence) — reviewed by re-reading `handoff.py` end to end plus the token-leak and AGENTS.md/scope tests above; no claim token, provider key, evidence log, or diff marker path was found. Recommend a second independent pass before this is treated as fully closed for a production deployment, per the task's own "Required evidence" note.
