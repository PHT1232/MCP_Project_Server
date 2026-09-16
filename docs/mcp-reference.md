# MCP reference

Run `pcs stdio` for local stdio transport or `pcs http` for streamable HTTP at `/mcp`. Every project-specific call accepts an exact project name or ID. Missing or unknown projects return an error listing registered projects. Tool calls emit structured audit data containing tool, project, caller, and outcome (NFR6).

Arguments listed as `null` are optional. MCP framework context (`ctx`) is internal and omitted below.

## Project and reads

| Tool | Arguments and defaults | Result |
|---|---|---|
| `list_projects` | none | Project summaries. |
| `register_project` | `name`, `root_path`, `overview` | Project summary; indexes an existing root, starts its watcher, and initializes requirements sync. |
| `configure_project` | `project=null`, `expiry_policy=null`, `expiry_days=null`, `briefing_token_budget=null`, `prepare_task_token_budget=null`, `headline_max_chars=null`, `detail_max_chars=null` | Updated project summary. |
| `get_project_briefing` | `project=null`, `sections=null`, `max_tokens=null` | Compact Markdown briefing. `max_tokens` is `500`–`4000`; null uses project configuration. |
| `get_section` | `section`, `project=null`, `include_resolved=false` | `{section, entries}`. Sections: `overview`, `focus`, `blockers`, `bugs`, `conventions`, `decisions`, `requirements`, `glossary`, `features`. |
| `get_entry` | `entry_id`, `project=null` | One verbatim entry; deleted/archived entries are hidden. |
| `get_entry_history` | `entry_id`, `project=null` | Immutable revisions, including lifecycle changes. |
| `update_overview` | `project=null`, `headline=null`, `detail=null` | Merged overview entry. |
| `set_current_focus` | `text`, `project=null` | Project summary after resolving prior open focus entries and setting the new focus. |
| `delete_entry` | `entry_id`, `project=null` | Soft-deleted entry snapshot; history remains. |

Project summaries contain `id`, `name`, `root_path`, `status_line`, both token budgets, both character limits, `expiry_policy`, and `expiry_days`. Entry objects contain `id`, `project_id`, `section`, `headline`, `detail`, lifecycle `status`, `priority`, `author`, timestamps, requirement status, linked files, related entry ID, and requirement key.

## Section writes

The following generated tools have the same signatures for each singular name `focus`, `blocker`, `bug`, `convention`, `decision`, and `glossary`:

| Pattern | Arguments and defaults | Behavior |
|---|---|---|
| `add_<singular>` | `project=null`, `headline=null`, `detail=null`, `priority=0`, `related_entry_id=null` | Creates an entry in the corresponding section. |
| `update_<singular>` | `entry_id`, `project=null`, `headline=null`, `detail=null`, `priority=null`, `related_entry_id=null` | Merge-updates supplied fields. |
| `resolve_<singular>` | `entry_id`, `project=null` | Resolves the entry so it leaves active briefings. |

Exact names are:

- `add_focus`, `update_focus`, `resolve_focus`
- `add_blocker`, `update_blocker`, `resolve_blocker`
- `add_bug`, `update_bug`, `resolve_bug`
- `add_convention`, `update_convention`, `resolve_convention`
- `add_decision`, `update_decision`, `resolve_decision`
- `add_glossary`, `update_glossary`, `resolve_glossary`

For focus replacement semantics, prefer `set_current_focus` over `add_focus`.

## Features

Per-feature docs — what a feature does, which files implement it, and which requirement it satisfies — for humans browsing the codebase rather than an agent's compact briefing. Deliberately excluded from `get_project_briefing` regardless of the `sections` argument (protects the token budget); read them back with `get_section(project, "features")`.

| Tool | Arguments and defaults | Behavior |
|---|---|---|
| `add_feature` | `project=null`, `headline=null`, `detail=null`, `linked_files=null`, `related_entry_id=null`, `priority=0` | Creates a feature entry. `linked_files` are the files that implement it; `related_entry_id` is the id of the requirements-section entry it satisfies. |
| `update_feature` | `entry_id`, `project=null`, `headline=null`, `detail=null`, `linked_files=null`, `related_entry_id=null`, `priority=null` | Merge-updates supplied fields. |
| `resolve_feature` | `entry_id`, `project=null` | Resolves the entry so it leaves active listings. |

To populate this section, an agent asked to "explain the codebase's features, their files, and I/O" should write the result via `add_feature`/`update_feature` instead of a standalone `.md` file, so the control-panel Features view stays the source of truth.

## Requirements

