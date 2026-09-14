# T26 — Advisory AI plan draft generation

**Branch:** `task/T26-ai-plan-draft` · **Depends on:** T20, T24 · **Blocks:** T28, T29

## Goal

Provide an advisory, read-only AI plan draft generation service (`generate_plan_draft`) using persisted T20 provider settings, strictly validating structured proposals locally and creating zero database rows until explicit caller approval.

## Owned files/modules

- `server/src/pcs/planning/generator.py`
- `server/src/pcs/planning/schemas.py`
- AI draft additions (*sequenced shared seam* on merged T24):
  - `server/src/pcs/mcp/planning_tools.py` (`generate_plan_draft`)
  - `server/src/pcs/web_api/planning_routes.py` (`POST /api/projects/{project}/plans/generate-draft`)
- `server/tests/test_ai_plan_draft.py`
- `tasks/T26-ai-plan-draft.md`

*Sequenced Shared Integration Seam:* T26 builds upon merged T24. It appends the `generate_plan_draft` tool and HTTP route to `planning_tools.py` and `planning_routes.py` without modifying base planning handlers.

Do not touch frontend code, core storage models, or `prepare_task`.

## Non-goals

- Automatically creating plans or tasks in the database (persisting is owned by `create_plan_with_tasks`).
- Automatically claiming tasks or dispatching agent processes (D24).
- Introducing a secondary AI provider configuration or bypassing T20 DNS/URL pinning.
- Building the frontend draft review modal (owned by T28).

## Invariants

- `INV-PLAN-6` (`56ca7dc0-e3f0-4270-b1ce-48a915fb09b7`): AI plan draft generation is strictly read-only; invalid or cancelled drafts persist zero rows; plans are stored only via explicit approval through atomic create_plan_with_tasks.

## Requirements

- Expose `generate_plan_draft(project, goal, constraints=None, max_tasks=10)` in MCP and HTTP API (`POST /api/projects/{project}/plans/generate-draft`).
- Use persisted T20 summary provider settings and security controls (DNS pinning, hostname allowlist, no redirects).
- Provide bounded input context to provider: project briefing, open requirements, guide facts, and user goal. Treat repository content as untrusted input.
- Enforce strict JSON schema on provider output:
  - Plan title and goal.
  - Ordered task items: `local_task_id`, title, objective, acceptance criteria, linked files, requirement IDs.
  - Prerequisite dependency mapping using local task IDs.
  - Optional implementation notes.
- Validate the proposal locally:
  - Bounded string lengths and maximum task counts.
  - Unique local task IDs within proposal.
  - Dependencies form a valid directed acyclic graph (no cycles, no dangling references).
  - Referenced requirement IDs belong to active project context AND have `section == 'requirements'`.
  - Linked files are normalized relative paths within project root.
  - Reject unknown schema fields and fail closed on truncated or malformed responses.
- Enforce read-only semantics: `generate_plan_draft` must perform zero SQL write operations and create zero rows in `plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, or `plan_task_events`.
- Return provider and model metadata without credentials, plus explicit warnings if AI provider is not configured or unavailable.

## Acceptance checklist

- [ ] `AC-PLAN-9` (`f9d99c08-7383-48f9-932c-94e1a5c24b35`): `generate_plan_draft` uses secure T20 settings, validates structured schema, and persists zero database rows.
- [ ] `AC-PLAN-10` (`9521864a-18e2-498b-8b09-b24e180580d2`): AI draft persistence occurs only through explicit caller approval via atomic `create_plan_with_tasks`.
- [ ] Proposal with dependency cycles fails validation and returns descriptive error.
- [ ] Cross-project or non-requirement IDs in draft are rejected.
- [ ] Unconfigured or unreachable AI provider returns clear warning without crashing.
- [ ] Database assertion confirms zero rows inserted across all planning tables (`plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, `plan_task_events`) during draft generation.
- [ ] `just check` passes cleanly.
- [ ] Task handoff documents prompt templates, schema validation, and mocked-provider test results.

## Required evidence

- Unit and mocked-provider tests in `server/tests/test_ai_plan_draft.py`.
- Independent review required for `AC-PLAN-9` (Zero-persistence read-only proof).

## Verification

```bash
cd server && uv run pytest tests/test_ai_plan_draft.py -v
just check
```

## Handoff template

```markdown
## Handoff

- **Branch:** `task/T26-ai-plan-draft`
- **What was done:**
  - ...
- **Provider Security:**
  - Integrated T20 settings consumption
  - Local schema validation rules
- **Verification:**
  - `test_ai_plan_draft.py` results
  - Zero-persistence test verification
  - `just check` result
- **Deviations:** None
```
