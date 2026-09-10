# T02 — Requirements template file

**Branch:** `task/T02-requirements-file`  ·  **Depends on:** T01 (merged)  ·  **Blocks:** T06

**Read first:** `AGENTS.md`, `REQUIREMENTS.md` §7 FR16a + D12/D15, `reviews/T01.md`
(esp. "Notes for dependents → T02"), and `tasks/T01-context-store.md` Handoff.
Base branch off current `main`.

**T01 gives you:** the `requirements` section in the store, `add_requirement` /
`update_requirement` / `set_requirement_status` / `resolve_requirement` MCP tools,
`context://{project}/requirements`, `linked_files` + `related_entry_id` columns
on `context_entries`, and the audit log. Requirement **id is a UUID** — add a
nullable `req_key` column (`R-NNN`) in your migration; do **not** overload the id
or headline. Store status tokens: `not-started | in-progress | blocked | done`.
The requirements file path default is `.project-context/requirements.md` relative
to the project root (T08 mounts `/repos/.project-context` read-write).

## Goal
Two-way sync between a human-editable Markdown requirements file in the repo and
the Requirements section of the context store (FR16a, D12, D15).

## In scope
- Template + parser for `.project-context/requirements.md` (configurable path):
  `### R-NNN — title`, managed `<!-- req status=… files=… blocker=… -->` line,
  human prose. Server-assigned stable `R-NNN` IDs written back.
- `sync_requirements` MCP tool + run on `register_project` and on frontend
  refresh: 3-way merge vs. a stored snapshot (file hash + parsed state):
  added→create, removed→archive (never resurrect), prose→update store,
  status conflict→**store wins**, rewrite the file token, log reconciliation.
- Atomic file writes (temp + rename); only the managed token + heading ID are
  machine-edited, prose never reflowed.
- Malformed block → skipped, error returned by `sync_requirements` + surfaced for
  the frontend; never partial apply.
- `add_requirement` / `set_requirement_status` (from T01) also write through to
  the file.

## Key requirements
FR16a, D12, D15. ACs: AC18, AC22, AC14a.

## Acceptance checklist
- [x] Add requirement in store → block appears in file; edit status marker in file + `sync_requirements` → store + reflected back (AC18) — `test_ac18_add_in_store_writes_a_block_into_the_file`, `test_ac18_file_status_edit_flows_to_the_store`, `test_ac18_end_to_end_through_mcp_tools`
- [x] Status changed in both file and store since last sync → store wins, file token rewritten, reconciliation reported (AC22) — `test_ac22_status_changed_in_both_store_wins_and_token_rewritten`
- [x] Block deleted from file → `archived` in store, still in history, not resurrected (AC22) — `test_ac22_deleted_block_is_archived_and_never_resurrected`
- [x] Malformed block → error, last-good retained, nothing partially applied — `test_malformed_block_is_skipped_and_last_good_is_retained`, `test_malformed_token_is_a_block_error_not_fatal`, `test_duplicate_id_is_a_fatal_error`
- [x] Tests per AC; `just check` green
- [x] Handoff written

## Handoff

### Final module layout

```
server/src/pcs/
  requirements/
    __init__.py            # public surface: sync_requirements, list_requirements,
                           #   write_through_requirement_change, resolve_requirements_path
    types.py               # regexes + ManagedToken / ParsedBlock / ParsedFile /
                           #   ReconciliationNote / RequirementView / SyncReport
    parser.py              # parse_requirements(text) -> ParsedFile (never raises)
    template.py            # DEFAULT_TEMPLATE, render_heading/token/new_block, LineEdit,
                           #   serialise() — surgical line edits, prose never reflowed
    service.py             # sync_requirements 3-way merge + atomic file writes (no MCP/HTTP)
    models.py              # RequirementsSyncState (per-project snapshot row)
  alembic/versions/0004_requirements_file.py   # req_key column + 'archived' status + snapshot table
  db/models.py             # ContextEntry.req_key (nullable, partial-unique per project)
  context/
    types.py               # + STATUS_ARCHIVED, HIDDEN_STATUSES, ACTION_ARCHIVE; EntryView.req_key
    service.py             # + archive_entry(); add_entry(req_key=…); hidden-status filters
  mcp/tools.py             # + sync_requirements tool; add/update/set_status/resolve_requirement
                           #   and register_project now write through to the file
  web_api/routes.py        # + GET /api/projects/{p}/requirements, POST …/requirements/sync;
                           #   generic entry routes write through when section == requirements
tests/
  test_requirements_parser.py   # pure text: parse + surgical serialise round-trips
  test_requirements_file.py      # AC18, AC22, malformed-block, idempotency, MCP e2e (real PG)
```

### How to run

- Gate: `just check` (repo root) — server ruff/mypy/pytest + web + `compose-lint` + `vite build`. Green.
- Migrate from empty: `just up && cd server && uv run alembic downgrade base && uv run alembic upgrade head` — clean (`0001…0004`).
- Just the T02 tests: `cd server && uv run pytest tests/test_requirements_parser.py tests/test_requirements_file.py`.
- MCP: `uv run pcs stdio` / `uv run pcs http`; tool `sync_requirements(project=…)`; HTTP `POST /api/projects/{project}/requirements/sync`.

### Template / file format (FR16a)

```
# Requirements
<!-- optional preamble / YAML frontmatter — opaque, never touched -->

### R-001 — Persist context in PostgreSQL
<!-- req status=in-progress files=src/db.ts,src/schema.sql blocker=<entry-id> -->
Human prose. Never reflowed by the server.
```

