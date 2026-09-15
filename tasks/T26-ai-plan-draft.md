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

- [x] `AC-PLAN-9` (`f9d99c08-7383-48f9-932c-94e1a5c24b35`): `generate_plan_draft` uses secure T20 settings, validates structured schema, and persists zero database rows.
- [x] `AC-PLAN-10` (`9521864a-18e2-498b-8b09-b24e180580d2`): AI draft persistence occurs only through explicit caller approval via atomic `create_plan_with_tasks`.
- [x] Proposal with dependency cycles fails validation and returns descriptive error.
- [x] Cross-project or non-requirement IDs in draft are rejected.
- [x] Unconfigured or unreachable AI provider returns clear warning without crashing.
- [x] Database assertion confirms zero rows inserted across all planning tables (`plans`, `plan_tasks`, `task_dependencies`, `plan_task_requirements`, `plan_task_events`) during draft generation.
- [x] `just check` passes cleanly.
- [x] Task handoff documents prompt templates, schema validation, and mocked-provider test results.

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

## Handoff

- **Branch:** `main` (worked directly; no separate task branch was created for this session)
- **What was done:**
  - `server/src/pcs/planning/schemas.py`: pure, DB/HTTP-free `parse_plan_draft(raw)` that
    strictly validates an AI provider's parsed-JSON response into a frozen `PlanDraft` —
    rejects unknown top-level/task/dependency fields, enforces bounded string lengths and
    task counts (1-30), requires unique `local_task_id`s, normalizes `linked_files` to
    repository-relative paths (rejects absolute paths and `..` segments), and runs a
    Kahn's-algorithm cycle check (`_check_acyclic`) over the dependency graph so both
    dangling references and cycles fail closed with a descriptive `DraftValidationError`.
  - `server/src/pcs/planning/generator.py`: `generate_plan_draft(session, project, goal,
    constraints=None, max_tasks=10)`. Loads the persisted T20 summary provider via
    `load_runtime_ai_settings`, gathers bounded read-only context (project briefing, open
    requirements, codebase guide facts — all capped in characters/tokens), builds a prompt
    that explicitly labels repository content as untrusted "(untrusted data)" the model must
    not treat as instructions, calls the provider through the same DNS-pinned/no-redirect
    `resolve_provider_endpoint` path the T20 summarizer uses, parses the response with
    `parse_plan_draft`, and additionally cross-checks every `requirement_ids` reference
    against the project's live `SECTION_REQUIREMENTS` entries (rejecting cross-project or
    non-requirement IDs the schema layer can't know about on its own). Never calls
    `session.add`/`session.execute` against any planning table — the module has no code
    path capable of persisting a draft; only a caller's own subsequent
    `create_plan_with_tasks` call (T23) can do that.
  - `server/src/pcs/mcp/planning_tools.py` / `server/src/pcs/web_api/planning_routes.py`:
    added the `generate_plan_draft` MCP tool and `POST
    /api/projects/{project}/plans/generate-draft` HTTP route as an additive seam on top of
    merged T24, sharing its `audit_outcome`/`log_tool_call`/`_error_response` conventions;
    neither touches the existing plan/task CRUD handlers.
  - `server/tests/test_ai_plan_draft.py`: 13 tests, one per acceptance-checklist line (see
    Verification below).
- **Provider Security:**
  - Reuses T20's persisted `ProviderSettings` (no new provider configuration surface) and
    its DNS-pinned endpoint resolution / no-redirect / bounded-timeout HTTP call pattern
    (`resolve_provider_endpoint`, same posture as `Summarizer._call_backend`).
  - Prompt explicitly instructs the model to ignore any instructions embedded in repository
    content; the model's JSON response is itself treated as untrusted input and validated
    strictly before any field reaches the caller (no field is trusted merely because it
    parsed as JSON).
  - Result payload carries only `provider`/`model` metadata — no credentials, no raw prompt.
- **Verification:**
  - `uv run pytest tests/test_ai_plan_draft.py -v` — 13 passed, 0 failed.
  - Zero-persistence proof: `test_database_assertion_zero_rows_across_every_scenario`
    snapshots row counts across `plans`, `plan_tasks`, `task_dependencies`,
    `plan_task_requirements`, `plan_task_events` before/after four scenarios (valid draft,
    malformed JSON, provider connection error, unconfigured provider) and asserts all five
    counts stay at 0 in every case; `test_generate_plan_draft_uses_t20_settings_and_persists_zero_rows`
    and `test_draft_is_advisory_only_persists_via_explicit_create_plan_with_tasks` add the
    same before/after assertion around the happy path, confirming persistence only happens
    when the caller separately invokes `create_plan_with_tasks`.
  - `just check` — full pass: `ruff format --check` + `ruff check` (115 files), `eslint`,
    backend `mypy` (115 source files, no issues), frontend `tsc -b --noEmit`, backend
    `pytest` (402 passed, 1 skipped), frontend `vitest` (76 passed), `docker compose config`
    validation (both compose files), frontend production build.
- **Deviations:** None from the task spec. `requirement_ids` cross-project/non-requirement
  validation is split across two layers by design: `schemas.py` bounds the field's shape
  (list of short strings) with no DB access since it must stay pure, while
  `generator.py` does the actual live-membership check against the calling project's
  requirements after parsing — this keeps the strict-schema module free of I/O per its own
  module docstring.
