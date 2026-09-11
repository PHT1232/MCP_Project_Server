# T11 — Compact contract retrieval

**Branch:** `task/T11-compact-contract-retrieval`  ·  **Depends on:** T10  ·  **Can run with:** T12  ·  **Blocks:** T13

## Goal

Expose relevant requirement contracts through progressive disclosure and add a hard-bounded contract/close-gate summary to `prepare_task` without reducing its code-context floor.

## Owned files/modules

- New `server/src/pcs/requirements/briefing.py`
- `server/src/pcs/mcp/index_tools.py`
- `server/src/pcs/mcp/tools.py` or a new requirement-contract registration module
- `server/src/pcs/mcp/server.py` only for registration
- `server/src/pcs/index/retrieval.py` only where `prepare_task` assembly requires it
- New focused tests for compact contract retrieval and task preparation
- `docs/mcp-reference.md`

Do not edit DB models/migrations, requirement status transitions, evidence writes, or frontend code.

## Requirements

- Add `get_requirement_contract(project, requirement_id, include)` for verbatim drill-down. `include` can select invariants, criteria, or both.
- Add `get_task_contract(project, task, requirement_ids?, max_tokens=500)` returning only relevant active contract statements and a compact close-gate summary.
- Extend `prepare_task` with a contract allocation capped at 500 estimated tokens and included inside the existing total budget.
- Preserve FR22a: curated context remains capped, code retains its floor when chunks exist, and unused contract budget spills to code.
- Deterministic selection order: blocking violations summary, forbidden paths, high-risk invariants, missing criteria, stale evidence. T12 data may be absent; represent it as `review: not-configured`, not an error.
- Never include raw evidence logs, full diffs, or unrelated requirements.
- Overflow becomes counts plus explicit drill-down tool names.
- Requirements are selected from explicit IDs first, then linked files/focus/retrieval relevance. Limit normal output to 1–3 requirements.

## Acceptance checklist

- [x] Empty/unconfigured contracts add negligible output and preserve current `prepare_task` behavior — `test_empty_unconfigured_contracts_preserve_prepare_task_behavior`
- [x] Contract section is at most 500 estimated tokens under adversarial long input — `test_contract_section_caps_at_500_tokens_under_adversarial_input`
- [x] Total `prepare_task` response remains within its requested budget — `test_prepare_task_total_stays_within_requested_budget`
- [x] Existing FR22a code floor remains satisfied when code chunks exist — `test_fr22a_code_floor_holds_when_code_chunks_exist`
- [x] Relevant forbidden/high-risk statements outrank low-risk prose deterministically — `test_forbidden_and_high_risk_outrank_low_risk_prose_deterministically`
- [x] Overflow reports omitted counts and drill-down pointers — `test_overflow_reports_omitted_counts_and_drill_down_pointers`
- [x] Full invariant/criterion detail is available only through explicit drill-down — `test_full_detail_available_only_through_explicit_drill_down`
- [x] Responses contain no raw command output or diff bodies — `test_responses_contain_no_raw_command_output_or_diff_bodies`
- [x] Every acceptance item has a regression test (plus no-match emptiness, criterion-to-invariant mapping, global overflow eviction, structured fallback, actual code token floor, narrow ImportError, explicit-ID dedupe/done, project isolation, MCP audit/schema/errors)
- [x] Focused tests and `just check` pass — `uv run pytest -k 'task_contract or prepare_task'` 21 passed; `just check` green (172 passed, 1 skipped)
- [x] Handoff documents exact budget accounting and relevance rules

## Verification

```bash
cd server && uv run pytest -k 'task_contract or prepare_task'
just check
```

## Handoff

Status: **in progress** — re-review of `13c7d2f` is implemented on `task/T11-compact-contract-retrieval`. R-060 stays **blocked** pending independent review. Not marking done; findings are not resolved.

### Budget accounting (`prepare_task`, FR22a + T11)

Let `B` be the clamped total (`1000`–`16000`; default project `prepare_task_token_budget`, usually 4000).

| Bucket | Cap / floor | Source |
|--------|-------------|--------|
| Curated context | `context_cap = B // 2` (50%) | unchanged FR22a |
| Code (when chunks exist) | `code_floor = (B * 3) // 10` (30%) | unchanged FR22a |
| Contract + close-gate | `contract_cap = min(500, B)` | T11; `pcs.requirements.briefing.CONTRACT_TOKEN_CAP` |
| Token estimate | `ceil(chars / 4)` | `pcs.context.assembly.estimate_tokens` (D13) |

Assembly order:

1. One `gather_relevant` call (shared with the code pack).
2. `get_task_contract(..., max_tokens=contract_cap, ranked_paths=hybrid paths)` → `contract_tokens`.
3. `remaining = B - contract_tokens`.
4. Briefing still assembled against **`context_cap` of total `B`**, not of `remaining`.
5. If code exists and `context_tokens > remaining - code_floor`, regenerate the briefing tighter.
6. `code_budget = remaining - context_tokens` when chunks exist (else 0).

