"""MCP tool for full project-context export (Markdown / JSON)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.context.export import EXPORT_FORMAT_MARKDOWN
from pcs.context.export import export_project_context as export_context
from pcs.mcp.support import run_tool


def register_export_tools(mcp: FastMCP) -> None:
    """Attach ``export_project_context``."""

    @mcp.tool()
    async def export_project_context(
        project: str | None = None,
        format: str = EXPORT_FORMAT_MARKDOWN,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Export every context-store section verbatim as Markdown or JSON.

        Args:
            project: Exact project name or id (D3).
            format: ``markdown`` (default) or ``json``. Invalid values error.

        Returns a download envelope: ``format``, ``filename``, ``media_type``,
        ``content`` (full body, no truncation), plus ``project`` and
        ``exported_at``. Requirements entries are entry-level only — no
        invariants, acceptance criteria, or evidence are nested.
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await export_context(session, project=project or "", format=format)

        return await run_tool("export_project_context", project, ctx, op)
