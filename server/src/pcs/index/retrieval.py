"""Token-bounded relevant-code packs: ``retrieve_context`` and ``prepare_task``.

FR22 / FR22a / D13. Built on hybrid search — no FTS/vector SQL here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.assembly import assemble_briefing, estimate_tokens
from pcs.context.service import get_project_briefing, load_assembly_entries, resolve_project
from pcs.context.types import (
    PREPARE_TASK_TOKEN_CAP,
    PREPARE_TASK_TOKEN_MAX,
    PREPARE_TASK_TOKEN_MIN,
)
from pcs.db.models import Project
from pcs.index.hybrid import HybridResult, gather_relevant
from pcs.index.search import SearchScopeName
from pcs.requirements.briefing import CONTRACT_TOKEN_CAP, get_task_contract
from pcs.token_savings.baseline import full_file_tokens
from pcs.token_savings.service import record_token_savings

# Baseline briefing assembly uses an effectively unlimited budget so nothing
# gets truncated/summarized — same order of magnitude used in context/service.py.
_UNBOUNDED_BUDGET = 10_000_000

logger = logging.getLogger("pcs")


async def _record_code_baseline(
    session: AsyncSession,
    *,
    project: str,
    operation: str,
    caller: str,
    actual_tokens: int,
    ranked_paths: Iterable[str],
) -> None:
    """Best-effort: baseline = full on-disk content of every distinct relevant
    path hybrid search found (not just what fit the budget). Never raises —
    a logging failure must not break the retrieval call it describes."""
    try:
        row = await resolve_project(session, project)
        baseline = full_file_tokens(row.root_path, ranked_paths)
        await record_token_savings(
            session,
            project_id=row.id,
            operation=operation,
            caller=caller,
            actual_tokens=actual_tokens,
            baseline_tokens=baseline,
        )
    except Exception:
        logger.warning("token_savings_record_failed", extra={"context": {"operation": operation}})


@dataclass(frozen=True)
class PackedChunk:
    """One code chunk selected for a prompt-injection pack (FR22)."""

    path: str
    start_line: int
    end_line: int
    symbol: str | None
    language: str | None
    content: str
    score: float
    matched_mode: str
    stale: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "symbol": self.symbol,
            "language": self.language,
            "content": self.content,
            "score": self.score,
            "matched_mode": self.matched_mode,
            "stale": self.stale,
        }


@dataclass(frozen=True)
class CodePack:
    """A budgeted set of code chunks plus how it was assembled."""

    chunks: list[PackedChunk]
    token_estimate: int
    truncated: bool
    semantic_available: bool


def _cost(chunk: PackedChunk) -> int:
    return estimate_tokens(f"// {chunk.path}:{chunk.start_line}-{chunk.end_line}\n{chunk.content}")


def pack_code_chunks(hybrid: HybridResult, *, max_tokens: int) -> CodePack:
    """Greedily fill ``max_tokens`` with the highest-ranked, non-overlapping chunks (FR22)."""
    picked: list[PackedChunk] = []
    used = 0
    truncated = False
    for ranked in hybrid.ranked:
        hit = ranked.hit
        overlaps = any(
            hit.path == p.path and not (hit.end_line < p.start_line or hit.start_line > p.end_line)
            for p in picked
        )
        if overlaps:
            continue
        body = hit.content or hit.snippet
        candidate = PackedChunk(
            path=hit.path,
            start_line=hit.start_line,
            end_line=hit.end_line,
            symbol=hit.symbol,
            language=hit.language,
            content=body,
            score=round(ranked.fused_score, 6),
            matched_mode=ranked.mode_label,
            stale=hit.stale,
        )
        cost = _cost(candidate)
        if used + cost > max_tokens:
            if picked:
                truncated = True
                break
            # Always return at least one chunk, hard-trimmed to the budget.
            budget_chars = max(0, max_tokens * 4 - 48)
            candidate = PackedChunk(
                path=candidate.path,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                symbol=candidate.symbol,
                language=candidate.language,
                content=body[:budget_chars],
                score=candidate.score,
                matched_mode=candidate.matched_mode,
                stale=candidate.stale,
            )
            cost = _cost(candidate)
            truncated = True
        picked.append(candidate)
        used += cost
        if truncated:
            break
    return CodePack(
        chunks=picked,
        token_estimate=used,
        truncated=truncated or len(picked) < len(hybrid.ranked),
        semantic_available=hybrid.semantic_available,
    )


async def retrieve_context(
    session: AsyncSession,
    *,
    project: str,
    task: str,
    max_tokens: int = 1500,
    scope: SearchScopeName = "project",
    subtree: str | None = None,
    files: list[str] | None = None,
    caller: str | None = None,
) -> dict[str, object]:
    """Token-bounded pack of the most relevant chunks for ``task`` (FR22).

    ``caller`` is optional and gates token-savings logging (None = don't
    record); only the outward-facing MCP tool/HTTP route passes it.
    """
    if not task.strip():
        raise ValueError("task description must not be empty")
    budget = max(1, min(int(max_tokens), 16_000))
    hybrid = await gather_relevant(
        session,
        project=project,
        task=task,
        scope=scope,
        subtree=subtree,
        files=files,
        limit=40,
    )
    pack = pack_code_chunks(hybrid, max_tokens=budget)
    if caller is not None:
        await _record_code_baseline(
            session,
            project=project,
            operation="retrieve_context",
            caller=caller,
            actual_tokens=pack.token_estimate,
            ranked_paths=(r.hit.path for r in hybrid.ranked),
        )
    return {
        "task": task,
        "chunks": [c.as_dict() for c in pack.chunks],
        "token_estimate": pack.token_estimate,
        "token_budget": budget,
        "truncated": pack.truncated,
        "semantic_available": pack.semantic_available,
        "mode": "hybrid" if pack.semantic_available else "keyword",
        "semantic_note": hybrid.semantic_note,
    }


def _clamp_prepare_budget(value: int | None, default: int) -> int:
    if value is None:
        return default
    if not PREPARE_TASK_TOKEN_MIN <= value <= PREPARE_TASK_TOKEN_MAX:
        raise ValueError(
            f"max_tokens must be in [{PREPARE_TASK_TOKEN_MIN}, {PREPARE_TASK_TOKEN_MAX}] (FR9g/D13)"
        )
    return value


async def prepare_task(
    session: AsyncSession,
    *,
    project: str,
    task: str | None = None,
    task_id: str | None = None,
    max_tokens: int | None = None,
    caller: str | None = None,
) -> dict[str, object]:
    """Briefing + relevant-code pack in one budgeted response (FR22, FR22a, D13, T11).

    Curated context is capped at 50% of the budget; when any code chunks exist the
    code pack gets a 30% floor and any unused context budget spills to code. A
    contract/close-gate allocation is capped at 500 estimated tokens inside the
    same total; unused contract budget spills to code (FR22a). The actual split
    is reported (AC19, AC24).

    Exactly one of ``task`` (free text) or ``task_id`` (a planned task's UUID,
    T25/INV-PLAN-5) must be given. ``task_id`` delegates to
    ``pcs.planning.handoff.render_handoff_prompt`` for a bounded, role-neutral
    Markdown handoff prompt instead of this function's own briefing+code pack.
    """
    has_task = bool(task and task.strip())
    has_task_id = bool(task_id and task_id.strip())
    if has_task and has_task_id:
        raise ValueError("exactly one of task or task_id must be provided, not both")
    if not has_task and not has_task_id:
        raise ValueError("exactly one of task or task_id must be provided")
    if has_task_id:
        from pcs.planning.handoff import render_handoff_prompt

        assert task_id is not None
        return await render_handoff_prompt(
            session, project=project, task_id=task_id, max_tokens=max_tokens, caller=caller
        )

    assert task is not None
    row = await resolve_project(session, project)
    budget = _clamp_prepare_budget(
        max_tokens, row.prepare_task_token_budget or PREPARE_TASK_TOKEN_CAP
    )

    context_cap = budget // 2  # 50% cap (FR22a)
    code_floor = (budget * 3) // 10  # 30% floor when chunks exist (FR22a)
    contract_cap = min(CONTRACT_TOKEN_CAP, budget)

    # Fetch a relevance result once so we know whether any code chunks exist.
    hybrid = await gather_relevant(session, project=project, task=task, scope="project", limit=40)
    have_code = bool(hybrid.ranked)

    contract = await get_task_contract(
        session,
        project=project,
        task=task,
        max_tokens=contract_cap,
        ranked_paths=tuple(hit.hit.path for hit in hybrid.ranked),
    )
    contract_tokens = contract.token_estimate
    remaining = budget - contract_tokens

    briefing_budget = max(200, min(context_cap, 4000))
    briefing = await get_project_briefing(session, project=project, max_tokens=briefing_budget)
    context_tokens = estimate_tokens(briefing)
    if context_tokens > context_cap:
        # Regenerate tighter so we never exceed the 50% cap.
        briefing = await get_project_briefing(
            session, project=project, max_tokens=max(200, context_cap)
        )
        context_tokens = estimate_tokens(briefing)

    if have_code and context_tokens > remaining - code_floor:
        tighter = max(200, remaining - code_floor)
        briefing = await get_project_briefing(session, project=project, max_tokens=tighter)
        context_tokens = estimate_tokens(briefing)

    # Unused contract budget spills to code (T11 / FR22a).
    code_budget = max(0, remaining - context_tokens) if have_code else 0
    pack = pack_code_chunks(hybrid, max_tokens=code_budget) if code_budget else _empty_pack(hybrid)

    if caller is not None:
        await _record_prepare_task_baseline(
            session,
            row=row,
            caller=caller,
            context_tokens=context_tokens,
            contract_tokens=contract_tokens,
            code_tokens=pack.token_estimate,
            ranked_paths=(r.hit.path for r in hybrid.ranked),
        )

    return {
        "project": row.name,
        "task": task,
        "briefing": briefing,
        "contract": contract.text,
        "code_chunks": [c.as_dict() for c in pack.chunks],
        "split": {
            "budget": budget,
            "context_tokens": context_tokens,
            "code_tokens": pack.token_estimate,
            "contract_tokens": contract_tokens,
            "contract_cap": contract_cap,
            "context_cap": context_cap,
            "code_floor": code_floor if have_code else 0,
            "code_budget": code_budget,
        },
        "semantic_available": hybrid.semantic_available,
        "mode": "hybrid" if hybrid.semantic_available else "keyword",
        "semantic_note": hybrid.semantic_note,
    }


async def _record_prepare_task_baseline(
    session: AsyncSession,
    *,
    row: Project,
    caller: str,
    context_tokens: int,
    contract_tokens: int,
    code_tokens: int,
    ranked_paths: Iterable[str],
) -> None:
    """Best-effort combined baseline: full-file code content (over every path
    hybrid search found relevant, not just what fit the budget) + the same
    briefing assembly unbounded. The contract sub-part's baseline is left
    equal to its actual (contract is capped at 500 tokens regardless, so this
    barely affects the total — a true contract baseline would need
    TaskContractView to expose its pre-truncation candidate set, which it
    currently doesn't). Never raises."""
    try:
        assembly = await load_assembly_entries(session, row)
        briefing_baseline_text = await asyncio.to_thread(
            assemble_briefing,
            project_name=row.name,
            entries=assembly,
            budget_tokens=_UNBOUNDED_BUDGET,
        )
        code_baseline = full_file_tokens(row.root_path, ranked_paths)
        baseline = code_baseline + estimate_tokens(briefing_baseline_text) + contract_tokens
        actual = context_tokens + contract_tokens + code_tokens
        await record_token_savings(
            session,
            project_id=row.id,
            operation="prepare_task",
            caller=caller,
            actual_tokens=actual,
            baseline_tokens=baseline,
        )
    except Exception:
        logger.warning(
            "token_savings_record_failed", extra={"context": {"operation": "prepare_task"}}
        )


def _empty_pack(hybrid: HybridResult) -> CodePack:
    return CodePack(
        chunks=[],
        token_estimate=0,
        truncated=False,
        semantic_available=hybrid.semantic_available,
    )
