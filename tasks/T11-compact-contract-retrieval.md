# T11 — Compact contract retrieval

**Branch:** `task/T11-compact-contract-retrieval`  ·  **Depends on:** T10  ·  **Can run with:** T12  ·  **Blocks:** T13

## Goal

Expose relevant requirement contracts through progressive disclosure and add a hard-bounded contract/close-gate summary to `prepare_task` without reducing its code-context floor.

## Owned files/modules

- New `server/src/pcs/requirements/briefing.py`
- `server/src/pcs/mcp/index_tools.py`
- `server/src/pcs/mcp/tools.py` or a new requirement-contract registration module
- `server/src/pcs/mcp/server.py` only for registration
- `server/src/pcs/index/retrieval.py` only where `prepare_task` assembly requires it
- New focused tests for compact contract retrieval and task preparation
- `docs/mcp-reference.md`

Do not edit DB models/migrations, requirement status transitions, evidence writes, or frontend code.

## Requirements

- Add `get_requirement_contract(project, requirement_id, include)` for verbatim drill-down. `include` can select invariants, criteria, or both.
- Add `get_task_contract(project, task, requirement_ids?, max_tokens=500)` returning only relevant active contract statements and a compact close-gate summary.
- Extend `prepare_task` with a contract allocation capped at 500 estimated tokens and included inside the existing total budget.
- Preserve FR22a: curated context remains capped, code retains its floor when chunks exist, and unused contract budget spills to code.
- Deterministic selection order: blocking violations summary, forbidden paths, high-risk invariants, missing criteria, stale evidence. T12 data may be absent; represent it as `review: not-configured`, not an error.
- Never include raw evidence logs, full diffs, or unrelated requirements.
- Overflow becomes counts plus explicit drill-down tool names.
- Requirements are selected from explicit IDs first, then linked files/focus/retrieval relevance. Limit normal output to 1–3 requirements.

## Acceptance checklist

- [ ] Empty/unconfigured contracts add negligible output and preserve current `prepare_task` behavior
- [ ] Contract section is at most 500 estimated tokens under adversarial long input
- [ ] Total `prepare_task` response remains within its requested budget
- [ ] Existing FR22a code floor remains satisfied when code chunks exist
- [ ] Relevant forbidden/high-risk statements outrank low-risk prose deterministically
- [ ] Overflow reports omitted counts and drill-down pointers
- [ ] Full invariant/criterion detail is available only through explicit drill-down
- [ ] Responses contain no raw command output or diff bodies
- [ ] Every acceptance item has a regression test
- [ ] Focused tests and `just check` pass
- [ ] Handoff documents exact budget accounting and relevance rules

## Verification

```bash
cd server && uv run pytest -k 'task_contract or prepare_task'
just check
```
