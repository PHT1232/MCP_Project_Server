# T01 — Context store

**Branch:** `task/T01-context-store`  ·  **Depends on:** T00  ·  **Blocks:** T02, T04, T06

## Goal
The full curated-context subsystem: every section, the two-field entry model,
the audit log, deterministic briefing assembly, and all read/write MCP tools.

## In scope
- Schema (Alembic migration) for all sections: overview, focus, blockers, bugs,
  conventions, decisions, requirements, glossary. Entry = `headline` + `detail`
  + metadata (id, section, status, priority, author, timestamps) (FR2, FR3, FR3b).
- **Audit log** (FR11): every create/update/resolve/delete is an immutable
  revision; nothing hard-deleted; `get_entry_history`.
- Expiry policy config, default off (FR3a).
- Read MCP surface: `get_project_briefing` (real §7.2a logic — FR9a–FR9g:
  verbatim store, schema limits, deterministic rank/trim, drill-down pointers;
  LLM summary layer behind the same backend seam as T04, off by default),
  `get_section`, `get_entry`, resources `context://{project}/*` (FR5–FR9, FR7).
- Write MCP surface: `add_*` / `update_*` / `resolve_*` per section,
  `set_current_focus`, `set_requirement_status` (FR10, FR12, FR13).
- Budgets configurable per project with the D13 defaults (FR9g).
- Concurrency: serialized writes, per-entry merge, read-after-write (FR17, FR18).

## Out of scope
- The requirements **file** sync (T02) — T01 just owns the requirements section
  in the store and its tools.
- The actual LLM summarizer call (T04 provides the backend); T01 implements
  FR9c/FR9e (deterministic + fallback) and the seam for FR9d.

## Key requirements
FR2–FR13, FR9a–FR9g, FR17, FR18, D5, D13. ACs: AC1, AC3, AC4, AC4a, AC5, AC6,
AC14, AC16, AC17.

## Acceptance checklist
- [x] Every section has tools + a resource; briefing assembles under budget with headlines + collapsed counts + drill-down (AC1, AC4a)
- [x] Two edits → two revisions via `get_entry_history`; "deleted" entry gone from reads, present in history (AC17)
- [x] Resolve moves an item out of the briefing, keeps history (AC4)
- [x] Cross-project isolation holds (AC5)
- [x] Unknown/missing `project` → error listing projects (AC16)
- [x] Restart preserves everything (AC6)
- [x] Tests for each AC; `just check` green
- [x] Handoff written

## Handoff

### Final module layout

```
server/
  pyproject.toml                 # S3: ruff/mypy exclude only alembic/env.py; versions/* are checked
  src/pcs/
    db/
      models.py                  # Project (+ budgets/expiry), ContextEntry (+ priority/links), ContextEntryRevision
    alembic/versions/
      0001_baseline.py           # reformatted so it type-checks/lints (S3)
      0002_context_store.py      # T01 schema (FR3, FR3a, FR9g, FR11)
    context/
      types.py                   # sections, statuses, errors, EntryView / RevisionView / ProjectSummary
      validation.py              # headline/detail hard-reject + derive-by-truncation (FR3b, FR9b, FR9g, FR13)
      summarizer.py              # FR9d seam; T01 is always-off + FR9e truncation fallback
      assembly.py                # §7.2a deterministic rank/trim/collapse (FR9c, FR9e, FR9f)
      service.py                 # all store operations over AsyncSession (no MCP/HTTP imports)
    mcp/
      support.py                 # caller() + run_tool() → session_scope + log_tool_call (NFR6)
      tools.py                   # register_tools(mcp) — every T01 tool
      resources.py               # context://{project}/{section} + context://{project}/history/{entry_id}
      server.py                  # FastMCP instance; register tools, resources, /api routes
    web_api/routes.py            # T00 routes + entry/section/focus/configure (AC14 server-side)
  tests/
    conftest.py                  # TRUNCATE projects CASCADE (picks up revisions)
    test_service_unit.py         # validation + assembly, no DB
    test_context_store.py        # AC1, AC3, AC4, AC4a, AC5, AC6, AC16, AC17 + expiry/merge/read-after-write
    test_integration.py          # MCP tools/resources, HTTP+AC14, NFR6/S2 audit line
```

### How to run each piece

- **Install / gate:** `just setup && just check` (unchanged). Postgres via testcontainers for pytest.
- **Migrate:** `just up && just migrate` applies `0001` then `0002`. `alembic downgrade base && alembic upgrade head` is clean from empty.
- **MCP:** `cd server && uv run pcs stdio` or `uv run pcs http` (binds `127.0.0.1:8080`; `/mcp` + `/api/*`).
- **Server tests:** `cd server && uv run pytest`.

### Naming / structure decisions

