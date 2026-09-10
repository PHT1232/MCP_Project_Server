# Acceptance coverage matrix

Every acceptance criterion from `REQUIREMENTS.md` §10 is mapped to automated or explicit manual evidence. `verified` means an automated assertion exists; `manual` means the criterion inherently requires an external agent, physical device, or release environment not available to the test process.

| AC | State | Evidence |
|---|---|---|
| AC1 | verified | `test_ac1_briefing_includes_all_active_sections_under_budget` |
| AC2 | manual | T09 fresh-agent orientation protocol in `tasks/T09-integration.md`; requires an independent agent and observation of file reads |
| AC3 | verified | `test_ac3_blocker_added_by_one_session_is_in_the_next_briefing` |
| AC4 | verified | `test_ac4_resolve_removes_bug_from_briefing_keeps_archive` |
| AC4a | verified | `test_ac4a_over_budget_collapses_and_store_is_unchanged` |
| AC5 | verified | `test_ac5_projects_are_isolated` |
| AC6 | verified | `test_ac6_engine_reset_preserves_context` proves persistence across engine lifecycle; Compose volume persistence is covered by T08 deployment configuration/review |
| AC7 | manual | T09 controlled token-comparison protocol in `tasks/T09-integration.md`; requires comparable independent agent runs |
| AC8 | verified | `test_ac8_natural_language_query_finds_file_and_symbol` |
| AC9 | verified | `test_ac9_edit_incremental_fresh_and_stale_flagged`; timing added by `test_nfr9_incremental_changed_file_reindexes_within_seconds` |
| AC10 | verified | `test_ac10_no_backend_keyword_results_and_note` |
| AC11 | verified | `test_ac11_top_level_nodes_and_edges_match_module_structure`, `test_ac11_expanding_scope_returns_only_that_subtree`, and T07 live indexed-repository run |
| AC12 | verified | `test_ac12_blocker_and_bug_flag_the_owning_nodes`, `codemap.test.ts` overlay assertions, and T07 live run |
| AC13 | verified | `test_source_returns_file_content`, `codemap.test.ts` related-entry/location assertions, and T07 live inspector run with symbols/dependencies/source |
| AC14 | verified | `test_http_app_and_ac14_http_mcp_share_the_store`, `DashboardEdit.test.tsx`, and T06 live bidirectional check |
| AC14a | verified | requirements service/MCP tests plus `requirements.test.ts`, API tests, and T06 view verification |
| AC15 | verified | `test_ac15_drop_index_schema_rebuild_preserves_context` |
| AC16 | verified | `test_ac16_unknown_and_missing_project_list_registered`, MCP and HTTP integration paths |
| AC17 | verified | `test_ac17_two_edits_two_revisions_deleted_gone_from_reads` |
| AC18 | verified | `test_ac18_add_in_store_writes_a_block_into_the_file`, `test_ac18_file_status_edit_flows_to_the_store`, MCP round trip, and T06 requirements UI path |
| AC19 | verified | `test_ac19_prepare_task_reports_split_within_budget` |
| AC20 | verified | `test_ac20_default_is_top_tier_only_and_expansion_is_scoped` and `codemap.test.ts` subtree-only merge |
| AC21 | verified | `test_ac21_status_shows_semantic_unavailable` and `semantic.test.ts` UI presentation logic |
| AC22 | verified | `test_ac22_status_changed_in_both_store_wins_and_token_rewritten`, `test_ac22_deleted_block_is_archived_and_never_resurrected` |
| AC23 | verified | `test_ac23_tags_fallback_symbol_mode`, `test_ac23_status_dict_reports_modes` |
| AC24 | verified | `test_ac24_small_context_expands_code_pack` |
| AC25 | verified | T08 live clean Compose smoke (health, registration, briefing, frontend) plus `test_ac25_*` deployment assertions |
| AC26 | manual | Bind/Compose policy automated by `test_ac26_*`, `test_s2_*`, and localhost tests; second-device reachability protocol remains in `tasks/T09-integration.md` |
| AC27 | verified | T06/T07 token-only source audit, `tokens.ts` runtime CSS-token bridge, frontend lint/type/build, and design review records |

## Non-functional release gates

| Requirement | Runnable evidence |
|---|---|
| NFR1 | `test_nfr1_typical_briefing_p95_under_200ms` |
| NFR2 | `test_nfr2_briefing_obeys_configured_budget` plus AC1/AC4a tests |
| NFR5 | `server/tests/test_security.py` traversal, symlink, source, SQL-input, and subprocess checks |
| NFR6 | Existing MCP/HTTP audit-log integration tests |
| NFR9 | `test_nfr9_incremental_changed_file_reindexes_within_seconds` |
| NFR10 | `test_nfr10_approximately_100k_loc_full_index_within_minutes` |
| NFR11 | Configuration/provider tests and privacy boundary in `docs/architecture.md` / `docs/configuration.md` |
| NFR13 | T05 240-file top-tier payload test; Sigma WebGL frontend build |
| NFR14 | `test_deploy.py` bind/Compose assertions; AC26 manual second-device protocol |
| NFR15 | T06/T07 design-token audit and frontend static gates |

Run `just accept T09` for performance, security, full tests/build, and Compose lint. Manual criteria are release-operator checks and are not falsely represented as automated tests.
