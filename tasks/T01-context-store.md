# T01 — Context store

**Branch:** `task/T01-context-store`  ·  **Depends on:** T00  ·  **Blocks:** T02, T04, T06

> Stub — flesh out against the real skeleton after T00 merges.

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
- [ ] Every section has tools + a resource; briefing assembles under budget with headlines + collapsed counts + drill-down (AC1, AC4a)
- [ ] Two edits → two revisions via `get_entry_history`; "deleted" entry gone from reads, present in history (AC17)
- [ ] Resolve moves an item out of the briefing, keeps history (AC4)
- [ ] Cross-project isolation holds (AC5)
- [ ] Unknown/missing `project` → error listing projects (AC16)
- [ ] Restart preserves everything (AC6)
- [ ] Tests for each AC; `just check` green
- [ ] Handoff written

## Handoff
_(fill in)_
