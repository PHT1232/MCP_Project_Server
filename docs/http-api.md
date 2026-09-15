# HTTP API reference

`pcs http` serves JSON routes under `/api` on the same Starlette application as streamable HTTP MCP (`/mcp`). Path `{project}` accepts an exact project name or ID and should be URL-encoded.

Requests may set `X-PCS-Caller`; absent values are logged as `frontend`. Handled service-validation errors use `{ "error": "..." }` and return `400`; unknown projects also include `available` and return `404`; missing entries/source return `404`. Malformed input rejected by framework-level parsing may use the framework's error response.

## Health and projects

| Method and path | Input | Success |
|---|---|---|
| `GET /api/health` | none | `{status, bind_mode, bind_host}`. |
| `GET /api/projects` | none | Array of project summaries. |
| `POST /api/projects` | JSON: `name`, `root_path`, `overview` | `201` project summary. Registers, indexes an existing root, starts watching, and initializes requirements sync. |
| `PATCH /api/projects/{project}` | Any of `expiry_policy`, `expiry_days`, `briefing_token_budget`, `prepare_task_token_budget`, `headline_max_chars`, `detail_max_chars` | Updated project summary. |
| `GET /api/projects/{project}/briefing` | Query: optional comma-separated `sections`; optional `max_tokens` | `{project, briefing}`. |
| `PUT /api/projects/{project}/focus` | JSON: `text` | Project summary after replacing current focus. |

Project summaries contain `id`, `name`, `root_path`, `status_line`, `briefing_token_budget`, `prepare_task_token_budget`, `headline_max_chars`, `detail_max_chars`, `expiry_policy`, and `expiry_days`.

## Sections and entries

| Method and path | Input | Success |
|---|---|---|
| `GET /api/projects/{project}/sections/{section}` | Query: `include_resolved=true` to include resolved entries | `{section, entries}`. Valid sections: `overview`, `focus`, `blockers`, `bugs`, `conventions`, `decisions`, `requirements`, `glossary`. |
| `POST /api/projects/{project}/entries` | JSON: `section`; optional `headline`, `detail`, `priority` (`0` default), `status` or `requirement_status`, `linked_files`, `related_entry_id` | `201` entry. Requirement writes may add `requirements_file`. |
| `GET /api/projects/{project}/entries/{entry_id}` | none | Entry object. |
| `PATCH /api/projects/{project}/entries/{entry_id}` | Any writable entry fields | Updated entry; supplied fields merge with existing values. |
| `POST /api/projects/{project}/entries/{entry_id}/resolve` | none | Resolved entry. |
| `DELETE /api/projects/{project}/entries/{entry_id}` | none | Soft-deleted entry; history remains. |
| `GET /api/projects/{project}/entries/{entry_id}/history` | none | `{entry_id, revisions}`. |

An entry contains `id`, `project_id`, `section`, `headline`, `detail`, lifecycle `status`, `priority`, `author`, ISO timestamps, `requirement_status`, `linked_files`, `related_entry_id`, and `req_key`.

## Requirements

