"""MCP tools for the keyword/structural code index (FR22 keyword, FR26, FR27)."""

from __future__ import annotations

from typing import Any, cast

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.index import service
from pcs.index.search import SearchScopeName
from pcs.mcp.support import run_tool

_SCOPES: frozenset[str] = frozenset({"project", "subtree", "files", "focus"})


def register_index_tools(mcp: FastMCP) -> None:
    """Attach ``get_index_status``, ``reindex``, and keyword ``search_code``."""

    @mcp.tool()
    async def get_index_status(
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Index timestamps, file/chunk counts, and skipped-with-reason (FR26)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.get_index_status(session, project=project or "")
            return view.as_dict()

        return await run_tool("get_index_status", project, ctx, op)

    @mcp.tool()
    async def reindex(
        project: str | None = None,
        incremental: bool = True,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Rebuild the code index; incremental updates changed files only (FR24, FR27)."""

        async def op(session: AsyncSession) -> dict[str, object]:
            view = await service.reindex(session, project=project or "", incremental=incremental)
            return view.as_dict()

        return await run_tool("reindex", project, ctx, op)

    @mcp.tool()
    async def search_code(
        query: str,
        project: str | None = None,
        scope: str = "project",
        subtree: str | None = None,
        files: list[str] | None = None,
        globs: list[str] | None = None,
        limit: int = 20,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Keyword/structural search (FR20, FR21, FR29). Semantic ranking is T04.

        Args:
            query: Exact/fuzzy text, symbol-ish name, or a path glob.
            project: Exact project name or id (D3).
            scope: ``project``, ``subtree``, ``files``, or ``focus``.
            subtree: Repo-relative directory when ``scope='subtree'``.
            files: Repo-relative paths when ``scope='files'``.
            globs: Optional path globs (e.g. ``**/*.py``).
            limit: Max hits (1-100).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            if scope not in _SCOPES:
                raise ValueError(f"scope must be one of {sorted(_SCOPES)}; got {scope!r}")
            return await service.search_code(
                session,
                project=project or "",
                query=query,
                scope=cast(SearchScopeName, scope),
                subtree=subtree,
                files=files,
                globs=globs,
                limit=limit,
            )

        return await run_tool("search_code", project, ctx, op)