| Tool | Arguments and defaults | Result/behavior |
|---|---|---|
| `add_requirement` | `project=null`, `headline=null`, `detail=null`, `status="not-started"`, `linked_files=null`, `related_entry_id=null`, `priority=0` | Creates a requirement and writes through to the configured file. |
| `update_requirement` | `entry_id`, `project=null`, `headline=null`, `detail=null`, `linked_files=null`, `related_entry_id=null`, `priority=null` | Merge-updates and writes through. |
| `set_requirement_status` | `entry_id`, `status`, `project=null` | Sets `not-started`, `in-progress`, `blocked`, or `done`; writes through. `done` is rejected when configured criteria fail the close gate. |
| `resolve_requirement` | `entry_id`, `project=null` | Resolves lifecycle state and writes through. This differs from setting requirement status to `done`. |
| `sync_requirements` | `project=null` | Re-parses the file and returns created, updated, archived, written-back, reconciliation, error, and count details. |
| `get_requirement_contract` | `requirement_id`, `project=null`, `include="both"` | Verbatim invariants and/or criteria for one requirement. `include` is `invariants`, `criteria`, or `both`. |
| `get_task_contract` | `task`, `project=null`, `requirement_ids=null`, `max_tokens=500` | Compact relevant contract + close-gate summary. `max_tokens` is `80`–`500`; below 80 is rejected so `token_estimate <= token_budget`. T12 evidence absent → `review: not-configured`. T12 `missing`/`stale` rows identify criteria by `id` (or `invariant_id` + `key`). |
| `create_requirement_invariant` | `requirement_id`, `statement`, `kind` (`behavior`/`architecture`/`data-boundary`/`forbidden-path`/`integration`/`manual`), `risk` (`low`/`medium`/`high`), `project=null`, `key=null`, `sort_order=null` | Creates one invariant via `pcs.requirements.contracts`. Allocates `INV-N` when `key` is omitted. Caller is stored as author. |
| `update_requirement_invariant` | `invariant_id`, `project=null`, `statement=null`, `kind=null`, `risk=null`, `key=null`, `sort_order=null` | Merge-update. Omitted fields stay. Empty payloads are rejected. Explicit JSON `null` on any patch field rejects the whole call; `false` and `0` remain valid. |
| `delete_requirement_invariant` | `invariant_id`, `project=null` | Soft-delete; open criteria cascade. History is kept. |
| `create_acceptance_criterion` | `invariant_id`, `statement`, `evidence_kind` (`test`/`command`/`review`/`manual`/`file`), `project=null`, `key=null`, `required=true`, `independent_review="not-required"`, `sort_order=null` | Creates one criterion. Allocates `AC-N` when `key` is omitted. |
| `update_acceptance_criterion` | `criterion_id`, `project=null`, `statement=null`, `evidence_kind=null`, `required=null`, `independent_review=null`, `key=null`, `sort_order=null` | Merge-update. Omitted fields stay. Empty payloads are rejected. Explicit JSON `null` rejects the whole call; `required=false` and `sort_order=0` are accepted. |
| `delete_acceptance_criterion` | `criterion_id`, `project=null` | Soft-delete; history is kept. |
| `record_requirement_evidence` | `criterion_id`, `kind` (`test`/`command`/`review`/`manual`/`file`), `result` (`passed`/`failed`/`manual-pending`), `source_commit` (7–40 hex; stored as full 40-char SHA), `project=null`, `command_ref=null`, `test_ref=null`, `file_ref=null`, `worktree_fingerprint=null`, `artifact_ref=null` | Append-only compact evidence. Does not change requirement status (D4). Rejects logs, diffs, secrets, and oversized fields. On a dirty worktree, `worktree_fingerprint` must exactly match the server-computed current value or the call is rejected with `dirty-worktree: worktree_fingerprint required/does not match (expected <hex>)` — no paths, but the expected hex value is included so the caller can retry with it verbatim. |
| `get_requirement_evidence` | `requirement_id`, `project=null` | Compact evidence, violations, and close-gate state. No stdout or diffs. |
| `add_requirement_violation` | `invariant_id`, `summary` (1–200 chars), `project=null`, `severity="blocking"` (`blocking`/`warning`), `file_ref=null`, `line_no=null` (≥1) | Records a review finding. |
| `resolve_requirement_violation` | `violation_id`, `project=null` | Marks the finding resolved; stores resolver identity; history is kept. |
| `evaluate_close_gate` | `requirement_id`, `project=null` | Deterministic coverage/freshness/review evaluation. Does not change status. |
| `review_requirement_compliance` | `requirement_ids`, `project=null` | Exception-only T13 pre-close review. Returns status separately from verification, AC verified/total, validation freshness, independent review, and actionable criterion/invariant/violation IDs with concise file refs. Input is deduplicated and sorted; output is capped at 25 requirements and 8 exceptions each with omission counts. |

Requirement write responses may include `requirements_file` with `path`, `written`, `errors`, and `reconciliations`.

## Planning (plans, tasks, orchestration)

