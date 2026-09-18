"""Planned-task handoff prompt generation (T25, INV-PLAN-5).

Turns one ``plan_tasks`` row into a bounded, role-neutral Markdown prompt an
implementation agent can act on directly: objective, acceptance criteria,
dependency status, and linked requirement contracts. Never emits claim
tokens, provider keys, evidence logs, or raw diffs — ``PlanTaskView`` never
carries a token in the first place (T24), and the contract text already
filters log/diff-shaped evidence (T11, ``briefing._sanitize_summary``).

No MCP or HTTP transport imports (AGENTS.md).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.assembly import estimate_tokens
from pcs.context.relevance import (
    CONTEXT_ENTRIES_TOKEN_CAP,
    CONTEXT_ENTRIES_TOKEN_FLOOR,
    CONTEXT_ENTRY_MIN_TOKENS,
    fit_text,
    paths_from_text,
    select_relevant_context_entries,
)
from pcs.context.service import get_section, resolve_project
from pcs.context.types import (
    PREPARE_TASK_TOKEN_CAP,
    PREPARE_TASK_TOKEN_MAX,
    PREPARE_TASK_TOKEN_MIN,
    SECTION_CONVENTIONS,
    SECTION_DECISIONS,
    SECTION_FOCUS,
    EntryView,
)
from pcs.index.hybrid import gather_relevant
from pcs.index.retrieval import PackedChunk, pack_code_chunks
from pcs.planning import service as planning
from pcs.planning.errors import TaskAlreadyTerminalError, TaskNotFoundError
from pcs.planning.models import PlanTask
from pcs.planning.types import TERMINAL_TASK_STATUSES, PlanTaskView, PlanView
from pcs.requirements.briefing import CONTRACT_TOKEN_CAP, get_task_contract
from pcs.token_savings.baseline import full_file_tokens
from pcs.token_savings.service import record_token_savings

if TYPE_CHECKING:
    from pcs.db.models import Project

__all__ = ["render_handoff_prompt"]

logger = logging.getLogger("pcs")


async def _record_handoff_baseline(
    session: AsyncSession,
    *,
    project_id: str,
    root_path: str,
    caller: str,
    actual_tokens: int,
    task_tokens: int,
    contract_tokens: int,
    ranked_paths: Iterable[str],
) -> None:
    """Best-effort: baseline = the never-truncated task block (baseline ==
    actual there) + the contract sub-part (same simplification as
    prepare_task's free-text form — capped at 500 tokens regardless, so its
    contribution to the total is small) + full on-disk content of every
    distinct path hybrid search found relevant. Never raises."""
    try:
        code_baseline = full_file_tokens(root_path, ranked_paths)
        baseline = task_tokens + contract_tokens + code_baseline
        await record_token_savings(
            session,
            project_id=project_id,
            operation="prepare_task",
            caller=caller,
            actual_tokens=actual_tokens,
            baseline_tokens=baseline,
        )
    except Exception:
        logger.warning(
            "token_savings_record_failed", extra={"context": {"operation": "prepare_task"}}
        )


@dataclass(frozen=True)
class _DependencyStatus:
    task_id: str
    local_task_id: str
    title: str
    status: str
    completed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "local_task_id": self.local_task_id,
            "title": self.title,
            "status": self.status,
            "completed": self.completed,
        }


async def _resolve_task(
    session: AsyncSession, *, project: str, task_id: str
) -> tuple[Project, PlanView, PlanTaskView]:
    """Resolve ``task_id`` to its plan within ``project`` only (FR-T25, D3).

    ``plan_tasks`` has a database-level ``(id, project_id)`` unique constraint
    (T23), so a single project-scoped lookup both finds the task and rejects a
    cross-project id in one step, without trusting a caller-supplied plan_id.
    """
    proj = await resolve_project(session, project)
    result = await session.execute(
        select(PlanTask.plan_id).where(
            PlanTask.id == task_id,
            PlanTask.project_id == proj.id,
        )
    )
    plan_id = result.scalar_one_or_none()
    if plan_id is None:
        raise TaskNotFoundError(task_id, project=proj.name)

    plan = await planning.get_plan(session, project=project, plan_id=plan_id)
    task = next((t for t in plan.tasks if t.id == task_id), None)
    if task is None:  # pragma: no cover - defensive; the row lookup above already found it
        raise TaskNotFoundError(task_id, plan_id, proj.name)
    return proj, plan, task


def _canonical_query(task: PlanTaskView) -> str:
    """Retrieval query from title, objective, and linked files.

    Deliberately excludes acceptance_criteria: they're checklist items, not
    descriptions of what to search for, and concatenating every one of them
    onto an already-long objective mostly adds length and noise rather than
    retrieval signal. That extra length has a real cost — keyword_search's
    fuzzy `similarity()` scoring runs against every WHERE-matched chunk (not
    just the returned limit), so a shorter, more focused query is both
    cheaper and, if anything, more precise. Acceptance criteria are still
    shown to the agent in full via _render_task_block; this only affects what
    gets searched for related code, not what's reported in the prompt.
    """
    parts = [task.title, task.objective, *task.linked_files]
    return "\n".join(part for part in parts if part)


def _dependency_statuses(task: PlanTaskView, plan: PlanView) -> list[_DependencyStatus]:
    by_id = {t.id: t for t in plan.tasks}
    statuses: list[_DependencyStatus] = []
    for dep_id in task.dependencies:
        dep = by_id.get(dep_id)
        if dep is None:  # pragma: no cover - defensive; DAG FKs guarantee this can't happen
            continue
        statuses.append(
            _DependencyStatus(
                task_id=dep.id,
                local_task_id=dep.local_task_id,
                title=dep.title,
                status=dep.status,
                completed=dep.status == "completed",
            )
        )
    statuses.sort(key=lambda d: d.local_task_id)
    return statuses


def _render_task_block(
    project_name: str, plan_id: str, task: PlanTaskView, deps: list[_DependencyStatus]
) -> str:
    """The protected identity block: task id, objective, AC, deps (FR-T25).

    Never truncated by the caller — this is what "prioritize task ID,
    objective, required AC IDs, and project name over general context" means
    in practice: everything else (contract detail, code) shrinks first.

    The "Required: use pcs" section exists because this prompt is designed to
    be copy-pasted into a *different* agent/session that has none of this
    project's own instructions loaded (no CLAUDE.md/AGENTS.md mandate to use
    pcs, possibly not even pcs configured) — deferring to "read AGENTS.md
    first" alone was observed to get skipped by weaker models that just act
    on the self-contained task/code text below it. Tool calls are spelled out
    with project/plan_id/task_id already filled in so a cold-started agent
    can act on them directly instead of inferring conventions, and the intro
    line explicitly says "mandatory, not optional" — a plain description of
    available tools reads as informational and was observed to still get
    skipped by weaker models; framing it as a requirement is more resistant
    to that. The explicit "claim_task failing doesn't mean pcs is broken"
    line exists because a weak model, given a claim_task error and no
    guidance distinguishing it from a real outage, was observed to abandon
    pcs entirely for the rest of the task instead of reading the error and
    continuing with search_code/retrieve_context/complete_task as normal —
    the only existing guidance on that distinction (onboarding_tools.TOOL_USAGE)
    is returned solely by the separate `onboard` bootstrap tool, which a
    cold-started agent given just this copied prompt never calls.
    """
    lines = [
        f"## Task Handoff — {task.local_task_id}: {task.title}",
        "",
        "### Required: use pcs for this task's lifecycle",
        f'This is a pcs MCP-tracked task — project "{project_name}", plan {plan_id}, '
        f"task {task.id}. The steps below are mandatory, not optional suggestions: "
        "do not start editing before claiming the task, and do not report this "
        "task done without calling complete_task.",
        f'- Claim it first: claim_task(project="{project_name}", plan_id="{plan_id}", '
        f'task_id="{task.id}", claimed_by="<your agent/session name>"). Keep the '
        "claim_token it returns — heartbeat_task and complete_task both need it.",
        "- If claim_task fails, that is a normal outcome sometimes (already claimed, "
        "unmet dependencies, wrong status) — its error message says which. It is NOT "
        "a sign pcs itself is broken or unavailable: keep using search_code / "
        "retrieve_context / get_code_map / complete_task normally, and tell the user "
        "the specific error instead of silently abandoning the task or pcs entirely.",
        "- Call heartbeat_task periodically (same project/plan_id/task_id/claim_token) "
        "to keep the lease alive while working.",
        "- For anything beyond the code already included below, use search_code / "
        "retrieve_context / get_code_map instead of ad hoc grep or file reads.",
        f'- When finished: complete_task(project="{project_name}", plan_id="{plan_id}", '
        f'task_id="{task.id}", claim_token=<the token from claim_task>) — a prose '
        '"done" report alone does not update this task\'s status.',
        "",
        "Read AGENTS.md first and respect its declared file scope. Do not touch "
        "files outside this task's ownership without checking for conflicts.",
        "",
        "### Objective",
        task.objective,
        "",
        "### Acceptance criteria",
    ]
    if task.acceptance_criteria:
        lines.extend(f"- [ ] {item}" for item in task.acceptance_criteria)
    else:
        lines.append("- [ ] (none recorded — confirm scope with the plan owner before starting)")
    lines.append("")
    lines.append("### Dependencies")
    if deps:
        for dep in deps:
            marker = "done" if dep.completed else dep.status
            lines.append(f"- {dep.local_task_id} ({marker}): {dep.title}")
    else:
        lines.append("- None")
    if task.linked_files:
        lines.append("")
        lines.append("### Declared file scope")
        lines.extend(f"- {path}" for path in task.linked_files)
    return "\n".join(lines)


def _format_chunk(chunk: PackedChunk) -> str:
    header = f"`{chunk.path}:{chunk.start_line}-{chunk.end_line}`"
    lang = chunk.language or ""
    return f"{header}\n```{lang}\n{chunk.content}\n```"


def _render_context_entries(
    conventions: list[EntryView],
    decisions: list[EntryView],
    omitted_conventions: int,
    omitted_decisions: int,
    *,
    max_tokens: int,
) -> tuple[str, str]:
    """Render selected conventions/decisions into ``(conventions_md, decisions_md)``.

    Splits ``max_tokens`` evenly across every selected entry (both sections
    combined) — the whole rendered line (headline + markdown scaffold +
    detail), not just the detail text. An entry whose full line wouldn't fit
    is truncated via ``fit_text`` on its detail; if what's left for detail
    after the headline+scaffold overhead is below CONTEXT_ENTRY_MIN_TOKENS
    (too little room for a meaningful truncated snippet), it's dropped
    entirely rather than shown as a near-empty stub. Either return is "" when
    nothing was selected for that section — the caller omits the heading
    entirely rather than a "(none)" placeholder (these are supplementary,
    unlike CONTRACT).
    """
    total_selected = len(conventions) + len(decisions)
    if total_selected == 0 or max_tokens <= 0:
        return "", ""
    # Reserve worst-case room for both sections' heading + drill-down lines
    # up front — they're outside the per-entry split but still count against
    # max_tokens. Whether a given section actually renders isn't known yet
    # (depends on scoring/truncation below), so reserve for both unconditionally;
    # it's a small, fixed cost against the 400-token cap.
    reserved = sum(
        estimate_tokens(text)
        for text in (
            "### Relevant conventions",
            "### Relevant decisions",
            'Details: call get_section(section="conventions")',
            'Details: call get_section(section="decisions")',
        )
    )
    per_entry = max(0, max_tokens - reserved) // total_selected

    def render_section(heading: str, section: str, entries: list[EntryView], omitted: int) -> str:
        lines: list[str] = []
        needs_drill_down = omitted > 0
        for entry in entries:
            # per_entry bounds the WHOLE rendered line, not just the detail
            # text — the "- **{headline}**: " scaffold counts against it too,
            # otherwise longer headlines would push the actual line past the
            # intended per-entry share (and the section's CONTEXT_ENTRIES_TOKEN_CAP).
            prefix = f"- **{entry.headline}**: "
            overhead = estimate_tokens(prefix)
            detail_budget = max(0, per_entry - overhead)
            if overhead + estimate_tokens(entry.detail) > per_entry:
                if detail_budget < CONTEXT_ENTRY_MIN_TOKENS:
                    needs_drill_down = True
                    continue
                needs_drill_down = True
            detail = fit_text(entry.detail, detail_budget) if entry.detail else ""
            line = f"{prefix}{detail}" if detail else f"- **{entry.headline}**"
            lines.append(line)
        if not lines:
            return ""
        parts = [heading, *lines]
        if needs_drill_down:
            parts.append(f'Details: call get_section(section="{section}")')
        return "\n".join(parts)

    conventions_text = render_section(
        "### Relevant conventions", SECTION_CONVENTIONS, conventions, omitted_conventions
    )
    decisions_text = render_section(
        "### Relevant decisions", SECTION_DECISIONS, decisions, omitted_decisions
    )
    return conventions_text, decisions_text


def _render_prompt(
    task_block: str,
    contract_text: str,
    conventions_text: str,
    decisions_text: str,
    code_chunks: list[PackedChunk],
    has_requirement_ids: bool,
) -> str:
    parts = [task_block]
    parts.append("")
    parts.append(contract_text if contract_text else "CONTRACT\n(no linked requirement contracts)")
    if conventions_text:
        parts.append("")
        parts.append(conventions_text)
    if decisions_text:
        parts.append("")
        parts.append(decisions_text)
    if code_chunks:
        parts.append("")
        parts.append("### Relevant code")
        parts.extend(_format_chunk(chunk) for chunk in code_chunks)
    parts.append("")
    parts.append("### Verification")
    verification = [
        "- Confirm every acceptance criterion above is satisfied before reporting done."
    ]
    # Only mention record_requirement_evidence when there's actually a linked
    # requirement to record it against — otherwise it's a dead reference next
    # to "(no linked requirement contracts)" above, easy to misread as a step
    # to perform anyway.
    if has_requirement_ids:
        verification.append(
            "- Record evidence for the linked requirement criteria via "
            "record_requirement_evidence before calling complete_task."
        )
    verification.append(
        "- Call complete_task to close this out — a prose report alone is not enough."
    )
    parts.append("\n".join(verification))
    return "\n".join(parts)


def _clamp_budget(value: int | None, default: int) -> int:
    if value is None:
        return default
    if not PREPARE_TASK_TOKEN_MIN <= value <= PREPARE_TASK_TOKEN_MAX:
        raise ValueError(
            f"max_tokens must be in [{PREPARE_TASK_TOKEN_MIN}, {PREPARE_TASK_TOKEN_MAX}] (FR9g/D13)"
        )
    return value


async def render_handoff_prompt(
    session: AsyncSession,
    *,
    project: str,
    task_id: str,
    max_tokens: int | None = None,
    caller: str | None = None,
) -> dict[str, object]:
    """Bounded, role-neutral Markdown handoff prompt for one planned task (T25, INV-PLAN-5).

    Task identity (id, objective, required AC, project name) is never
    truncated; the linked-contract and code-context sections shrink first
    when the budget is tight, mirroring ``prepare_task``'s existing split
    (contract capped, unused budget spills to code, 30% code floor when
    relevant chunks exist) but rebased on the budget left over after the
    protected task block.
    """
    if not task_id.strip():
        raise ValueError("task_id must not be empty")
    proj, plan, task = await _resolve_task(session, project=project, task_id=task_id)
    if task.status in TERMINAL_TASK_STATUSES:
        raise TaskAlreadyTerminalError(task.id, task.status)
    budget = _clamp_budget(max_tokens, proj.prepare_task_token_budget or PREPARE_TASK_TOKEN_CAP)

    deps = _dependency_statuses(task, plan)
    task_block = _render_task_block(proj.name, plan.id, task, deps)
    task_tokens = estimate_tokens(task_block)
    remaining = max(0, budget - task_tokens)

    query = _canonical_query(task)
    hybrid = await gather_relevant(session, project=project, task=query, scope="project", limit=40)
    ranked_paths = [hit.hit.path for hit in hybrid.ranked]
    have_code = bool(hybrid.ranked)
    code_floor = (remaining * 3) // 10 if have_code else 0
    contract_cap = min(CONTRACT_TOKEN_CAP, max(0, remaining - code_floor))

    contract = (
        await get_task_contract(
            session,
            project=project,
            task=query,
            requirement_ids=list(task.requirement_ids),
            max_tokens=max(contract_cap, 80) if contract_cap else 80,
            # Reuse the already-ranked paths from gather_relevant above so
            # get_task_contract doesn't redundantly re-run the same
            # keyword+semantic search from scratch (it defaults to doing so
            # whenever ranked_paths is omitted) — this was doubling the
            # latency of every prepare_task call.
            ranked_paths=ranked_paths,
        )
        if task.requirement_ids and contract_cap
        else None
    )
    contract_text = contract.text if contract is not None else ""
    contract_tokens = contract.token_estimate if contract is not None else 0

    # A convention/decision explicitly linked to one of this task's own
    # requirements (either passed in directly or auto-selected by the
    # contract above) is a strong, domain-specific relevance signal.
    related_requirement_ids = frozenset(task.requirement_ids) | frozenset(
        contract.requirement_ids if contract is not None else ()
    )
    entries_cap = min(CONTEXT_ENTRIES_TOKEN_CAP, max(0, remaining - contract_tokens - code_floor))
    conventions: list[EntryView] = []
    decisions: list[EntryView] = []
    omitted_conventions = omitted_decisions = 0
    if entries_cap >= CONTEXT_ENTRIES_TOKEN_FLOOR:
        focus_entries = await get_section(session, project=project, section=SECTION_FOCUS)
        focus_text = " ".join(f"{e.headline} {e.detail}" for e in focus_entries)
        focus_paths = [
            *paths_from_text(query, focus_text),
            *[p for e in focus_entries for p in e.linked_files],
        ]
        conventions, omitted_conventions = await select_relevant_context_entries(
            session,
            project=project,
            section=SECTION_CONVENTIONS,
            task=query,
            focus_text=focus_text,
            focus_paths=focus_paths,
            ranked_paths=ranked_paths,
            related_requirement_ids=related_requirement_ids,
        )
        decisions, omitted_decisions = await select_relevant_context_entries(
            session,
            project=project,
            section=SECTION_DECISIONS,
            task=query,
            focus_text=focus_text,
            focus_paths=focus_paths,
            ranked_paths=ranked_paths,
            related_requirement_ids=related_requirement_ids,
        )
    conventions_text, decisions_text = _render_context_entries(
        conventions, decisions, omitted_conventions, omitted_decisions, max_tokens=entries_cap
    )
    entries_tokens = estimate_tokens(conventions_text) + estimate_tokens(decisions_text)

    code_budget = max(0, remaining - contract_tokens - entries_tokens) if have_code else 0
    pack = pack_code_chunks(hybrid, max_tokens=code_budget) if code_budget else None
    code_chunks = pack.chunks if pack is not None else []

    prompt = _render_prompt(
        task_block,
        contract_text,
        conventions_text,
        decisions_text,
        list(code_chunks),
        bool(task.requirement_ids),
    )

    if caller is not None:
        await _record_handoff_baseline(
            session,
            project_id=proj.id,
            root_path=proj.root_path,
            caller=caller,
            actual_tokens=estimate_tokens(prompt),
            task_tokens=task_tokens,
            contract_tokens=contract_tokens,
            ranked_paths=(r.hit.path for r in hybrid.ranked),
        )

    return {
        "project": proj.name,
        "task_id": task.id,
        "plan_id": plan.id,
        "local_task_id": task.local_task_id,
        "prompt": prompt,
        "token_estimate": estimate_tokens(prompt),
        "dependencies": [d.as_dict() for d in deps],
        "requirement_ids": list(task.requirement_ids),
        "split": {
            "budget": budget,
            "task_tokens": task_tokens,
            "contract_tokens": contract_tokens,
            "contract_cap": contract_cap,
            "context_entries_tokens": entries_tokens,
            "code_tokens": pack.token_estimate if pack is not None else 0,
            "code_budget": code_budget,
            "code_floor": code_floor if have_code else 0,
        },
        "truncated": bool(
            (pack is not None and pack.truncated) or (contract is not None and contract.truncated)
        ),
        "semantic_available": hybrid.semantic_available,
        "mode": "hybrid" if hybrid.semantic_available else "keyword",
        "semantic_note": hybrid.semantic_note,
    }
