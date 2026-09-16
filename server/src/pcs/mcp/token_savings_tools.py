"""MCP tools for reading the token-savings log.

Read-only — writes happen as a side effect of retrieve_context, search_code,
prepare_task, and get_project_briefing themselves (pcs.token_savings.service).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.mcp.support import run_tool
from pcs.token_savings.service import get_token_savings_summary as _get_summary
from pcs.token_savings.service import list_token_savings as _list_entries


def register_token_savings_tools(mcp: FastMCP) -> None:
    """Attach ``get_token_savings_log`` and ``get_token_savings_summary``."""

    @mcp.tool()
    async def get_token_savings_log(
        project: str | None = None,
        operation: str | None = None,
        limit: int = 100,
        ctx: Context[Any, Any] | None = None,
    ) -> list[dict[str, object]]:
        """Most-recent-first token-savings log entries.

        Args:
            project: Exact project name or id (D3).
            operation: Optional filter — one of ``retrieve_context``,
                ``search_code``, ``prepare_task``, ``get_project_briefing``.
            limit: Max entries returned (1-500, default 100).
        """

        async def op(session: AsyncSession) -> list[dict[str, object]]:
            return await _list_entries(session, project or "", operation=operation, limit=limit)

        return await run_tool("get_token_savings_log", project, ctx, op)

    @mcp.tool()
    async def get_token_savings_summary(
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Overall totals plus a per-operation breakdown of tokens saved."""

        async def op(session: AsyncSession) -> dict[str, object]:
            return await _get_summary(session, project or "")

        return await run_tool("get_token_savings_summary", project, ctx, op)
