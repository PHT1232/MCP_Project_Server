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

- [ ] `AC-PLAN-8` (`eabc07be-3c22-4227-ae97-9b63bc2ea3f4`): `prepare_task` with `task_id` produces bounded role-neutral prompt with dependency and contract state without secrets.
- [ ] Existing `prepare_task(task="...")` remains 100% backward compatible.
- [ ] Supplying both `task` and `task_id` or neither is rejected with descriptive validation error.
- [ ] Cross-project or non-existent `task_id` returns 404 / NotFoundError.
- [ ] Prompt instructs agent on AGENTS.md conventions, scope boundaries, and evidence recording.
- [ ] Prompt contains zero claim tokens, API secrets, or full diffs.
- [ ] Token budget limits are respected, and code floor is preserved when chunks exist.
- [ ] `just check` passes cleanly across server and web.
- [ ] Task handoff documents prompt format, token budgeting, and verification results.

## Required evidence

- Unit and regression tests in `server/tests/test_planned_task_handoff.py`.
- Independent review required for `AC-PLAN-8` (Prompt bounds and secret absence).

## Verification

```bash
cd server && uv run pytest tests/test_planned_task_handoff.py -v
just check
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T25-planned-task-handoff`
- **What was done:**
  - ...
- **Prompt Structure:**
  - Sections generated in role-neutral Markdown prompt
  - Token budget allocations and truncation order
- **Verification:**
  - `test_planned_task_handoff.py` results
  - `just check` result
- **Deviations:** None
```
