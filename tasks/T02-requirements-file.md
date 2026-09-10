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
- [ ] Add requirement in store → block appears in file; edit status marker in file + `sync_requirements` → store + reflected back (AC18)
- [ ] Status changed in both file and store since last sync → store wins, file token rewritten, reconciliation reported (AC22)
- [ ] Block deleted from file → `archived` in store, still in history, not resurrected (AC22)
- [ ] Malformed block → error, last-good retained, nothing partially applied
- [ ] Tests per AC; `just check` green
- [ ] Handoff written

## Handoff
_(fill in)_