| Method and path | Input | Success |
|---|---|---|
| `GET /api/projects/{project}/requirements` | none | `{requirements, done_count, total_count}`. |
| `POST /api/projects/{project}/requirements/sync` | none | Full sync report: file metadata, created/updated/archived/written-back keys, reconciliations, errors, requirements, and counts. |
| `GET /api/projects/{project}/requirements/{requirement_id}/contract` | Query: `include=invariants`, `criteria`, or `both` | Typed verbatim contract drill-down from T11. |
| `POST /api/projects/{project}/requirements/{requirement_id}/invariants` | JSON: `statement`, `kind`, `risk`; optional `key`, `sort_order` | `201` invariant view. Delegates to `contracts.create_invariant`. `X-PCS-Caller` is stored as author. Unknown fields and non-string/non-integer JSON types return `400`. |
| `PATCH /api/projects/{project}/requirements/invariants/{invariant_id}` | Any of `statement`, `kind`, `risk`, `key`, `sort_order` | Merge-update. Omitted fields stay. Empty `{}`, JSON null, unknown fields, or non-string/non-integer JSON types return `400`. |
| `DELETE /api/projects/{project}/requirements/invariants/{invariant_id}` | none | Soft-deleted invariant; open criteria cascade. History remains. |
| `POST /api/projects/{project}/requirements/invariants/{invariant_id}/criteria` | JSON: `statement`, `evidence_kind`; optional `key`, `required` (default `true`), `independent_review` (default `not-required`), `sort_order` | `201` criterion view. Unknown fields and coerced JSON types return `400`. `required` must be a JSON boolean; `sort_order` a JSON integer (`0` allowed). |
| `PATCH /api/projects/{project}/requirements/criteria/{criterion_id}` | Any of `statement`, `evidence_kind`, `required`, `independent_review`, `key`, `sort_order` | Merge-update. Omitted fields stay. Empty payloads, JSON null, unknown fields, or coerced types return `400`. |
| `DELETE /api/projects/{project}/requirements/criteria/{criterion_id}` | none | Soft-deleted criterion; history remains. |
| `GET /api/projects/{project}/requirements/{requirement_id}/evidence` | none | Typed compact evidence, violations, and close-gate summary from T12; no logs or diffs. |
| `GET /api/projects/{project}/requirements/compliance` | Repeated `requirement_id` query parameters, or comma-separated `requirement_ids` | Deterministic compact T13 verdicts. At most 25 sorted unique requirements and 8 actionable exceptions per requirement are returned; omission counts expose truncation. |

Requirement status values are `not-started`, `in-progress`, `blocked`, and `done`. Lifecycle resolution is distinct from status `done`.

## Planning (plans, tasks, orchestration)

Plans and tasks live under `/api/projects/{project}/plans/...`; every task-scoped route is nested under its plan (`/plans/{plan_id}/tasks/{task_id}/...`) and returns `404` if `task_id` does not belong to `plan_id`, or if `plan_id` does not belong to `{project}` (AC-PLAN-1). See `docs/mcp-reference.md`'s Planning section for the shared domain model — plan/task status values, the lease-expiry boundary (`lease_expires_at > now()` is active; `<= now()` is expired/reclaimable), and the "no operator bypass" active-lease token rule.

