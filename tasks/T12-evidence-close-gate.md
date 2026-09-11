# T12 — Evidence ledger and deterministic close gate

**Branch:** `task/T12-evidence-close-gate`  ·  **Depends on:** T10  ·  **Can run with:** T11  ·  **Blocks:** T13

## Goal

Record compact evidence with revision provenance and prevent false completion when configured acceptance criteria are missing, failed, stale, or blocked by an open violation.

## Owned files/modules

- New Alembic migration for evidence and violations
- New `server/src/pcs/requirements/evidence.py`
- `server/src/pcs/context/service.py` only around requirement status transitions
- Requirement evidence MCP tools in a new registration module
- `server/src/pcs/mcp/server.py` only for registration
- New `server/tests/test_requirement_evidence.py`
- `docs/mcp-reference.md`

Do not edit `prepare_task`, retrieval ranking, frontend code, or requirement-file grammar.

## Requirements

- Store compact evidence: criterion ID, kind, result (`passed`, `failed`, `manual-pending`), command/test/file references, source commit, optional worktree fingerprint, author, timestamp, and optional artifact reference.
- Do not store full stdout, full diffs, credentials, or arbitrary binary payloads.
- Store review violations linked to invariants with severity, concise summary, optional file/line, lifecycle status, author, and timestamps.
- Derive close-gate state deterministically from required criteria, latest valid evidence, source revision/fingerprint freshness, independent-review policy, and open blocking violations.
- Add tools to record/list evidence, add/resolve violations, and evaluate the close gate.
- Keep `set_requirement_status` backward compatible: requirements without configured criteria may still become `done`; configured requirements receive an actionable rejection until the gate passes.
- Independent-review evidence must have an author different from the recorded implementer when policy requires it.
- Evidence does not automatically change requirement status, preserving D4.

## Acceptance checklist

- [ ] Missing required criterion rejects `done` and names the criterion key
- [ ] Latest failed evidence rejects `done`; later passing current evidence supersedes it without deleting history
- [ ] Evidence from an older commit/fingerprint is reported stale and rejects `done`
- [ ] Open blocking violation rejects `done`; resolving it preserves history and removes the block
- [ ] Independent-review policy rejects self-authored review evidence
- [ ] Requirement with no configured criteria preserves legacy status behavior
- [ ] Evidence payload limits reject raw/oversized log-like content and secrets are not echoed in errors
- [ ] Concurrent evidence writes preserve all records and produce deterministic latest-evidence selection
- [ ] Every acceptance item has a regression test
- [ ] Focused tests and `just check` pass
- [ ] Handoff documents freshness semantics and compatibility behavior

## Verification

```bash
cd server && uv run pytest tests/test_requirement_evidence.py
just migrate
just check
```
