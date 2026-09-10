# Acceptance coverage matrix

Every `AC` from REQUIREMENTS.md §10, the task that owns it, and its verification
state. I update the last two columns during review; T09 closes any gaps and
confirms the whole column is green.

State: `—` not started · `wip` in progress · `claimed` agent says done ·
`verified` I confirmed a test proves it · `gap` needs a test (T09).

| AC | What it checks | Owner | Also touches | State | Test / note |
|----|----------------|-------|--------------|-------|-------------|
| AC1 | Briefing returns all sections under budget | T01 | T00 (seed) | verified | `test_ac1_briefing_includes_all_active_sections_under_budget` |
| AC2 | Agent orients from briefing alone, no stray file reads | T09 | T01 | — | qualitative E2E |
| AC3 | Blocker added by one agent seen by the next | T01 | | verified | `test_ac3_blocker_added_by_one_session_is_in_the_next_briefing` |
| AC4 | Resolve removes from briefing, keeps archive | T01 | | verified | `test_ac4_resolve_removes_bug_from_briefing_keeps_archive` |
| AC4a | Over-budget → headlines + counts + drill-down; store unchanged | T01 | | verified | `test_ac4a_over_budget_collapses_and_store_is_unchanged` |
| AC5 | Two projects isolated, no leakage | T01 | T00 | verified | `test_ac5_projects_are_isolated` |
| AC6 | Restart preserves context | T01 | T00 | verified | `test_ac6_engine_reset_preserves_context` |
| AC7 | Fewer orientation tokens vs. baseline | T09 | T01, T04 | — | measured run |
| AC8 | NL query → right file+symbol in top results | T04 | | — | |
| AC9 | Edit file → fresh result in seconds; stale flagged | T03 | T04 | — | |
| AC10 | No embedding backend → keyword results + notice | T04 | | — | |
| AC11 | Code map top-level nodes match real modules + edges | T05 | T07 | — | |
| AC12 | Open blocker/bug marked on its node | T05 | T07 | — | |
| AC13 | Node select → inspector (source, deps, related context) | T07 | T05 | — | |
| AC14 | Frontend edit ↔ next briefing (both directions) | T06 | T01 | server-side verified | T01 `test_http_app_and_ac14_http_mcp_share_the_store` (HTTP write ↔ MCP briefing); frontend half is T06 |
| AC14a | Requirements view N/M accurate; store ↔ file both reflected | T06 | T02 | — | |
| AC15 | Drop index schema + restart → clean rebuild, context intact | T03 | | — | |
| AC16 | Missing/unknown project → error listing projects, no guess | T01 | T00 | verified | `test_ac16_unknown_and_missing_project_list_registered` + MCP/HTTP paths |
| AC17 | Two edits → two revisions; deleted entry gone from reads, in history | T01 | | verified | `test_ac17_two_edits_two_revisions_deleted_gone_from_reads` |
| AC18 | Add requirement in frontend → block in file; file edit + sync → store+view | T02 | T06 | — | |
| AC19 | `prepare_task` = briefing + code in one response, adaptive split | T04 | | — | |
| AC20 | `get_code_map` default = top-level only; expand = lazy children | T05 | T07 | — | |
| AC21 | No embedding backend → frontend + `get_index_status` show unavailable | T04 | T06 | — | |
| AC22 | Status conflict → store wins, file token rewritten, reconciliation reported; deleted block archived | T02 | | — | |
| AC23 | Supported language, no SCIP indexer → tags fallback, status shows mode | T04 | | — | |
| AC24 | `prepare_task` reports split; small context → code expands | T04 | | — | |
| AC25 | `docker compose up` clean → register + briefing with only mount config | T08 | | — | |
| AC26 | Tailscale on → tailnet-only reachable; off → localhost only | T08 | | — | |
| AC27 | Frontend computed styles = DESIGN.md tokens; no "Don't"-list violations | T06 | T07 | — | |

## NFR checks (T09 unless noted)

| NFR | Check | Owner |
|-----|-------|-------|
| NFR1 | Briefing fetch < 200 ms | T09 (T01 builds it) |
| NFR2 | Briefing ≤ configured budget (default 1,500 tok) | T01 / T09 |
| NFR6 | Every tool call logs project/caller/outcome | T00 → all |
| NFR9 | Incremental reindex of a changed file within seconds | T03 |
| NFR10 | Medium repo (~100k LOC) full index in minutes; embed cache by hash | T03 / T04 |
| NFR11 | Data leaves host only via configured backend or the tailnet | T04 / T08 |
| NFR13 | Frontend responsive regardless of repo size (server aggregation) | T05 / T07 |
| NFR14 | Bind localhost by default; tailnet only otherwise; never public/LAN | T00 / T08 |
| NFR15 | Single token-driven theme layer; components use tokens not literals | T06 / T07 |
