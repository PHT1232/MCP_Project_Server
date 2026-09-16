"""Record and query the token-savings log.

``record_token_savings`` is called from inside retrieve_context, search_code,
prepare_task, and get_project_briefing themselves (gated on an explicit
``caller`` argument — ``None`` means "don't record," which every existing
internal call site keeps using unchanged) rather than at the MCP/HTTP
wrapper layer, because baseline computation needs data (the full ranked
candidate set, the full assembled-entries list) that isn't retained in
those functions' return values.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.service import resolve_project
from pcs.token_savings.models import OPERATIONS, TokenSavingsLogEntry

__all__ = [
    "OPERATIONS",
    "OperationSummary",
    "get_token_savings_summary",
    "list_token_savings",
    "record_token_savings",
]

LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 500


async def record_token_savings(
    session: AsyncSession,
    *,
    project_id: str,
    operation: str,
    caller: str,
    actual_tokens: int,
    baseline_tokens: int,
) -> None:
    """Append one row. Never raises past a malformed input; callers should
    additionally wrap this in a broad try/except so a logging failure never
    breaks the retrieval call it describes."""
    if operation not in OPERATIONS:
        raise ValueError(f"operation must be one of {OPERATIONS}")
    actual = max(0, int(actual_tokens))
    baseline = max(0, int(baseline_tokens))
    saved = max(0, baseline - actual)
    session.add(
        TokenSavingsLogEntry(
            project_id=project_id,
            operation=operation,
            caller=caller.strip()[:120] or "agent",
            actual_tokens=actual,
            baseline_tokens=baseline,
            saved_tokens=saved,
        )
    )
    await session.flush()


def _entry_dict(row: TokenSavingsLogEntry) -> dict[str, object]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "operation": row.operation,
        "caller": row.caller,
        "actual_tokens": row.actual_tokens,
        "baseline_tokens": row.baseline_tokens,
        "saved_tokens": row.saved_tokens,
        "created_at": row.created_at.isoformat(),
    }


async def list_token_savings(
    session: AsyncSession,
    project: str,
    *,
    operation: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
) -> list[dict[str, object]]:
    """Most-recent-first log entries, optionally filtered to one operation."""
    if operation is not None and operation not in OPERATIONS:
        raise ValueError(f"operation must be one of {OPERATIONS}")
    bounded_limit = max(1, min(int(limit), LIST_LIMIT_MAX))
    row = await resolve_project(session, project)
    stmt = (
        select(TokenSavingsLogEntry)
        .where(TokenSavingsLogEntry.project_id == row.id)
        .order_by(TokenSavingsLogEntry.created_at.desc())
        .limit(bounded_limit)
    )
    if operation is not None:
        stmt = stmt.where(TokenSavingsLogEntry.operation == operation)
    result = await session.execute(stmt)
    return [_entry_dict(entry) for entry in result.scalars().all()]


@dataclass(frozen=True)
class OperationSummary:
    """Aggregate totals for one operation (or overall, when ``operation`` is None)."""

    operation: str | None
    call_count: int
    actual_tokens_total: int
    baseline_tokens_total: int
    saved_tokens_total: int

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "call_count": self.call_count,
            "actual_tokens_total": self.actual_tokens_total,
            "baseline_tokens_total": self.baseline_tokens_total,
            "saved_tokens_total": self.saved_tokens_total,
        }


async def get_token_savings_summary(session: AsyncSession, project: str) -> dict[str, object]:
    """Overall totals plus a per-operation breakdown, for the summary cards."""
    row = await resolve_project(session, project)
    stmt = (
        select(
            TokenSavingsLogEntry.operation,
            func.count(TokenSavingsLogEntry.id),
            func.coalesce(func.sum(TokenSavingsLogEntry.actual_tokens), 0),
            func.coalesce(func.sum(TokenSavingsLogEntry.baseline_tokens), 0),
            func.coalesce(func.sum(TokenSavingsLogEntry.saved_tokens), 0),
        )
        .where(TokenSavingsLogEntry.project_id == row.id)
        .group_by(TokenSavingsLogEntry.operation)
    )
    result = await session.execute(stmt)
    by_operation = [
        OperationSummary(
            operation=operation,
            call_count=call_count,
            actual_tokens_total=actual_total,
            baseline_tokens_total=baseline_total,
            saved_tokens_total=saved_total,
        )
        for operation, call_count, actual_total, baseline_total, saved_total in result.all()
    ]
    overall = OperationSummary(
        operation=None,
        call_count=sum(s.call_count for s in by_operation),
        actual_tokens_total=sum(s.actual_tokens_total for s in by_operation),
        baseline_tokens_total=sum(s.baseline_tokens_total for s in by_operation),
        saved_tokens_total=sum(s.saved_tokens_total for s in by_operation),
    )
    return {
        "overall": overall.as_dict(),
        "by_operation": [s.as_dict() for s in by_operation],
    }