- Sections (FR2): `overview`, `focus`, `blockers`, `bugs`, `conventions`, `decisions`, `requirements`, `glossary`.
- Lifecycle `status`: `open` | `resolved` | `deleted`. Delete is a state transition; the row stays (FR11, D5, AC17).
- Requirement status tokens (store form, FR2/FR16a): `not-started` | `in-progress` | `blocked` | `done`. T02 maps the file's `status=` token onto these; T01 does not touch the file.
- Writes take `SELECT … FROM projects WHERE … FOR UPDATE` so concurrent writers on one project serialize (FR17). Updates merge only the fields the caller sent (FR17). The acknowledging session commits before `run_tool` returns, so the next `session_scope` sees the write (FR18).
- Expiry (FR3a): `expiry_policy=off|age` + `expiry_days`. Default off. Age-based **hides** stale non-overview entries at read time; it does not mutate them to `resolved`. `include_resolved=True` on `get_section` still returns them. Explicit resolve is always available.
- Briefing rank (FR9c): overview → open blockers → current focus → open bugs → conventions linked to the current focus (`related_entry_id`) → recent decisions → requirement status summary → glossary. Over-budget items collapse to `+N more … — call get_section(project=…, section=…)`. Every listed item carries `[id]` (FR9f). Stored rows are never rewritten by assembly (FR9a, AC4a).
- Schema limits (FR9b/FR9g): supplied `headline` > per-project cap (default 120) or `detail` > cap (default 8000) is a hard reject. If only one field is given at **create**, the other is derived by truncation, not an LLM (FR3b).
- `set_current_focus` still **replaces** open focus rows (resolves them, inserts one new). `add_focus` appends an additional open focus without resolving others.
- Overview is upserted via `update_overview`; `add_entry(section="overview")` is rejected.

### MCP tools (32)

Read: `get_project_briefing` (`sections?`, `max_tokens?`), `get_section`, `get_entry`, `get_entry_history`, `list_projects`.
Lifecycle: `register_project`, `configure_project`.
Write: `update_overview`, `set_current_focus`, `add_*`/`update_*`/`resolve_*` for focus, blocker, bug, convention, decision, glossary; `add_requirement` / `update_requirement` / `set_requirement_status` / `resolve_requirement`; `delete_entry`.

Resources: `context://{project}/{section}` for every section, plus `context://{project}/history/{entry_id}`.

### HTTP surface (AC14 server-side; T06 consumes)

Kept T00: `GET /api/health`, `GET|POST /api/projects`, `GET /api/projects/{project}/briefing`.
Added: `PATCH /api/projects/{project}` (budgets/expiry), `PUT …/focus`, `GET …/sections/{section}`, `POST …/entries`, `GET|PATCH|DELETE …/entries/{id}`, `POST …/entries/{id}/resolve`, `GET …/entries/{id}/history`.

### Seams left for later tasks

- **T02:** `add_requirement` / `set_requirement_status` only touch the store. Do not create `.project-context/requirements.md` here. Canonical store tokens are the hyphenated FR16a set. `linked_files` and `related_entry_id` are already on the row for file/blocker links.
- **T04:** replace `pcs.context.summarizer.Summarizer` (always `is_available() is False` today) with the embedding/LLM backend. `assemble_briefing` already calls it for long overview details and falls back to `fallback_truncate` (FR9e). `prepare_task_token_budget` is stored per project (D13 default 4000, range 1000–16000) but unused until `prepare_task` lands.
- **T06:** typed client should extend T00's `api/client.ts` with the new `/api/projects/{project}/…` routes; do not embed MCP in the browser. AC14's frontend half is T06; T01 proves HTTP write ↔ MCP briefing and MCP write ↔ HTTP briefing.
- **T08:** unchanged bind-mode seam.

### Deviations / decisions to confirm

1. **`configure_project` and `delete_entry` are extra MCP tools** not named in §9's indicative table. Needed for FR3a/FR9g (per-project budgets/expiry) and AC17 (soft-delete). Happy to rename.
2. **Expiry hides at read time** rather than auto-flipping `status=resolved`. Reversible if the policy is turned off; say if you'd rather persist a resolve.
3. **Headline column is `Text`**, cap enforced in the app against `projects.headline_max_chars` so the D13 default of 120 can be raised per project. T00's `String(120)` would have blocked FR9g.
4. **FR9d is a class seam, not the T04 backend config object.** T04 should replace `get_summarizer()`; I did not invent a settings field for an LLM URL.
5. **S3 reformatted `0001_baseline.py`** (whitespace only) so `versions/*` pass ruff. No logic change.
6. **S2 captures `log_tool_call` via a spy on `pcs.mcp.support`** and asserts the JSON line shape through `JsonFormatter`. Attaching a handler to the `pcs` logger under pytest was a no-op (same T00 gap S2 described); the spy is on the actual call site every tool uses.

### New dependencies

None. Stack is unchanged (SQLAlchemy JSONB for `linked_files`, already on Postgres).

### Notes that may affect T02/T04/T06 scoping

- Service / thin-transport split is unchanged. New tools: `_caller` + `run_tool` + one service call.
- FastMCP tools still take `ctx: Context | None = None`.
- `StreamableHTTPSessionManager.run()` can only be entered once per `mcp` instance — tests must use a single `TestClient` per process for `/api`. T06/T09 should not spawn a second TestClient against the singleton `mcp`.
- Requirement IDs are still UUIDs. T02 assigns `R-NNN` — add a nullable `external_id` / `req_key` column then, don't overload `headline`.
- `get_project_briefing(sections=[…])` is FR6 scoping; unknown section names are ignored.
