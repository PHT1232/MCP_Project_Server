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

Requirement status values are `not-started`, `in-progress`, `blocked`, and `done`. Lifecycle resolution is distinct from status `done`.

## Index and retrieval

| Method and path | Input | Success |
|---|---|---|
| `GET /api/projects/{project}/index` | none | Index state, timestamps, commit, file/chunk/skip counts, skipped files, symbol modes/count, embedded count, and semantic status. |
| `POST /api/projects/{project}/reindex` | Optional JSON `incremental` (`true` default) | Updated index status. |
| `GET /api/projects/{project}/search` | Query: `q` or `query`; `scope=project` default; optional `subtree`, comma-separated `files`, comma-separated `globs`, `limit=20` | `{hits, semantic_available, mode, note}`. Limit range is `1`–`100`. |
| `POST /api/projects/{project}/retrieve-context` | JSON or query: `task`; optional `max_tokens` (`1500` default) | Token-bounded context pack. Unlike the MCP tool, this HTTP route currently does not accept scope fields. |
| `POST /api/projects/{project}/prepare-task` | JSON or query: `task`; optional `max_tokens` (project default) | Curated briefing plus code pack and reported budget split. |

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
