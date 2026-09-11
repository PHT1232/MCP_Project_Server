"""Token-bounded relevant-code packs: ``retrieve_context`` and ``prepare_task``.

FR22 / FR22a / D13. Built on hybrid search — no FTS/vector SQL here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.assembly import estimate_tokens
from pcs.context.service import get_project_briefing, resolve_project
from pcs.context.types import (
    PREPARE_TASK_TOKEN_CAP,
    PREPARE_TASK_TOKEN_MAX,
    PREPARE_TASK_TOKEN_MIN,
)
from pcs.index.hybrid import HybridResult, gather_relevant
from pcs.index.search import SearchScopeName
from pcs.requirements.briefing import CONTRACT_TOKEN_CAP, get_task_contract


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
) -> dict[str, object]:
    """Token-bounded pack of the most relevant chunks for ``task`` (FR22)."""
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
    return {
        "task": task,
        "chunks": [c.as_dict() for c in pack.chunks],
        "token_estimate": pack.token_estimate,
        "token_budget": budget,
        "truncated": pack.truncated,
        "semantic_available": pack.semantic_available,
        "mode": "hybrid" if pack.semantic_available else "keyword",
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
    task: str,
    max_tokens: int | None = None,
) -> dict[str, object]:
    """Briefing + relevant-code pack in one budgeted response (FR22, FR22a, D13, T11).

    Curated context is capped at 50% of the budget; when any code chunks exist the
    code pack gets a 30% floor and any unused context budget spills to code. A
    contract/close-gate allocation is capped at 500 estimated tokens inside the
    same total; unused contract budget spills to code (FR22a). The actual split
    is reported (AC19, AC24).
    """
    if not task.strip():
        raise ValueError("task description must not be empty")
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
    }


def _empty_pack(hybrid: HybridResult) -> CodePack:
    return CodePack(
        chunks=[],
        token_estimate=0,
        truncated=False,
        semantic_available=hybrid.semantic_available,
    )