Empty/unconfigured contracts return `text=""` and `contract_tokens=0`, so the split matches pre-T11. Unused contract budget **spills to code**, it is not reserved as a 500-token hole. Split reports `contract_tokens` and `contract_cap`.

### Relevance and packing

- **Requirements (1-3):** explicit `requirement_ids` first (deduplicated, first-seen order, including `done`). Otherwise open, non-`done` requirements that have active invariants. Match score is linked-files ∩ retrieval paths / focus paths / task text, plus `req_key`/title token overlap. No-match auto-select returns empty — never a fallback dump of unrelated contracts.
- **Statements:** blocking-violation summaries (T12) → `forbidden-path` → high-risk → missing required criteria → stale evidence → remaining by risk/`sort_order`/`key`. Missing/stale criteria map to parents by **criterion UUID** or `(invariant_id, key)` — never a global `AC-1` map. A payload parent is used only when T10 cannot resolve the criterion, or when it exactly agrees with T10; conflicting `invariant_id` / `invariant_key` values are ignored. Overflow evicts the globally lowest-ranked included line. `get_task_contract` rejects `max_tokens` outside 80–500 so every accepted budget satisfies `token_estimate <= token_budget`. Documents are never character-sliced.
- **T12 absent:** `review: not-configured` (also AC/Validation). Optional seam: `pcs.requirements.evidence.summarize_close_gate(session, *, project, requirement_ids) -> Mapping`. Only compact keys are copied (`ac_verified`, `ac_total`, `missing_keys` display-only, `missing`/`stale` links, `validation`, `review`, `blocking`, `stale_count`). **Stale payload:** `stale: [{"id": "<criterion uuid>"}]` (optional `key` / `invariant_id`); `stale_count` defaults to `len(stale)` and ranking boosts that criterion's T10 parent. A missing evidence *module* is not-configured; any other `ModuleNotFoundError` (broken T12 import) propagates. Stdout/diffs are dropped or replaced with `(omitted)`.
- **Drill-down:** `get_requirement_contract(..., include=invariants|criteria|both)` returns verbatim T10 views. Compact output never embeds full criterion statements or evidence bodies.

### Files

- New `server/src/pcs/requirements/briefing.py` (service; no MCP/HTTP)
- New `server/src/pcs/mcp/contract_tools.py` (registration; `tools.py` untouched)
- `server/src/pcs/mcp/server.py` registration only
- `server/src/pcs/index/retrieval.py` `prepare_task` assembly
- `server/src/pcs/mcp/index_tools.py` docstring
- `server/tests/test_task_contract.py`, `EXPECTED_TOOLS` in `test_integration.py`
- `docs/mcp-reference.md`, this file, `ROADMAP.md` → T11 **in progress**

### Out of scope (unchanged)

DB models/migrations, `set_requirement_status` gating, evidence writes, frontend, T12/T13 task files.

### Cross-task

T12: implement `summarize_close_gate` and `get_requirement_evidence`. T11 already points at those names and will consume the seam without a follow-up edit if the payload keys match. T13 must not start.

### Review fixes (post-f3ca46c)

- No-match relevance is empty (`test_no_match_relevance_returns_empty_contract`).
- Criterion-to-invariant priority uses T10 ids (`test_missing_criterion_maps_to_parent_invariant_not_key_prefix`).
- Global overflow eviction + intact headings (`test_global_overflow_eviction_keeps_highest_rank_and_headers`).
- Structured fallback for tiny budgets (`test_tiny_budget_uses_structured_fallback_not_sliced_headers`).
- Actual `code_tokens >= code_floor` with a bulky index (`test_fr22a_code_floor_holds_when_code_chunks_exist`).
- Narrow `ModuleNotFoundError` on `pcs.requirements.evidence` only (`test_broken_t12_import_is_not_hidden_as_not_configured`).
- Explicit-ID dedupe + `done` inclusion (`test_explicit_ids_are_deduped_and_done_ids_are_included`).
- Project isolation (`test_contract_tools_are_project_isolated`).
- MCP schema/audit/errors (`test_mcp_contract_tools_audit_schema_and_errors`).

### Review fixes (post-13c7d2f)

- Safe minimum 80: reject `max_tokens < 80` in service, MCP schema (`minimum`/`maximum`), docs, and tests (`test_below_safe_minimum_is_rejected`, `test_accepted_budget_token_estimate_never_exceeds_budget`). `prepare_task` still uses `min(500, B)` (always ≥ 80).
- Criterion ownership is id-scoped (`test_duplicate_ac_keys_across_requirements_use_criterion_ids`).
- Conflicting payload parents lose to T10 (`test_conflicting_payload_parent_uses_authoritative_owner`).
- T12 stale `{id}` boosts the parent invariant (`test_stale_criterion_raises_parent_invariant_in_ranking`).

### Focused tests

`cd server && uv run pytest tests/test_task_contract.py` → 25 passed. `just check` green: 177 passed / 1 skipped (server), 56 vitest. Status stays **in progress** / R-060 **blocked** pending independent re-review; not marking done.
