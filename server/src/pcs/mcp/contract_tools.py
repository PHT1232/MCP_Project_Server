"""MCP tools for compact requirement-contract retrieval (T11).

Thin wrappers: resolve caller → session_scope → ``pcs.requirements.briefing``
→ ``log_tool_call`` (NFR6). No SQL here.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.mcp.support import run_tool
from pcs.requirements import briefing


def register_contract_tools(mcp: FastMCP) -> None:
    """Attach ``get_requirement_contract`` and ``get_task_contract``."""

    @mcp.tool()
    async def get_requirement_contract(
        requirement_id: str,
        project: str | None = None,
        include: str = "both",
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Verbatim invariant/criterion drill-down for one requirement (T11).

        Args:
            requirement_id: Store entry id of the requirement.
            project: Exact project name or id (D3).
            include: ``invariants``, ``criteria``, or ``both`` (default).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await briefing.get_requirement_contract(
                session,
                project=project or "",
                requirement_id=requirement_id,
                include=include,
            )

        return await run_tool("get_requirement_contract", project, ctx, op)

    @mcp.tool()
    async def get_task_contract(
        task: str,
        project: str | None = None,
        requirement_ids: list[str] | None = None,
        max_tokens: int = 500,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Relevant active contract statements plus a compact close-gate (T11).

        Capped at 500 estimated tokens. T12 evidence, if absent, is reported as
        ``review: not-configured``. Full statements stay on
        ``get_requirement_contract``.

        Args:
            task: Current task description used for relevance ranking.
            project: Exact project name or id (D3).
            requirement_ids: Optional explicit requirement entry ids (max 3 used).
            max_tokens: Compact budget, clamped to 1-500.
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await briefing.get_task_contract(
                session,
                project=project or "",
                task=task,
                requirement_ids=requirement_ids,
                max_tokens=max_tokens,
            )
            return view.as_dict()

        return await run_tool("get_task_contract", project, ctx, op)