Multi-agent and human work is orchestrated as plans containing a task DAG, atomic claim leases, and an immutable event history (FR43-FR48, D18-D24). Tasks belong to exactly one plan and one project; dependency, requirement-link, and event isolation are enforced by database composite foreign keys (INV-PLAN-1). Task/plan completion never mutates requirement status — that stays strictly evidence-governed (D4, INV-PLAN-2).

Plan status: `draft`, `active`, `completed`, `archived`. Task status: `pending`, `ready`, `claimed`, `in_progress`, `blocked`, `in_review`, `completed`, `cancelled`. A lease is active while `lease_expires_at > now()`; at or below `now()` it is expired and reclaimable (the exact boundary `lease_expires_at == now()` counts as expired). Mutations on a task with an active lease strictly require its current claim token — there is no operator bypass; `archive_plan` is the sole trusted exception, atomically revoking every active lease in the plan.

| Tool | Arguments and defaults | Result/behavior |
|---|---|---|
| `create_plan` | `project`, `title`, `goal` | Empty plan in `draft` status. |
| `create_plan_with_tasks` | `project`, `title`, `goal`, `tasks` (list of `{local_task_id, title, objective, acceptance_criteria=[], linked_files=[], requirement_ids=[], priority=0}`), `dependencies=null` (list of `{task_local_id, depends_on_local_id}`) | Atomically creates a plan with its full task DAG in one transaction (FR43-FR45, D23). Rejects cycles, self-dependencies, and unknown local ids. |
| `list_plans` | `project`, `status=null` | Plans with their tasks; `status` filters to one plan status. |
| `get_plan` | `project`, `plan_id` | One plan with tasks, resolved dependencies, and requirement links. |
| `update_plan` | `project`, `plan_id`, `title=missing`, `goal=missing` | Merge-update; empty patch is rejected. |
| `archive_plan` | `project`, `plan_id` | Transitions to `archived`, atomically revokes every active lease, and cancels non-terminal tasks. |
| `activate_plan` | `project`, `plan_id` | `draft` -> `active`; zero-dependency tasks become `ready`. |
| `complete_plan` | `project`, `plan_id` | `active` -> `completed`; rejected while any task is non-terminal. Never touches linked requirements (D4). |
| `add_plan_task` | `project`, `plan_id`, `local_task_id`, `title`, `objective`, `acceptance_criteria=null`, `linked_files=null`, `requirement_ids=null`, `priority=0` | Adds one task to a draft or active plan. `requirement_ids` must reference entries in that project's `requirements` section. |
| `update_plan_task` | `project`, `plan_id`, `task_id`, `title=missing`, `objective=missing`, `acceptance_criteria=missing`, `linked_files=missing`, `requirement_ids=missing`, `priority=missing`, `claim_token=missing` | Merge-update; omitted fields stay. `claim_token` is required whenever the task holds an active lease. |
| `add_task_dependency` | `project`, `plan_id`, `task_id`, `depends_on_task_id` | Adds one prerequisite edge; rejects cycles, self-dependencies, and cross-plan/cross-project references (INV-PLAN-1). |
| `list_ready_tasks` | `project`, `plan_id=null` | Tasks across all active plans (or one plan) whose prerequisites are complete and whose status is `ready`, or which hold an expired/reclaimable lease (`claimed`/`in_progress`/`in_review` with `lease_expires_at <= now()`) (FR46). |
| `claim_task` | `project`, `plan_id`, `task_id`, `claimed_by`, `lease_seconds=1800` | Atomically claims a `ready` task or reclaims one with an expired lease. Returns a one-time `claim_token` — never retrievable again; every other read redacts it. Concurrent claims on an unexpired lease fail. |
| `heartbeat_task` | `project`, `plan_id`, `task_id`, `claim_token`, `lease_seconds=1800` | Extends the lease, strictly preserving the current status (`claimed` stays `claimed`, `in_progress` stays `in_progress` — never advances the task). |
| `release_task` | `project`, `plan_id`, `task_id`, `claim_token` | Relinquishes the lease back to `ready`. |
| `set_task_status` | `project`, `plan_id`, `task_id`, `status`, `claim_token=null`, `reason=null` | Transitions status (e.g. `claimed` -> `in_progress` -> `in_review`, or -> `blocked`/`cancelled`). `claim_token` is required whenever the task holds an active lease. |
| `complete_task` | `project`, `plan_id`, `task_id`, `claim_token=null` | Completes the task, revokes its lease, and unlocks downstream dependents whose other prerequisites are also done. `claim_token` is required only while the lease is active — tokenless completion is permitted once it has expired. |
| `get_task_history` | `project`, `plan_id`, `task_id` | Immutable, chronologically ordered event log — `created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled` — each with actor, prior/new status, timestamp, and a redacted structured payload (FR48, D21, INV-PLAN-4). |
| `generate_plan_draft` | `project`, `goal`, `constraints=null`, `max_tasks=10` | Advisory, strictly read-only AI plan proposal using the project's persisted T20 summary provider (INV-PLAN-6). Returns `{ok, draft, provider, model, warning}` — `ok=false` with a `warning` (never an error) when the provider is unconfigured, unreachable, or returns an invalid/hallucinated proposal (e.g. a requirement id not present in the project). Writes zero rows; a caller must separately call `create_plan_with_tasks` with data of their own choosing to persist anything. |

