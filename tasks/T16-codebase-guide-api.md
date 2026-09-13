# T16 — Codebase Guide MCP and HTTP surfaces

**Branch:** `task/T16-codebase-guide-api` · **Depends on:** T15 · **Blocks:** T17

## Goal

Expose the guide service through audited MCP tools, a Markdown resource, and equivalent typed HTTP reads/sync.

## Owned files/modules

- `server/src/pcs/mcp/codemap_tools.py`
- `server/src/pcs/web_api/codemap_routes.py`
- MCP/server registration only if required by current architecture
- New `server/tests/test_codebase_guide_api.py`
- Focused additions to `server/tests/test_integration.py`

Do not change guide persistence semantics, migration, frontend, or main documentation.

## Invariants

- `INV-GUIDE-8`: MCP and HTTP reads return equivalent guide state for the same project/scope/include.
- `INV-GUIDE-9`: Only MCP `describe_files` writes summaries in v1; HTTP offers reads and artifact sync only.
- `INV-GUIDE-10`: Every tool/route logs project, caller, and outcome without logging summary prose.
- `INV-GUIDE-11`: The Markdown resource is generated from the same service payload, not a second implementation.
- `INV-GUIDE-12`: Project isolation and scope/path validation apply identically at every adapter.

## Requirements

- Extend `register_codemap_tools` with `get_codebase_guide`, `describe_files`, and `sync_codebase_guide`, each through `run_tool`.
- Capture `caller(ctx)` as `updated_by`; validate `notes` shape before service invocation.
- Add `context://{project}/codebase-guide`, rendered by `render_guide_markdown(get_codebase_guide(...))`.
- Add `GET /api/projects/{project}/codebase-guide?scope=&include=` with file path/writability metadata needed by UI.
- Add `POST /api/projects/{project}/codebase-guide/sync`; do not add HTTP summary editing.
- Follow existing `_caller`, `_error_response`, session, and structured audit patterns.
- Keep responses deterministic and avoid raw source/log/diff content.

## Acceptance checklist

- [x] MCP read exposes all/documented/undocumented/stale and scoped views
- [x] MCP describe writes multiple summaries, deletes empty summaries, and reports unknown paths
- [x] MCP sync regenerates the configured artifact
- [x] Resource Markdown equals service renderer output for current state
- [x] HTTP guide read equals MCP state and includes artifact writability metadata
- [x] HTTP sync regenerates the artifact without editing summaries
- [x] Unknown project, invalid include/scope, malformed notes, and read-only path return actionable bounded errors/results
- [x] Cross-project paths/notes cannot leak or mutate another project
- [x] Audit records success/error and caller without summary prose
- [x] Existing code-map routes/tools/resources remain compatible
- [x] Focused tests and `just check` pass
- [x] Handoff includes exact tool/resource/route payloads and independent-review result

## Required evidence

- Adapter tests for equality, audit, isolation, malformed input, resource output, and registration.
- Independent review required for project isolation, write authorization surface, and audit privacy.

## Verification

```bash
cd server && uv run pytest tests/test_codebase_guide_api.py tests/test_integration.py
just check
```

## Handoff

### Branch and Commits

- **Branch:** `task/T16-codebase-guide-api`
- **Scope:** Exposes Codebase Guide service through audited MCP tools, Markdown resource `context://{project}/codebase-guide`, and typed HTTP endpoints (`GET /api/projects/{project}/codebase-guide`, `POST /api/projects/{project}/codebase-guide/sync`).

### MCP Tools & Resources

1. `get_codebase_guide`:
   - Args: `project: str | None = None, scope: str | None = None, include: str = "all"`
   - Output: JSON dict with `project`, `scope`, `include`, `coverage: {total, documented, undocumented, stale, percentage}`, `generated_from`, and `files: [...]`.
2. `describe_files`:
   - Args: `project: str | None = None, notes: list[dict[str, str]] | None = None`
   - Output: JSON dict with `project`, `applied: list[str]`, `deleted: list[str]`, `unknown: list[dict[str, str]]`, `coverage`.
3. `sync_codebase_guide`:
   - Args: `project: str | None = None`
   - Output: JSON dict with `path`, `file_writable`, `written`, `bytes`.
4. Resource `context://{project}/codebase-guide`:
   - Returns Markdown generated via `guide.render_guide_markdown(...)`.

### HTTP Endpoints

1. `GET /api/projects/{project}/codebase-guide?scope=&include=`:
   - Returns guide payload identical to MCP `get_codebase_guide`, plus `artifact: {path, file_writable}`, `file_path`, and `file_writable`.
2. `POST /api/projects/{project}/codebase-guide/sync`:
   - Regenerates artifact via `write_guide_file`; does not permit summary edits.

### Security and Isolation

- Read-only HTTP surface; only `describe_files` MCP tool accepts notes updates.
- Audit logging records tool, project, caller, and bounded outcome (`ok` / `error: ...`) omitting user summary prose.
- Cross-project requests validated against project root containment and database project boundaries.

### Validation

- `uv run pytest tests/test_codebase_guide_api.py tests/test_integration.py` — 18 passed.
- `just check` — 251 passed, 1 skipped server; 68 vitest passed; production build clean.

### Limitations / Out of Scope

- No UI components or frontend views (T17).
- No integration orchestrator changes (T18).
- No AI provider settings changes (T20).
- New dependencies: None.