| Method and path | Input | Success |
|---|---|---|
| `POST /api/projects/{project}/plans` | JSON: `title`, `goal` | `201` empty plan in `draft` status. |
| `GET /api/projects/{project}/plans` | Query: optional `status` | Array of plans (with tasks). |
| `POST /api/projects/{project}/plans/with-tasks` | JSON: `title`, `goal`, `tasks` (array of `{local_task_id, title, objective, acceptance_criteria, linked_files, requirement_ids, priority}`), optional `dependencies` (array of `{task_local_id, depends_on_local_id}`) | `201` plan created atomically with its full task DAG (FR43-FR45, D23). This is the only route that ever persists an AI-drafted plan, and only when a caller submits it explicitly. |
| `POST /api/projects/{project}/plans/generate-draft` | JSON: `goal`; optional `constraints`, `max_tasks` (`10` default, `1`-`30`) | `200` `{ok, draft, provider, model, warning}` (T26, INV-PLAN-6). Strictly read-only — writes zero rows regardless of `ok`. `ok=false` with a `warning` (not an HTTP error) covers an unconfigured/unreachable provider or an invalid/hallucinated proposal. |
| `GET /api/projects/{project}/plans/{plan_id}` | none | One plan with tasks, resolved dependencies, and requirement links. |
| `PATCH /api/projects/{project}/plans/{plan_id}` | Any of `title`, `goal` | Merge-update; empty patch returns `400`. |
| `POST /api/projects/{project}/plans/{plan_id}/activate` | none | `draft` -> `active`; zero-dependency tasks become `ready`. |
| `POST /api/projects/{project}/plans/{plan_id}/complete` | none | `active` -> `completed`; `400` while any task is non-terminal. Never touches linked requirements (D4). |
| `POST /api/projects/{project}/plans/{plan_id}/archive` | none | -> `archived`; atomically revokes every active lease in the plan and cancels non-terminal tasks — the sole trusted exception to active-lease token enforcement. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks` | JSON: `local_task_id`, `title`, `objective`; optional `acceptance_criteria`, `linked_files`, `requirement_ids`, `priority` | `201` task added to a draft or active plan. `requirement_ids` must reference that project's `requirements`-section entries. |
| `PATCH /api/projects/{project}/plans/{plan_id}/tasks/{task_id}` | Any of `title`, `objective`, `acceptance_criteria`, `linked_files`, `requirement_ids`, `priority`, `claim_token` | Merge-update; empty patch returns `400`. `claim_token` required (`409` otherwise) while the task holds an active lease. |
| `POST /api/projects/{project}/plans/{plan_id}/dependencies` | JSON: `task_id`, `depends_on_task_id` | Adds one prerequisite edge; `400` on a cycle, self-dependency, or a task from another plan/project (INV-PLAN-1). |
| `GET /api/projects/{project}/ready-tasks` | none | Ready/reclaimable tasks across every active plan in the project (FR46). |
| `GET /api/projects/{project}/plans/{plan_id}/ready-tasks` | none | Same predicate, scoped to one plan. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/claim` | JSON: `claimed_by`; optional `lease_seconds` (`1800` default) | `200` `{task, claim_token}` — claims a `ready` task or atomically reclaims one with an expired lease. `claim_token` is returned exactly once; every later read redacts it. `409` if the current lease is unexpired. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/heartbeat` | JSON: `claim_token`; optional `lease_seconds` (`1800` default) | Extends the lease, strictly preserving status (never `claimed` -> `in_progress`). `409` on a stale/expired/invalid token. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/release` | JSON: `claim_token` | Relinquishes the lease back to `ready`. `409` on a stale/expired/invalid token. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/status` | JSON: `status`; optional `claim_token`, `reason` | Transitions status. `409` if the task holds an active lease and `claim_token` is missing or invalid — no bypass. |
| `POST /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/complete` | JSON (optional body): optional `claim_token` | Completes the task, revokes its lease, and unlocks downstream dependents. `claim_token` required only while the lease is active; tokenless completion is allowed once it has expired. |
| `GET /api/projects/{project}/plans/{plan_id}/tasks/{task_id}/history` | none | Immutable, chronologically ordered event array — `created`, `updated`, `dependency_added`, `claimed`, `reclaimed`, `heartbeat`, `released`, `status_changed`, `completed`, `cancelled` — each with actor, prior/new status, timestamp, and a redacted structured payload (FR48, D21, INV-PLAN-4). |

A plan object contains `id`, `project_id`, `title`, `goal`, `status` (`draft`/`active`/`completed`/`archived`), `author`, timestamps, and `tasks`. A task object contains `id`, `plan_id`, `project_id`, `local_task_id`, `title`, `objective`, `acceptance_criteria`, `linked_files`, `priority`, `status`, `claimed_by`, `lease_expires_at`, timestamps, `dependencies` (prerequisite task ids), and `requirement_ids` — never `claim_token` or `claim_token_hash`.

```bash
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans \
  -H 'content-type: application/json' -H 'x-pcs-caller: agent' \
  -d '{"title":"Ship checkout","goal":"Migrate off the legacy gateway"}'
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans/PLAN_ID/tasks/TASK_ID/claim \
  -H 'content-type: application/json' \
  -d '{"claimed_by":"agent-7","lease_seconds":1800}'
curl -s http://127.0.0.1:8080/api/projects/demo/ready-tasks
```

## Index and retrieval

| Method and path | Input | Success |
|---|---|---|
| `GET /api/projects/{project}/index` | none | Index state, timestamps, commit, file/chunk/skip counts, skipped files, symbol modes/count, embedded count, and semantic status. |
| `POST /api/projects/{project}/reindex` | Optional JSON `incremental` (`true` default) | Updated index status. |
| `GET /api/projects/{project}/search` | Query: `q` or `query`; `scope=project` default; optional `subtree`, comma-separated `files`, comma-separated `globs`, `limit=20` | `{hits, semantic_available, mode, note}`. Limit range is `1`–`100`. |
| `POST /api/projects/{project}/retrieve-context` | JSON or query: `task`; optional `max_tokens` (`1500` default) | Token-bounded context pack. Unlike the MCP tool, this HTTP route currently does not accept scope fields. |
| `POST /api/projects/{project}/prepare-task` | JSON or query: exactly one of `task` (free text) or `task_id` (a planned task's UUID, T25); optional `max_tokens` (project default) | With `task`: curated briefing plus code pack and reported budget split. With `task_id`: a bounded, role-neutral Markdown handoff `prompt` covering the task's objective, acceptance criteria, dependency status, and linked contract rules — never claim tokens or raw diffs. |

Scopes are `project`, `subtree`, `files`, and `focus`. Search hits include path, line range, snippet, score, match/retrieval modes, stale flag, symbol, kind, and language.

## Code map and source

| Method and path | Input | Success |
|---|---|---|
| `GET /api/projects/{project}/code-map` | Query: optional `scope`, `depth` (`1` default), `external=true` | One graph tier with nodes, edges, overlays, provenance, and stats. Scope may be a subtree or indexed file; depth is clamped to `1`–`3`. |
| `GET /api/projects/{project}/source` | Required query `path` | `{path, language, content, truncated}` for a non-skipped indexed file. Response is capped at 512 KiB. |

Source paths must be relative, remain within the registered root, and exist in the project's current index.

## Examples

```bash
curl -s http://127.0.0.1:8080/api/projects
curl -s 'http://127.0.0.1:8080/api/projects/demo/search?q=authentication&limit=10'
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/reindex \
  -H 'content-type: application/json' \
  -d '{"incremental":true}'
