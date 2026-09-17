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
from pcs.context.service import resolve_project
from pcs.context.types import (
    PREPARE_TASK_TOKEN_CAP,
    PREPARE_TASK_TOKEN_MAX,
    PREPARE_TASK_TOKEN_MIN,
)
from pcs.index.hybrid import gather_relevant
from pcs.index.retrieval import PackedChunk, pack_code_chunks
from pcs.planning import service as planning
from pcs.planning.errors import TaskNotFoundError
from pcs.planning.models import PlanTask
from pcs.planning.types import PlanTaskView, PlanView
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


def _render_task_block(task: PlanTaskView, deps: list[_DependencyStatus]) -> str:
    """The protected identity block: task id, objective, AC, deps (FR-T25).

    Never truncated by the caller — this is what "prioritize task ID,
    objective, required AC IDs, and project name over general context" means
    in practice: everything else (contract detail, code) shrinks first.
    """
    lines = [
        f"## Task Handoff — {task.local_task_id}: {task.title}",
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


def _render_prompt(task_block: str, contract_text: str, code_chunks: list[PackedChunk]) -> str:
    parts = [task_block]
    parts.append("")
    parts.append(contract_text if contract_text else "CONTRACT\n(no linked requirement contracts)")
    if code_chunks:
        parts.append("")
        parts.append("### Relevant code")
        parts.extend(_format_chunk(chunk) for chunk in code_chunks)
    parts.append("")
    parts.append("### Verification")
    parts.append(
        "- Confirm every acceptance criterion above is satisfied before reporting done.\n"
        "- Record evidence for any linked requirement criteria via "
        "record_requirement_evidence.\n"
        "- Report completion using this project's standard handoff template."
    )
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
    budget = _clamp_budget(max_tokens, proj.prepare_task_token_budget or PREPARE_TASK_TOKEN_CAP)

    deps = _dependency_statuses(task, plan)
    task_block = _render_task_block(task, deps)
    task_tokens = estimate_tokens(task_block)
    remaining = max(0, budget - task_tokens)

    query = _canonical_query(task)
    hybrid = await gather_relevant(session, project=project, task=query, scope="project", limit=40)
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
            ranked_paths=[hit.hit.path for hit in hybrid.ranked],
        )
        if task.requirement_ids and contract_cap
        else None
    )
    contract_text = contract.text if contract is not None else ""
    contract_tokens = contract.token_estimate if contract is not None else 0

    code_budget = max(0, remaining - contract_tokens) if have_code else 0
    pack = pack_code_chunks(hybrid, max_tokens=code_budget) if code_budget else None
    code_chunks = pack.chunks if pack is not None else []

    prompt = _render_prompt(task_block, contract_text, list(code_chunks))

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