Plan objects contain `id`, `project_id`, `title`, `goal`, `status`, `author`, timestamps, and `tasks`. Task objects contain `id`, `plan_id`, `project_id`, `local_task_id`, `title`, `objective`, `acceptance_criteria`, `linked_files`, `priority`, `status`, `claimed_by`, `lease_expires_at`, timestamps, `dependencies` (prerequisite task ids), and `requirement_ids` — never `claim_token` or `claim_token_hash`. `claim_task`'s result additionally carries the one-time `claim_token` alongside the task.

## Index, retrieval, and code map

| Tool | Arguments and defaults | Result |
|---|---|---|
| `get_index_status` | `project=null` | Index state, timestamps, commit, counts, skips, symbol modes, and semantic availability. |
| `reindex` | `project=null`, `incremental=true` | Updated index status. `false` performs a full rebuild. |
| `search_code` | `query`, `project=null`, `scope="project"`, `subtree=null`, `files=null`, `globs=null`, `limit=20` | Ranked hits plus semantic availability/mode. `limit` is `1`–`100`. |
| `retrieve_context` | `task`, `project=null`, `max_tokens=1500`, `scope="project"`, `subtree=null`, `files=null` | Token-bounded relevant code/document pack. |
| `prepare_task` | `task=null`, `task_id=null`, `project=null`, `max_tokens=null` | Exactly one of `task` or `task_id` must be given. With `task` (free text): briefing, ≤500-token contract/close-gate, and code pack with reported budget split; null `max_tokens` uses project default, valid range `1000`–`16000`. With `task_id` (a planned task's UUID from `create_plan`/`add_plan_task`, T25/INV-PLAN-5): a bounded, role-neutral Markdown handoff prompt covering the task's objective, acceptance criteria, dependency status, and linked contract rules — never claim tokens, provider keys, or raw diffs. Unused contract budget spills to code; the FR22a code floor is kept when chunks exist. |
| `get_code_map` | `project=null`, `scope=null`, `depth=1`, `include_external=false` | One graph tier. `scope` may be a subtree or indexed file; `depth` is clamped to `1`–`3`. |

Search/retrieval scopes are `project`, `subtree`, `files`, and `focus`. `subtree` is used with subtree scope; `files` is used with files scope. Semantic ranking is unavailable until an embedding backend is configured and the project is reindexed.

## Resources

| URI template | Format | Content |
|---|---|---|
| `context://{project}/overview` | Markdown text | Active overview entries. |
| `context://{project}/focus` | Markdown text | Active focus entries. |
| `context://{project}/blockers` | Markdown text | Active blockers. |
| `context://{project}/bugs` | Markdown text | Active bugs. |
| `context://{project}/conventions` | Markdown text | Active conventions. |
| `context://{project}/decisions` | Markdown text | Active decisions. |
| `context://{project}/requirements` | Markdown text | Active requirements. |
| `context://{project}/glossary` | Markdown text | Active glossary entries. |
| `context://{project}/history/{entry_id}` | Markdown text | Immutable revision history; returns `(no revisions)` when none exist. |
| `context://{project}/code-map` | JSON text | Top-tier code map. Use `get_code_map` for scoped expansion. |

Resources are read-only. Use tools for all writes.


## Pre-close agent sequence

Author the contract before writing implementation evidence:

1. `create_requirement_invariant` / `create_acceptance_criterion` (or the matching HTTP routes) until `get_requirement_contract` returns stable IDs. Merge-update with `update_*`; never send empty payloads. Soft-delete with `delete_*`.
2. `prepare_task` with the task and requirement IDs.
3. `get_requirement_contract` for missing AC details.
4. `record_requirement_evidence` for each completed criterion. Independent-review evidence must use a different author when the criterion requires it.
5. `review_requirement_compliance` and resolve only the returned exceptions.
6. `evaluate_close_gate` then `set_requirement_status(..., status="done")` after every configured verdict is `verified`. A `not-configured` verdict is explicit legacy state, not a failed or verified contract.

Example create:

`create_requirement_invariant(project="demo", requirement_id="REQ_ENTRY_ID", statement="Adapters delegate to contracts.", kind="architecture", risk="high", key="INV-AUTHOR-1")`

Example: `review_requirement_compliance(project="demo", requirement_ids=["REQ_ENTRY_ID"])`. Successful rows contain no repeated contract prose and an empty `exceptions` list.