curl -s 'http://127.0.0.1:8080/api/projects/demo/code-map?scope=server/src&depth=2'
```


### Pre-close compliance workflow

1. Author invariants and criteria (`POST`/`PATCH`/`DELETE` under `/requirements/...` or the MCP `create_*`/`update_*`/`delete_*` tools) until `GET .../contract` returns stable IDs.
2. Call `prepare_task` for the implementation task and requirement IDs.
3. Read `get_requirement_contract` or the HTTP contract route to inspect missing AC IDs.
4. Record compact evidence with `record_requirement_evidence`; never submit stdout, logs, or diffs.
5. Call `review_requirement_compliance` or the HTTP compliance route. Drill into returned criterion, invariant, and violation IDs only when exceptions exist.
6. Request requirement status `done` only after `evaluate_close_gate` passes and the verdict is `verified`. `not-configured` preserves legacy behavior but is not evidence of verification.

```bash
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/requirements/REQ_ENTRY_ID/invariants \
  -H 'content-type: application/json' -H 'x-pcs-caller: agent' \
  -d '{"statement":"Adapters delegate to contracts.","kind":"architecture","risk":"high","key":"INV-AUTHOR-1"}'
curl -sG http://127.0.0.1:8080/api/projects/demo/requirements/compliance \
  --data-urlencode requirement_id=REQ_ENTRY_ID
```

## Global AI provider settings (T20)

| Method and path | Input | Success |
|---|---|---|
| `GET /api/admin/ai-settings` | none | `{embedding, summary, reindex_required}`. Provider objects contain nonsecret settings, `source` (`persisted`, `environment`, or `default`), and `api_key_configured`; API key values are never returned. |
| `PATCH /api/admin/ai-settings` | One or both complete `embedding` / `summary` objects | Merge-update and return the same redacted shape. Omit a provider to retain it. Inside a supplied provider, omit `api_key` to retain, provide a non-empty string to replace, or use `null` to clear. |

Embedding fields are `backend`, `base_url`, `model`, `dimensions`, `batch_size`, `timeout_seconds`, and optional `api_key`. Summary fields are `backend`, `base_url`, `model`, `timeout_seconds`, and optional `api_key`. Unknown/missing fields, unsupported backends, nonpositive numeric values, and unsafe URLs return `400`. Persisting a secret without `PCS_AI_SETTINGS_MASTER_KEY` also returns `400`; the submitted secret is not included in the response or structured tool-call log.

`PATCH` requires a constant-time validated `PCS_ADMIN_TOKEN` and fails closed when it is unset. Malformed JSON returns `400`. URL validation uses an explicit allowed-host list and repeats all-address DNS safety checks at call time; redirects are disabled. `reindex_required` is derived across all project index rows and clears only after each affected project completes successful full embedding.

All responses from `/api/admin/ai-settings`, including errors, carry `Cache-Control: no-store`. Provider bounds are URL 2048 characters, model 200, backend 32, API key 8192, dimensions 65536, batch size 2048, and timeout 300 seconds; non-finite numbers are invalid. Outbound requests connect to the validated IP while preserving the configured hostname for `Host`, TLS SNI, and certificate verification.
