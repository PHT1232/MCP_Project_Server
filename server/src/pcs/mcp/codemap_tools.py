"""MCP surface for the code map and codebase guide (FR32a, FR43, D18, T16).

Thin wrappers over :mod:`pcs.codemap.service` and :mod:`pcs.codemap.guide`.
Every call emits the NFR6 audit line via :func:`pcs.mcp.support.run_tool`.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.codemap import guide
from pcs.codemap import service as codemap_service
from pcs.context.types import ValidationError
from pcs.db.base import session_scope
from pcs.mcp.support import caller, run_tool


def register_codemap_tools(mcp: FastMCP) -> None:
    """Attach code-map and codebase-guide MCP tools and resources."""

    @mcp.tool()
    async def get_code_map(
        project: str | None = None,
        scope: str | None = None,
        depth: int = codemap_service.DEFAULT_DEPTH,
        include_external: bool = False,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Aggregated dependency/structure graph for one tier of a project (FR32, FR32a).

        Args:
            project: Exact project name or id (D3).
            scope: Repo-relative subtree path to expand, or an indexed file path
                for its symbol view. Omit for the repo's top directory tier.
            depth: Levels below ``scope`` to reveal (1..3). Default 1.
            include_external: Also emit aggregated edges to external packages.

        The response only ever describes the requested tier — expanding a scope
        never re-sends the rest of the graph (D9, AC20).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await codemap_service.get_code_map(
                session,
                project=project or "",
                scope=scope,
                depth=depth,
                include_external=include_external,
            )

        return await run_tool("get_code_map", project, ctx, op)

    @mcp.tool()
    async def get_codebase_guide(
        project: str | None = None,
        scope: str | None = None,
        include: str = "all",
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Agent-authored per-file documentation and index facts (FR43, D18, T16).

        Args:
            project: Exact project name or id (D3).
            scope: Repo-relative subtree directory or file to filter by.
            include: 'all' (default), 'documented', 'undocumented', or 'stale'.
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await guide.get_codebase_guide(
                session,
                project=project or "",
                scope=scope,
                include=include,
            )

        return await run_tool("get_codebase_guide", project, ctx, op)

    @mcp.tool()
    async def describe_files(
        notes: list[dict[str, str]],
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Upsert or delete agent-authored per-file summaries (FR43, D18, T16).

        Args:
            notes: List of {"path": "...", "summary": "..."} mappings.
                Empty summary deletes a note.
            project: Exact project name or id (D3).
        """
        if not isinstance(notes, list):
            raise ValidationError("notes must be a list of objects")

        who = caller(ctx)

        async def op(session: AsyncSession) -> dict[str, object]:
            return await guide.describe_files(
                session,
                project=project or "",
                notes=notes,
                author=who,
            )

        return await run_tool("describe_files", project, ctx, op)

    @mcp.tool()
    async def sync_codebase_guide(
        project: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, object]:
        """Regenerate the git-tracked codebase guide Markdown file (FR43, D18, T16).

        Args:
            project: Exact project name or id (D3).
        """

        async def op(session: AsyncSession) -> dict[str, object]:
            return await guide.write_guide_file(
                session,
                project=project or "",
            )

        return await run_tool("sync_codebase_guide", project, ctx, op)

    @mcp.resource("context://{project}/code-map")
    async def code_map_resource(project: str) -> str:
        """The project's top-tier code map as JSON (FR32a, FR7). Expand via get_code_map."""
        async with session_scope() as session:
            payload = await codemap_service.get_code_map(session, project=project)
        return json.dumps(payload, indent=2, default=str)

    @mcp.resource("context://{project}/codebase-guide")
    async def codebase_guide_resource(project: str) -> str:
        """The project's codebase guide as Markdown (FR43, D18, T16)."""
        async with session_scope() as session:
            data = await guide.get_codebase_guide(
                session,
                project=project,
                include=guide.INCLUDE_ALL,
            )
            return guide.render_guide_markdown(data)