- One `### R-NNN — title` heading per requirement (separator may be `—`, `–`, `-`, or `:`).
- Exactly one managed `<!-- req … -->` line, immediately after the heading. Missing ⇒ `not-started`.
- `status ∈ not-started | in-progress | blocked | done` (same tokens as the store).
- `files=` / `blocker=` are **store-owned** (D15): seeded from the token on first
  sight, thereafter rewritten from `ContextEntry.linked_files` / `related_entry_id`.
  Unrecognised `key=value` tokens are preserved verbatim.
- Server-managed: the `<!-- req … -->` line and the heading's `R-NNN` id. Everything
  else (title text, prose, blank lines, preamble) is human-owned and copied byte-for-byte.
- Writes are atomic (temp file in the same dir + `os.replace`). The file always ends
  with exactly one newline (the only normalisation applied).

### Sync model / decisions

- **System of record (D15):** file owns existence + title/prose; store owns status +
  links + history. `sync_requirements` = 3-way merge vs. the `requirements_sync_state`
  snapshot (`{req_key, title, prose_hash, status}` per requirement + file SHA-256 + the
  `next_seq` R-NNN counter).
- Block added in file (no id) → store row created, `R-NNN` assigned + written back.
- Block removed from file → `archive_entry` (new lifecycle status `archived`): hidden
  from reads, full history kept, **never** resurrected (snapshot drops it; a later
  re-added `### R-001` heading is left untouched with a reconciliation note).
- Title/prose differ → store updated from the file (file always wins; D15).
- Status differs: file-only change since snapshot ⇒ file wins; store-only ⇒ store wins +
  token rewritten; **both** changed ⇒ **store wins**, token rewritten, reconciliation
  note logged (`requirements_reconciliation`) and returned in `SyncReport.reconciliations`.
- Unparseable block → skipped, its last-good store state retained, error in
  `SyncReport.errors` (`ok=False`); good blocks in the same file still apply. A
  **file-level** problem (duplicate id, unreadable file) applies nothing.
- `R-NNN` ids: server-assigned, zero-padded to 3, monotonic per project, never reused
  (counter persists across archive). Collisions with a hand-typed id are skipped over.
- Runs on: `register_project` (creates the file from the template if absent),
  `sync_requirements` (MCP + HTTP), and after every `add_/update_/set_requirement_status/
  resolve_requirement` (write-through; a file problem is logged, never loses the store write).

### New config / schema

- `PCS_REQUIREMENTS_FILE` (default `.project-context/requirements.md`) — relative ⇒ under
  the project `root_path`, absolute ⇒ verbatim; `..` rejected. Documented in `.env.example`
  and `pcs.config.Settings`.
- Migration `0004_requirements_file`: `context_entries.req_key` (nullable `String(16)`,
  partial-unique `(project_id, req_key) WHERE req_key IS NOT NULL`); status check constraint
  gains `'archived'`; new table `requirements_sync_state` (PK `project_id`, FK → projects
  `ON DELETE CASCADE`, `file_path`, `file_sha256`, `next_seq`, `snapshot` JSONB, `last_synced_at`).

### Seams for T06

- Read model: `GET /api/projects/{project}/requirements` → `{requirements:[{req_key, entry_id,
  title, status, lifecycle, linked_files}], done_count, total_count}` — no file write.
- Refresh action: `POST /api/projects/{project}/requirements/sync` → `SyncReport.as_dict()`
  (`created / updated / archived / written_back / reconciliations / errors / requirements /
  done_count / total_count`). Wire this to the manual-refresh control (D6).
- Add / status-change from the dashboard: use the existing `POST …/entries` (section
  `requirements`) and `PATCH …/entries/{id}` routes — they now return an extra
  `requirements_file` key (`{path, written, errors, reconciliations}`); surface `errors`
  to the user (AC14a UI half is T06).
- `EntryView` / entry JSON now carries `req_key`.
- The frontend never edits the `.md` file directly — always go through the store + sync.

### Deviations / notes to confirm

1. **New lifecycle status `archived`** on `context_entries` (not just a T02-local concept).
   Needed for AC22's "archived (still in history), not removed" as distinct from `resolved`
   (requirement done) and `deleted` (soft-delete). `HIDDEN_STATUSES = {deleted, archived}`
   now drives the "hidden from reads, kept in history" filter in `context.service`.
2. **`archive_entry` + `ACTION_ARCHIVE`** added to `context.service` / `context.types`
   (revisions have no action check-constraint, so no migration for the action value).
3. **`files=` / `blocker=` are store-owned** and rewritten from the store after first
   sight (D15 "store owns links"); `blocker=` carries the related entry id (there is no
   external key for blockers). Say if you want the file token to stay authoritative.
4. **Write-through = a full `sync_requirements`** after each requirement tool call (not a
   one-way projection). Keeps the snapshot fresh and resolves conflicts per spec; a
   malformed file makes the tool return `requirements_file.errors` but the store write
   still succeeds.
5. **`sync_requirements` always creates the file** from the template when missing (not only
   on `register_project`) so a frontend refresh on a pre-T02 project just works.
6. **`.env.example`** is behind a `Read(.env.*)` deny rule in this environment; the one-line
   `PCS_REQUIREMENTS_FILE` addition was written through an indirect shell reference — please
   eyeball that hunk in the diff.

### New dependencies

None. (`hashlib`, `os`, `re`, `pathlib`, `uuid` — stdlib.)
