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
| `get_section` | `section`, `project=null`, `include_resolved=false` | `{section, entries}`. Sections: `overview`, `focus`, `blockers`, `bugs`, `conventions`, `decisions`, `requirements`, `glossary`. |
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

## Requirements

| Tool | Arguments and defaults | Result/behavior |
|---|---|---|
| `add_requirement` | `project=null`, `headline=null`, `detail=null`, `status="not-started"`, `linked_files=null`, `related_entry_id=null`, `priority=0` | Creates a requirement and writes through to the configured file. |
| `update_requirement` | `entry_id`, `project=null`, `headline=null`, `detail=null`, `linked_files=null`, `related_entry_id=null`, `priority=null` | Merge-updates and writes through. |
| `set_requirement_status` | `entry_id`, `status`, `project=null` | Sets `not-started`, `in-progress`, `blocked`, or `done`; writes through. |
| `resolve_requirement` | `entry_id`, `project=null` | Resolves lifecycle state and writes through. This differs from setting requirement status to `done`. |
| `sync_requirements` | `project=null` | Re-parses the file and returns created, updated, archived, written-back, reconciliation, error, and count details. |
| `get_requirement_contract` | `requirement_id`, `project=null`, `include="both"` | Verbatim invariants and/or criteria for one requirement. `include` is `invariants`, `criteria`, or `both`. |
| `get_task_contract` | `task`, `project=null`, `requirement_ids=null`, `max_tokens=500` | Compact relevant contract + close-gate summary, capped at 500 estimated tokens. T12 evidence absent → `review: not-configured`. |

Requirement write responses may include `requirements_file` with `path`, `written`, `errors`, and `reconciliations`.

## Index, retrieval, and code map

| Tool | Arguments and defaults | Result |
|---|---|---|
| `get_index_status` | `project=null` | Index state, timestamps, commit, counts, skips, symbol modes, and semantic availability. |
| `reindex` | `project=null`, `incremental=true` | Updated index status. `false` performs a full rebuild. |
| `search_code` | `query`, `project=null`, `scope="project"`, `subtree=null`, `files=null`, `globs=null`, `limit=20` | Ranked hits plus semantic availability/mode. `limit` is `1`–`100`. |
| `retrieve_context` | `task`, `project=null`, `max_tokens=1500`, `scope="project"`, `subtree=null`, `files=null` | Token-bounded relevant code/document pack. |
| `prepare_task` | `task`, `project=null`, `max_tokens=null` | Briefing, ≤500-token contract/close-gate, and code pack with reported budget split. Null uses project default; valid range is `1000`–`16000`. Unused contract budget spills to code; the FR22a code floor is kept when chunks exist. |
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
