# Contract-driven completion — implementation plan

## Problem

PCS stores requirements but does not prove that an agent satisfied each non-negotiable invariant before marking a requirement `done`. A green test suite can therefore coexist with an architecture violation, an unreviewed data path, or stale validation evidence.

## Product outcome

Turn PCS into a compact contract and completion gate without turning every prompt into a requirements dump.

Agents receive a short task contract by default. Full criteria and evidence remain in PostgreSQL and are fetched only on demand. Completion is rejected deterministically when required evidence is missing, stale, or failed.

## Locked decisions

1. **Store much, retrieve little.** Full invariants, acceptance criteria, evidence, and review findings live in PostgreSQL. Default task preparation returns only active contract statements and exception summaries.
2. **Progressive disclosure.** Detail is available through dedicated MCP/HTTP reads; briefing and `prepare_task` do not embed raw logs or diffs.
3. **Hard compact budget.** Contract plus close-gate summary uses at most 500 estimated tokens in `prepare_task`, within its existing total budget. Code keeps the existing FR22a floor.
4. **Deterministic close gate.** Missing evidence, failed evidence, stale commit/worktree provenance, and open blocking violations are evaluated without an LLM.
5. **No automatic inference of project truth.** PCS records evidence supplied by agents/humans and computes freshness/coverage from that record. It does not infer requirement status from CI or source code, preserving D4.
6. **Backward compatibility.** Existing requirement rows and `not-started | in-progress | blocked | done` clients continue to work during migration. New verification state is additive; `done` becomes gated only after criteria are configured for that requirement.
7. **Evidence summaries, not logs.** Store command, exit code, counts, commit/worktree fingerprint, timestamp, and optional external artifact reference. Never place full stdout or full diffs in compact responses.
8. **Independent review is policy-driven.** High-risk criteria can require evidence authored by a caller different from the implementer; normal criteria do not.

## Delivery sequence

```text
T10 Contract model and migration
  ├── T11 Compact contract retrieval and prepare_task integration
  └── T12 Evidence ledger and deterministic close gate
        └── T13 Compliance review API and dashboard
```

T11 and T12 may run in parallel only after T10 is merged. T13 starts after both are merged.

## Data model

- `requirement_invariants`: stable ID, statement, kind, risk, ordering.
- `acceptance_criteria`: stable ID, invariant link, statement, evidence kind, required, independent-review policy.
- `requirement_evidence`: criterion link, evidence kind, result, command/test/file references, source revision, worktree fingerprint, author, timestamp, artifact reference.
- `requirement_violations`: invariant link, severity, summary, file/line reference, status, author, timestamps.
- Requirement verification is derived: criterion coverage, evidence freshness, open blocking violations, and review policy.

Do not store full test logs or source diffs in these tables.

## Compact response contract

Default `prepare_task` addition, maximum 500 estimated tokens:

```text
CONTRACT
Must: <highest-risk active invariants>
Must not: <forbidden-path invariants>

CLOSE GATE
AC: 3/5 verified; missing AC2, AC5
Validation: stale
Review: failed (1 blocking violation)
Details: call get_requirement_contract / get_requirement_evidence
```

Selection order: blocking violations, forbidden-path invariants, high-risk invariants, missing required criteria, stale evidence. Overflow collapses to counts plus drill-down pointers.

## Compatibility and rollout

- Requirements without acceptance criteria retain current status behavior.
- Requirements with configured criteria cannot transition to `done` until the close gate passes.
- Existing `set_requirement_status` remains the public entry point and returns actionable unmet conditions.
- File sync keeps requirement prose/status ownership unchanged. Contract records are store-owned in this MVP; no new Markdown grammar in T10–T13.

## Success measures

- A requirement with missing, failed, or stale required evidence cannot become `done`.
- A high-risk criterion requiring independent review cannot be satisfied by its implementer.
- `prepare_task` returns relevant contract and close-gate state within 500 estimated tokens.
- Raw evidence remains one explicit drill-down call away and is absent from briefing output.
- Existing projects with no criteria behave as before.
- Every new acceptance item has a regression test that fails without the implementation.

## Non-goals

- LLM-based semantic compliance judgement.
- Automatic parsing of prose into invariants.
- Uploading or retaining complete CI logs.
- A general workflow engine.
- Replacing GitHub checks or code review.
- Automatically changing requirement status from test/CI results.

## Agent execution rules

1. Read this plan, the assigned task file, and all referenced FR/D IDs before editing.
2. Translate every unchecked acceptance item into a failing test first where practical.
3. Audit all production entry points named by the task, not only the first matching function.
4. Keep response budgets deterministic and test exact overflow behavior.
5. Run focused tests, then `just check`.
6. Update only the assigned task checklist and handoff. Do not mark roadmap state `merged`.
7. Do not weaken checks, add wildcard suppressions, or bypass the close gate for tests.
