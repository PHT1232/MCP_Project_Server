"""MCP surface for the code map: the ``get_code_map`` tool + ``code-map`` resource.

Thin wrappers over :mod:`pcs.codemap.service` (no graph logic here). Every call
emits the NFR6 audit line via :func:`pcs.mcp.support.run_tool`.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from pcs.codemap import service as codemap_service
from pcs.db.base import session_scope
from pcs.mcp.support import run_tool


def register_codemap_tools(mcp: FastMCP) -> None:
    """Attach ``get_code_map`` and the ``context://{project}/code-map`` resource."""

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

    @mcp.resource("context://{project}/code-map")
    async def code_map_resource(project: str) -> str:
        """The project's top-tier code map as JSON (FR32a, FR7). Expand via get_code_map."""
        async with session_scope() as session:
            payload = await codemap_service.get_code_map(session, project=project)
        return json.dumps(payload, indent=2, default=str)
